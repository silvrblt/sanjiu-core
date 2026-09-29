#!/usr/bin/env python3
"""三审九方流转状态机 v0（2026-09-29，阶段2 C5 门禁实现）

职责（定稿 R02/R03/R07）：
1. 材料包硬校验：六类包 schema 校验，不符即拒（FLOW_ERR_SCHEMA）；
2. 防扯皮硬计数：每级 对抗≤1轮 / 裁决≤1轮 / 上诉仅1次，超限熔断转人工；
3. 回执闸门：立案庭三选一判决签回执，桥接入口 gate_check 无合法回执拒绝审计调用；
4. 三选一判决：v0 规则版（关键词信号），模型判决可经 lead_route 接入。

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

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(HERE, "schemas", "flow-packages.schema.json")

# 错误码（定稿 Q7：拒绝码与 schema 同源）
FLOW_ERR_SCHEMA = "FLOW_ERR_SCHEMA"            # 材料包不符 schema
FLOW_ERR_ROUND_LIMIT = "FLOW_ERR_ROUND_LIMIT"  # 轮次超限（熔断转人工）
FLOW_ERR_NO_RECEIPT = "FLOW_ERR_NO_RECEIPT"    # 无回执
FLOW_ERR_BAD_RECEIPT = "FLOW_ERR_BAD_RECEIPT"  # 回执校验失败
FLOW_ERR_MELTDOWN = "FLOW_ERR_MELTDOWN"        # 已熔断
FLOW_ERR_UNKNOWN_PACKAGE = "FLOW_ERR_UNKNOWN_PACKAGE"

# 强制域信号（routing_rules.yaml 同源语义，v0 规则版）
FORCED_DOMAINS = ["对外交付", "资金", "财务", "法律", "安全", "框架", "部署", "external_delivery",
                  "finance", "legal", "security", "framework_change"]
DIRECT_HINTS = ["问答", "闲聊", "聊天", "翻译一下", "解释一下", "这是什么", "帮我查"]
BUGFIX_HINTS = ["单文件", "bugfix", "一行", "小修", "改个错别字"]


class RoundCounter:
    """防扯皮硬计数（R07）：lead_audit/judge/appeal 每级各 1 次上限。"""

    LIMITS = {"lead_audit": 1, "judge": 1, "appeal": 1}

    def __init__(self):
        self.state = {}  # task_id -> {action: count}

    def allow(self, task_id, action):
        if action not in self.LIMITS:
            return False, FLOW_ERR_UNKNOWN_PACKAGE
        counts = self.state.setdefault(task_id, {})
        if counts.get(action, 0) >= self.LIMITS[action]:
            return False, FLOW_ERR_ROUND_LIMIT
        counts[action] = counts.get(action, 0) + 1
        return True, None

    def reset(self, task_id):
        self.state.pop(task_id, None)


class FlowGate:
    def __init__(self, secret=None):
        raw = secret or os.environ.get("FLOW_GATE_SECRET") or "dev-insecure-do-not-use-in-prod"
        self.secret = raw.encode("utf-8")
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            self.schema = json.load(f)
        self.counter = RoundCounter()
        self.meltdown = set()  # 已熔断 task_id

    # ---- 1. 材料包硬校验 ----
    def validate_package(self, pkg):
        if not isinstance(pkg, dict):
            return False, [FLOW_ERR_SCHEMA], ["not an object"]
        try:
            jsonschema.validate(pkg, self.schema)
            return True, [], []
        except jsonschema.ValidationError as e:
            return False, [FLOW_ERR_SCHEMA], [e.message]

    # ---- 2. 防扯皮硬计数 ----
    def check_round(self, task_id, action):
        if task_id in self.meltdown:
            return False, FLOW_ERR_MELTDOWN, "已熔断：转人工"
        ok, err = self.counter.allow(task_id, action)
        if not ok:
            self.meltdown.add(task_id)  # 超限熔断
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
            "task_id": card.get("title", "")[:64],
            "receipt_id": receipt_id,
            "combo": combo,
            "task_type": task_type,
            "issued_at": issued_at,
            "card_sha256": card_sha256,
            "signature": signature,
        }

    def verify_receipt(self, receipt, card):
        try:
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

    # ---- 4. 三选一判决（v0 规则版）----
    def route(self, card):
        text = " ".join(str(card.get(k) or "") for k in ("title", "description", "prompt", "type"))
        if card.get("domain") in FORCED_DOMAINS or any(k in text for k in FORCED_DOMAINS):
            combo = "B"
        elif any(k in text for k in BUGFIX_HINTS):
            combo = "A_exception"
        elif card.get("type") == "qa" or any(k in text for k in DIRECT_HINTS):
            combo = "direct"
        else:
            combo = "A"
        return combo


def _selftest():
    gate = FlowGate()
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)
        print(("PASS " if cond else "FAIL ") + name)

    # 1. schema 硬校验
    lead_ok = {"package_version": "1.0", "package_type": "lead_package", "task_id": "t1",
               "user_quote": "原话", "requirement_analysis": "a", "proposal": "p", "basis": "b"}
    check("lead_package 完整通过", gate.validate_package(lead_ok)[0])
    lead_bad = dict(lead_ok); lead_bad.pop("user_quote")
    check("lead_package 缺 user_quote 拒绝", not gate.validate_package(lead_bad)[0])
    appeal_ok = {"package_version": "1.0", "package_type": "appeal_package", "task_id": "t1",
                 "background": "背景", "objection_items": [{"issue_id": "i1", "objection": "o", "basis": "b"}]}
    check("appeal_package 通过", gate.validate_package(appeal_ok)[0])
    appeal_full = dict(appeal_ok); appeal_full["full_context"] = "全套材料（违规）"
    check("appeal_package 带全量上下文拒绝", not gate.validate_package(appeal_full)[0])
    audit_bad = {"package_version": "1.0", "package_type": "audit_package", "task_id": "t1",
                 "verdict": "reject", "issue_list": [], "evidence_mapping": [], "returned_to_lead": False}
    check("audit_package 未返还承办拒绝", not gate.validate_package(audit_bad)[0])
    judge_in = {"package_version": "1.0", "package_type": "judge_input_package", "task_id": "t1",
                "user_quote": "原话", "lead_analysis": "a", "audit_opinion": "o",
                "questions_to_adjudicate": ["q1"]}
    check("judge_input 四字段通过", gate.validate_package(judge_in)[0])
    final_pkg = {"package_version": "1.0", "package_type": "final_package", "task_id": "t1",
                 "background": "b", "dispute": "d", "business_impact": "i", "options": ["o1"]}
    check("final_package 通过", gate.validate_package(final_pkg)[0])

    # 2. 防扯皮硬计数
    card = {"title": "t1"}
    ok, _, _ = gate.check_round("t1", "lead_audit")
    check("第一轮对抗放行", ok)
    ok2, err2, _ = gate.check_round("t1", "lead_audit")
    check("第二轮对抗熔断", (not ok2) and err2 == FLOW_ERR_MELTDOWN)
    gate.counter.reset("t1"); gate.meltdown.discard("t1")
    ok, _, _ = gate.check_round("t1", "appeal")
    ok2, err2, _ = gate.check_round("t1", "appeal")
    check("第二次上诉熔断", (not ok2) and err2 == FLOW_ERR_MELTDOWN)

    # 3. 回执闸门
    gate.counter.reset("t1"); gate.meltdown.discard("t1")
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
    check("bugfix->A_exception", gate.route({"title": "单文件 bugfix"}) == "A_exception")
    check("问答->direct", gate.route({"type": "qa"}) == "direct")
    check("默认->A", gate.route({"title": "写个工具"}) == "A")

    print(f"\n共 {9 + 8 + 3 + 4} 项断言，失败 {len(fails)}")
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
