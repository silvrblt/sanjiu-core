#!/usr/bin/env python3
"""三审九方流转状态机 v1（2026-09-29，阶段2 C5 门禁实现；二审对抗打回后修复版）

职责（定稿 R02/R03/R07）：
1. 材料包硬校验：六类包 schema 校验，不符即拒（FLOW_ERR_SCHEMA）；
2. 防扯皮硬计数：每级 对抗≤1轮 / 裁决≤1轮 / 上诉仅1次，超限熔断转人工；计数持久化（~/.sanjiu/flow_gate_state.json，原子写）；
3. 回执闸门：立案庭三选一判决签回执（HMAC-SHA256，密钥 ~/.sanjiu/flow_gate_secret 自动生成 600 权限，禁弱默认密钥），桥接入口 gate_check 无合法回执拒绝审计调用；
4. 三选一判决（唯一事实源 = routing_rules.yaml flow_signals 节，内置信号仅为 yaml 缺失时的兜底）。

用法：
  python3 flow_gate.py --selftest
  python3 flow_gate.py --route <任务卡.json>              # 输出回执 JSON
  python3 flow_gate.py --gate <回执.json> <任务卡.json>    # 桥接入口闸门校验
"""
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone

import jsonschema
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(HERE, "schemas", "flow-packages.schema.json")
RULES_PATH = os.path.join(HERE, "routing_rules.yaml")
STATE_DIR = os.path.expanduser("~/.sanjiu")
STATE_PATH = os.path.join(STATE_DIR, "flow_gate_state.json")
SECRET_PATH = os.path.join(STATE_DIR, "flow_gate_secret")

# 错误码（定稿 Q7：拒绝码与 schema 同源）
FLOW_ERR_SCHEMA = "FLOW_ERR_SCHEMA"            # 材料包不符 schema
FLOW_ERR_ROUND_LIMIT = "FLOW_ERR_ROUND_LIMIT"  # 轮次超限（熔断转人工）
FLOW_ERR_NO_RECEIPT = "FLOW_ERR_NO_RECEIPT"    # 无回执
FLOW_ERR_BAD_RECEIPT = "FLOW_ERR_BAD_RECEIPT"  # 回执校验失败
FLOW_ERR_MELTDOWN = "FLOW_ERR_MELTDOWN"        # 已熔断
FLOW_ERR_UNKNOWN_PACKAGE = "FLOW_ERR_UNKNOWN_PACKAGE"

# 三选一信号兜底（唯一事实源 = routing_rules.yaml flow_signals 节；此处仅 yaml 缺失时兜底）
FALLBACK_SIGNALS = {
    "forced_domains": ["对外交付", "资金", "财务", "法律", "安全", "框架", "部署",
                       "external_delivery", "finance", "legal", "security", "framework_change"],
    "direct_hints": ["问答", "闲聊", "聊天", "翻译一下", "解释一下", "这是什么", "帮我查", "qa"],
}


def _load_signals():
    if not os.path.exists(RULES_PATH):
        return dict(FALLBACK_SIGNALS)  # 唯一兜底：yaml 文件缺失
    with open(RULES_PATH, encoding="utf-8") as f:
        rules = yaml.safe_load(f) or {}
    sig = rules.get("flow_signals")
    if not sig or not sig.get("forced_domains") or not sig.get("direct_hints"):
        raise ValueError("routing_rules.yaml flow_signals 节缺失/为空：拒绝静默兜底（唯一事实源）")
    return {"forced_domains": list(sig["forced_domains"]),
            "direct_hints": list(sig["direct_hints"])}


def _load_secret():
    """密钥：FLOW_GATE_SECRET 环境变量 > ~/.sanjiu/flow_gate_secret 持久文件（自动生成）。"""
    if os.environ.get("FLOW_GATE_SECRET"):
        return os.environ["FLOW_GATE_SECRET"].encode("utf-8")
    if not os.path.exists(SECRET_PATH):
        os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
        secret = os.urandom(32).hex()
        with open(SECRET_PATH, "w", encoding="utf-8") as f:
            f.write(secret)
        os.chmod(SECRET_PATH, 0o600)
    with open(SECRET_PATH, encoding="utf-8") as f:
        return f.read().strip().encode("utf-8")


class RoundCounter:
    """防扯皮硬计数（R07）：lead_audit/judge/appeal 每级各 1 次上限；状态持久化。"""

    LIMITS = {"lead_audit": 1, "judge": 1, "appeal": 1}

    def __init__(self):
        self.path = STATE_PATH
        self.state = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self):
        os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False)
        os.replace(tmp, self.path)  # 原子写

    def allow(self, task_id, action):
        if action not in self.LIMITS:
            return False, FLOW_ERR_UNKNOWN_PACKAGE
        counts = self.state.setdefault(task_id, {})
        if counts.get(action, 0) >= self.LIMITS[action]:
            self._save()
            return False, FLOW_ERR_ROUND_LIMIT
        counts[action] = counts.get(action, 0) + 1
        self._save()
        return True, None

    def reset(self, task_id):
        self.state.pop(task_id, None)
        self._save()


class FlowGate:
    def __init__(self):
        self.secret = _load_secret()
        self.signals = _load_signals()
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            self.schema = json.load(f)
        self.counter = RoundCounter()
        self.meltdown = set(self.counter.state.get("__meltdown__", []))

    def _mark_meltdown(self, task_id):
        self.meltdown.add(task_id)
        self.counter.state["__meltdown__"] = sorted(self.meltdown)
        self.counter._save()

    def reset_task(self, task_id):
        """复位任务全部状态：轮次计数 + 熔断标记（持久化同步）。"""
        self.counter.reset(task_id)
        self.meltdown.discard(task_id)
        self.counter.state["__meltdown__"] = sorted(self.meltdown)
        self.counter._save()

    # ---- 1. 材料包硬校验 ----
    def validate_package(self, pkg):
        if not isinstance(pkg, dict):
            return False, [FLOW_ERR_SCHEMA], ["not an object"]
        try:
            jsonschema.validate(pkg, self.schema)
            return True, [], []
        except jsonschema.ValidationError as e:
            return False, [FLOW_ERR_SCHEMA], [e.message]

    # ---- 2. 防扯皮硬计数（持久化）----
    def check_round(self, task_id, action):
        if task_id in self.meltdown:
            return False, FLOW_ERR_MELTDOWN, "已熔断：转人工"
        ok, err = self.counter.allow(task_id, action)
        if not ok:
            self._mark_meltdown(task_id)  # 超限熔断
            return False, FLOW_ERR_MELTDOWN, f"轮次超限({action})：熔断转人工"
        return True, None, None

    # ---- 3. 回执闸门 ----
    def _sig_body(self, receipt_id, combo, task_type, issued_at, card_sha256):
        return f"{receipt_id}|{combo}|{task_type}|{issued_at}|{card_sha256}".encode("utf-8")

    def issue_receipt(self, card, combo, task_type):
        card_sha256 = hashlib.sha256(
            json.dumps(card, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        receipt_id = os.urandom(8).hex()
        issued_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        signature = hmac.new(self.secret, self._sig_body(
            receipt_id, combo, task_type, issued_at, card_sha256), hashlib.sha256).hexdigest()
        return {
            "package_version": "1.0",
            "package_type": "receipt",
            "task_id": str(card.get("title", ""))[:64],
            "receipt_id": receipt_id,
            "combo": combo,
            "task_type": task_type,
            "issued_at": issued_at,
            "card_sha256": card_sha256,
            "signature": signature,
        }

    def verify_receipt(self, receipt, card):
        try:
            if receipt.get("combo") not in ("direct", "A", "B"):
                return False
            body = self._sig_body(receipt["receipt_id"], receipt["combo"],
                                  receipt["task_type"], receipt["issued_at"],
                                  receipt["card_sha256"])
            expect = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
            card_sha256 = hashlib.sha256(
                json.dumps(card, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            return hmac.compare_digest(expect, receipt.get("signature", "")) \
                and receipt["card_sha256"] == card_sha256
        except (KeyError, TypeError):
            return False

    def gate_check(self, receipt, card):
        """桥接入口闸门：审计/流转调用前必须携带合法回执。"""
        if receipt is None:
            return False, FLOW_ERR_NO_RECEIPT
        if not self.verify_receipt(receipt, card):
            return False, FLOW_ERR_BAD_RECEIPT
        return True, None

    # ---- 4. 三选一判决（唯一事实源 routing_rules.yaml flow_signals）----
    def route(self, card):
        text = " ".join(str(card.get(k) or "") for k in ("title", "description", "prompt", "type"))
        if card.get("domain") in self.signals["forced_domains"] \
                or any(k in text for k in self.signals["forced_domains"]):
            return "B"
        if card.get("type") == "qa" or any(k in text for k in self.signals["direct_hints"]):
            return "direct"
        return "A"


def _selftest():
    gate = FlowGate()
    fails = []
    total = 0
    _pid = str(os.getpid())  # 自测任务隔离：避免历史状态文件残留干扰断言

    def check(name, cond):
        nonlocal total
        total += 1
        if not cond:
            fails.append(name)
        print(("PASS " if cond else "FAIL ") + name)

    # 1. schema 硬校验
    lead_ok = {"package_version": "1.0", "package_type": "lead_package", "task_id": f"t1-{_pid}",
               "user_quote": "原话", "requirement_analysis": "a", "proposal": "p", "basis": "b"}
    check("lead_package 完整通过", gate.validate_package(lead_ok)[0])
    lead_bad = dict(lead_ok); lead_bad.pop("user_quote")
    check("lead_package 缺 user_quote 拒绝", not gate.validate_package(lead_bad)[0])
    appeal_ok = {"package_version": "1.0", "package_type": "appeal_package", "task_id": f"t1-{_pid}",
                 "background": "背景", "objection_items": [{"issue_id": "i1", "objection": "o", "basis": "b"}]}
    check("appeal_package 通过", gate.validate_package(appeal_ok)[0])
    appeal_full = dict(appeal_ok); appeal_full["full_context"] = "全套材料（违规）"
    check("appeal_package 带全量上下文拒绝", not gate.validate_package(appeal_full)[0])
    audit_bad = {"package_version": "1.0", "package_type": "audit_package", "task_id": f"t1-{_pid}",
                 "verdict": "reject", "issue_list": [], "evidence_mapping": [], "returned_to_lead": False}
    check("audit_package 未返还承办拒绝", not gate.validate_package(audit_bad)[0])
    judge_in = {"package_version": "1.0", "package_type": "judge_input_package", "task_id": f"t1-{_pid}",
                "user_quote": "原话", "lead_analysis": "a", "audit_opinion": "o",
                "questions_to_adjudicate": ["q1"]}
    check("judge_input 四字段通过", gate.validate_package(judge_in)[0])
    final_pkg = {"package_version": "1.0", "package_type": "final_package", "task_id": f"t1-{_pid}",
                 "background": "b", "dispute": "d", "business_impact": "i", "options": ["o1"]}
    check("final_package 通过", gate.validate_package(final_pkg)[0])

    # 2. 防扯皮硬计数（含持久化跨实例）
    card = {"title": f"t1-{_pid}"}
    ok, _, _ = gate.check_round(f"t1-{_pid}", "lead_audit")
    check("第一轮对抗放行", ok)
    ok2, err2, _ = gate.check_round(f"t1-{_pid}", "lead_audit")
    check("第二轮对抗熔断", (not ok2) and err2 == FLOW_ERR_MELTDOWN)
    gate2 = FlowGate()
    check("熔断状态跨实例持久化", f"t1-{_pid}" in gate2.meltdown)
    gate.reset_task(f"t1-{_pid}")
    ok, _, _ = gate.check_round(f"t1-{_pid}", "appeal")
    ok2, err2, _ = gate.check_round(f"t1-{_pid}", "appeal")
    check("第二次上诉熔断", (not ok2) and err2 == FLOW_ERR_MELTDOWN)
    gate.reset_task(f"t1-{_pid}")

    # 3. 回执闸门
    r = gate.issue_receipt(card, "A", "code_gen")
    ok, err = gate.gate_check(r, card)
    check("合法回执通过", ok and err is None)
    tampered = dict(card); tampered["title"] = "t1-改"
    ok, err = gate.gate_check(r, tampered)
    check("任务卡被篡改拒绝", (not ok) and err == FLOW_ERR_BAD_RECEIPT)
    ok, err = gate.gate_check(None, card)
    check("无回执拒绝", (not ok) and err == FLOW_ERR_NO_RECEIPT)

    # 4. 三选一判决
    check("强制域->B", gate.route({"title": "对外交付材料"}) == "B")
    check("问答->direct", gate.route({"type": "qa"}) == "direct")
    check("默认->A", gate.route({"title": "写个工具"}) == "A")
    check("三选一无第四值", gate.route({"title": "单文件 bugfix"}) == "A")

    print(f"\n共 {total} 项断言，失败 {len(fails)}")
    return 1 if fails else 0


def main(argv):
    if "--selftest" in argv:
        sys.exit(_selftest())
    gate = FlowGate()
    if "--route" in argv:
        card = json.load(open(argv[argv.index("--route") + 1], encoding="utf-8"))
        combo = gate.route(card)
        print(json.dumps(gate.issue_receipt(card, combo, card.get("type", "")), ensure_ascii=False, indent=1))
        return 0
    if "--gate" in argv:
        receipt = json.load(open(argv[argv.index("--gate") + 1], encoding="utf-8"))
        card = json.load(open(argv[argv.index("--gate") + 2], encoding="utf-8"))
        ok, err = gate.gate_check(receipt, card)
        print(json.dumps({"ok": ok, "err": err}, ensure_ascii=False))
        return 0 if ok else 2
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
