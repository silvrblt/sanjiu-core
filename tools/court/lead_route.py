#!/usr/bin/env python3
"""lead_route.py — 承办自动路由（方案 A v1.0，2026-09-07 老板拍板实施）

用途：任务进入立案庭后，承办产出按类型路由（type_route）推荐由达标模型经桥接生成——
当前窗口会话变编排/验收角色，不再默认由窗口模型直产（关闭"派任务默认窗口模型"断点）。

用法：
  lead_route.py <任务卡.json> [--out <产出回收路径>] [--force-model <model>] [--dry-run]
  lead_route.py --self-test

流程：
  1. 复用 route_task（classify_type + type_route，同源 rules/models）
  2. 决策分流：
     - manual（compound/未知扩展/空候选）→ 人工指引 exit 2
     - tool_seat（image_understand/image_gen）→ 工具席原链指引 exit 2
     - tier（ui_design）→ 模板库指引（ui-design-library/生成规范，9/5 终裁分工）exit 2
     - ranked → 候选依序桥接承办
  3. 桥接调用：model → (cli, api_id) 解析（seats 精确命中优先 → vendor 推断），
     命令 = <cli> audit <任务卡> "<诉求>" --system <承办模板> --model <api_id>
     --max-tokens N --no-compress --json；产出写 --out
  4. 降级：调用失败 → 达标池下一候选（链记录）；全败 exit 3 回退当前会话 + 提示
退出码：0 成功 / 2 需人工或指引 / 3 候选全败

依赖：PyYAML ≥5.0；同目录 route_task.py；桥接 CLI 在 PATH（hunyuan-audit/doubao-audit/
minimax-audit/glm-audit/deepseek-audit/kimi/qwen-text-audit）
副本约定：与 route_task.py 同三处同步（court 权威 / tools / 运行位 eep-tools）。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from route_task import classify_type, type_route, load_models, load_rules  # noqa: E402

# vendor → 默认桥接 CLI（seats 未精确命中时的推断；api_id 回退 = 模型名本身）
VENDOR_CLI = {
    "zhipu": "glm-audit",
    "tencent": "hunyuan-audit",
    "minimax": "minimax-audit",
    "doubao": "doubao-audit",
    "moonshot": "kimi",
    "deepseek": "deepseek-audit",
    "aliyun": "qwen-text-audit",
    "ark": "ark-image",
}
DEFAULT_MAX_TOKENS = 16384

LEAD_PROMPT = os.path.join(HERE, "lead_prompts", "lead-v1.txt")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def resolve_cli(models_yaml, model, vendor):
    """model → (cli, api_id)：seats 九席精确命中优先（取其 cli/api_id/max_tokens）；miss → vendor 推断。"""
    seats = models_yaml.get("seats") or {}
    for seat in seats.values():
        if isinstance(seat, dict) and seat.get("model") == model:
            cli = seat.get("cli")
            if cli and cli != "session":  # session 席（一审承办）不可桥接——防自环
                return cli, seat.get("api_id") or model, seat.get("max_tokens") or DEFAULT_MAX_TOKENS
    cli = VENDOR_CLI.get(vendor)
    if not cli:
        return None, None, DEFAULT_MAX_TOKENS
    return cli, model, DEFAULT_MAX_TOKENS


def build_payload(task, ttype, troute, prompt_path):
    """承办输入文件 + system 提示词组装。"""
    ask = " ".join(str(task.get(k, "")) for k in ("title", "description", "prompt")) or task.get("type", "")
    payload = {
        "task": {k: task.get(k) for k in ("title", "description", "prompt", "type", "domain", "scale") if task.get(k)},
        "task_type": ttype,
        "type_route": troute,
        "诉求": ask.strip(),
    }
    return payload, _read(prompt_path)


def call_lead(cli, api_id, payload_file, ask, system, max_tokens):
    """调桥接 CLI 承办模式。返回 (ok, stdout_text)。"""
    cmd = [cli, "audit", payload_file, ask, "--system", system,
           "--model", api_id, "--max-tokens", str(max_tokens), "--no-compress", "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return False, "[timeout] 桥接调用超时（600s）"
    if r.returncode != 0:
        return False, f"[exit {r.returncode}] {r.stderr[:300] or r.stdout[:300]}"
    out = r.stdout
    # 从 bridge JSON 提取 content（与各桥接 CLI 输出同构）
    try:
        j = json.loads(out)
        content = j.get("content", out)
    except Exception:
        content = out
    if not content or len(str(content).strip()) < 20:
        return False, "[empty] 产出为空"
    return True, str(content)


def route_and_execute(task, models_yaml, out_path=None, force_model=None, dry_run=False):
    """主流程：决策分流 + ranked 桥接承办。返回 (exit_code, result_dict)。"""
    ttype = classify_type(task)
    exclude = task.get("exclude_vendor")
    troute = type_route(ttype, models_yaml, exclude)
    decision = troute["decision"]
    chain = []
    started = time.time()

    # ---- 指引类（不自动直调）----
    if decision == "manual":
        return 2, {"decision": "manual", "task_type": ttype,
                   "note": troute.get("note", "需人工改判/指派"), "chain": chain,
                   "duration_s": round(time.time() - started, 1)}
    if decision == "tool_seat":
        seat = troute.get("tool_seat")
        rec = troute.get("recommended") or {}
        return 2, {"decision": "tool_seat", "task_type": ttype, "tool_seat": seat,
                   "note": f"工具席 {seat} 不走审级：cli={rec.get('cli')}（视觉三级验收/独立记账，原链不变）",
                   "chain": chain, "duration_s": round(time.time() - started, 1)}
    if decision == "tier":
        return 2, {"decision": "tier", "task_type": ttype,
                   "note": "ui_design 走 2026-09-05 终裁 Tier 分工与资产生成链（查 ui-design-library 索引 → "
                           "无匹配按生成规范 v1 注入 minimax 产新模板 → R10 入库 → 读图复核）；"
                           "候选 " + json.dumps([c.get("model") for c in troute.get("candidates", [])], ensure_ascii=False),
                   "chain": chain, "duration_s": round(time.time() - started, 1)}

    # ---- ranked：候选依序桥接承办 ----
    payload, system = build_payload(task, ttype, troute, LEAD_PROMPT)
    payload_file = out_path + ".task.json" if out_path else os.path.join("/tmp", f"lead-{int(time.time())}.task.json")
    with open(payload_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    candidates = troute.get("candidates", [])
    if force_model:
        cand = next((c for c in candidates if c.get("model") == force_model), None)
        candidates = [cand] if cand else candidates
    errors = []
    for c in candidates:
        model = c.get("model")
        vendor = c.get("vendor")
        cli, api_id, mt = resolve_cli(models_yaml, model, vendor)
        if not cli:
            errors.append(f"{model}: 无可用桥接 CLI（vendor={vendor}）")
            chain.append({"model": model, "ok": False, "err": "无 CLI"})
            continue
        chain.append({"model": model, "cli": cli, "api_id": api_id, "ok": True, "dry_run": True})
        if dry_run:  # 解析验证模式：首选候选即可判定决策正确性
            return 0, {"decision": "ranked", "task_type": ttype, "model": model, "cli": cli,
                       "chain": chain, "out": out_path, "dry_run": True,
                       "duration_s": round(time.time() - started, 1)}
        print(f"[lead] 承办候选: {model} via {cli} --model {api_id}", file=sys.stderr)
        ok, content = call_lead(cli, api_id, payload_file, payload["诉求"], system, mt)
        chain.append({"model": model, "cli": cli, "api_id": api_id, "ok": ok,
                      "err": None if ok else content[:200]})
        if ok:
            if out_path:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(content)
            return 0, {"decision": "ranked", "task_type": ttype, "model": model, "cli": cli,
                       "chain": chain, "out": out_path,
                       "duration_s": round(time.time() - started, 1),
                       "note": f"承办产出由 {model} 生成（类型路由推荐/降级链第 {len(chain)} 位）"}
        errors.append(f"{model}: {content[:150]}")
    # 全败
    return 3, {"decision": "ranked", "task_type": ttype, "model": None,
               "chain": chain, "errors": errors,
               "note": "候选全部失败——回退当前会话承办 + 人工核查（候选 api_id 未内置时可用 --force-model 指定）",
               "duration_s": round(time.time() - started, 1)}


def self_test():
    """决策分支单测（不真调模型；集成冒烟另行 --dry-run + 真实小任务）。"""
    models_yaml, _ = load_models()
    failures = []
    passed = 0

    def check(cond, label, msg):
        nonlocal passed
        if cond:
            passed += 1
            print(f"  ✓ {label}")
        else:
            failures.append(msg)
            print(f"  ✗ {label}")

    # manual：compound（并列/零命中）
    code, r = route_and_execute({"title": "生成数据分析看板"}, models_yaml, dry_run=True)  # 并列 → compound
    check(code == 2 and r["decision"] == "manual", "compound → manual exit 2",
          f"compound 期望 manual/2 实得 {code}/{r['decision']}")
    code, r = route_and_execute({"title": "hello world 无任何类型词"}, models_yaml, dry_run=True)  # 零命中
    check(code == 2 and r["decision"] == "manual", "零命中 → manual exit 2",
          f"零命中期望 manual/2 实得 {code}/{r['decision']}")
    # tool_seat
    code, r = route_and_execute({"title": "识别这张截图的文字"}, models_yaml, dry_run=True)
    check(code == 2 and r["decision"] == "tool_seat", "image_understand → tool_seat 指引",
          f"tool_seat 期望 exit 2 实得 {code}")
    # tier
    code, r = route_and_execute({"title": "设计一个经营看板页面"}, models_yaml, dry_run=True)
    check(code == 2 and r["decision"] == "tier", "ui_design → tier 指引（模板库）",
          f"tier 期望 exit 2 实得 {code}")
    # ranked + 候选解析（dry-run 验证 cli/api_id 解析正确）
    code, r = route_and_execute({"title": "实现用户登录接口", "description": "写后端代码"}, models_yaml, dry_run=True)
    check(code == 0 and r["decision"] == "ranked" and r["model"] == "minimax-m3",
          f"code_gen → ranked 首选 minimax-m3（dry-run）实得 {r.get('model')}",
          f"code_gen ranked 期望 minimax-m3 实得 {r}")
    chain_cli = {c["model"]: c.get("cli") for c in r.get("chain", [])}
    check(chain_cli.get("minimax-m3") == "minimax-audit", "minimax-m3 → minimax-audit 解析",
          f"CLI 解析: {chain_cli}")
    # text_gen → glm-5.3-flash（vendor 推断 glm-audit）
    code, r = route_and_execute({"title": "撰写产品宣传文案"}, models_yaml, dry_run=True)
    check(r.get("model") == "glm-5.3-flash", "text_gen → glm-5.3-flash（vendor 推断）",
          f"text_gen 期望 glm-5.3-flash 实得 {r.get('model')}")
    # data_analysis → hy3
    code, r = route_and_execute({"title": "统计本月账单并出对账报表"}, models_yaml, dry_run=True)
    check(r.get("model") == "hy3" and chain_cli.get("hy3") or r.get("chain", [{}])[0].get("cli") == "hunyuan-audit",
          "data_analysis → hy3 via hunyuan-audit", f"hy3 解析实得 {r.get('chain')}")
    # exclude_vendor 生效
    code, r = route_and_execute({"title": "实现用户登录接口", "exclude_vendor": "minimax"}, models_yaml, dry_run=True)
    check(r.get("model") == "doubao-2.1-turbo", "exclude_vendor=minimax → doubao-2.1-turbo",
          f"exclude 期望 doubao 实得 {r.get('model')}")
    # force-model
    code, r = route_and_execute({"title": "实现用户登录接口"}, models_yaml, dry_run=True, force_model="kimi-k2.7-code")
    check(r.get("model") == "kimi-k2.7-code", "force-model=kimi-k2.7-code 生效", f"force 实得 {r.get('model')}")

    total = passed + len(failures)
    print(f"lead_route 自测: {passed}/{total} 通过")
    for f in failures:
        print("  FAIL:", f)
    return 0 if not failures else 1


def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
            sys.exit(self_test())
        if len(sys.argv) < 2:
            print(__doc__)
            sys.exit(2)
        with open(sys.argv[1], encoding="utf-8") as f:
            task = json.load(f)
        out_path = None
        force_model = None
        dry_run = False
        args = sys.argv[2:]
        while args:
            a = args.pop(0)
            if a == "--out":
                out_path = args.pop(0)
            elif a == "--force-model":
                force_model = args.pop(0)
            elif a == "--dry-run":
                dry_run = True
        models_yaml = load_models()[0]
    except Exception as e:
        print(f"✗ lead_route 启动错误: {e}", file=sys.stderr)
        sys.exit(2)
    code, result = route_and_execute(task, models_yaml, out_path, force_model, dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
