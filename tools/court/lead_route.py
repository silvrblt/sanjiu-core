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
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from route_task import classify_type, type_route, load_models, load_rules, route  # noqa: E402

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
_lead_call = None  # 可注入调用函数（单测 mock 用）；None = 默认 call_lead
MIN_VALID_OUTPUT_LENGTH = 20  # 最短有效产出字符数（过滤空回复/仅标点问候等无效输出）

LEAD_PROMPT = os.path.join(HERE, "lead_prompts", "lead-v1.txt")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


PREFIX_VENDOR = [  # 模型名前缀 → vendor（force-model 非候选池推断用，A4）
    ("glm", "zhipu"), ("kimi", "moonshot"), ("hunyuan", "tencent"), ("hy3", "tencent"),
    ("hy4", "tencent"), ("doubao", "doubao"),
    ("minimax", "minimax"), ("qwen", "aliyun"), ("deepseek", "deepseek"), ("seedream", "ark")]


def _vendor_by_prefix(model):
    for prefix, vendor in PREFIX_VENDOR:
        if model.startswith(prefix):
            return vendor
    return None


def resolve_cli(models_yaml, model, vendor):
    """model → (cli, api_id)：seats 九席精确命中优先（取其 cli/api_id/max_tokens）；
    cli=session 的席位（一审承办=窗口会话）模型禁止 vendor 推断——防同模型双通道（API 再调一次
    窗口模型 = 换汤不换药）与语义自环（DS Pro 三轮问题1）。
    miss（非现役候选）→ vendor 推断，api_id = 模型名（未验证标记由调用方打）。"""
    seats = models_yaml.get("seats") or {}
    session_models = set()
    for seat in seats.values():
        if isinstance(seat, dict) and seat.get("model") == model:
            cli = seat.get("cli")
            if cli == "session":
                session_models.add(model)
                continue
            if cli:
                return cli, seat.get("api_id") or model, seat.get("max_tokens") or DEFAULT_MAX_TOKENS
    if model in session_models:  # 现役 session 席模型 → 不可桥接
        return None, None, DEFAULT_MAX_TOKENS
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
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"[cli_error] {type(e).__name__}: {e}"  # CLI 缺失/权限等 → 进降级链
    if r.returncode != 0:
        return False, f"[exit {r.returncode}] {r.stderr[:300] or r.stdout[:300]}"
    out = r.stdout
    # bridge --json 输出必须含 content 键；缺失/非 JSON = 调用失败（A3：禁止 fallback 原始 JSON 串污染产出）
    try:
        j = json.loads(out)
    except Exception as e:
        return False, f"[json_parse] 桥接输出非 JSON: {e}"
    content = j.get("content", "")
    if not isinstance(content, str) or not content.strip() or len(content.strip()) < MIN_VALID_OUTPUT_LENGTH:
        return False, "[empty] 产出为空或无效"
    return True, content


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
    if not os.path.exists(LEAD_PROMPT):  # A6：模板缺失前置校验（不进决策流程才发现）
        return 2, {"decision": "manual", "task_type": ttype,
                   "note": f"承办模板缺失：{LEAD_PROMPT}", "chain": chain,
                   "duration_s": round(time.time() - started, 1)}
    payload, system = build_payload(task, ttype, troute, LEAD_PROMPT)
    candidates = troute.get("candidates", [])
    forced = bool(force_model)
    in_pool = False
    if force_model:
        cand = next((c for c in candidates if c.get("model") == force_model), None)
        if cand:
            candidates = [cand]  # P1-3：池内命中 = 人工指定达标候选，非"非官方候选池"
            in_pool = True
        else:
            # force 不在达标池：构造单元素候选（vendor 按前缀映射推断），note 标注人工强制
            vendor = _vendor_by_prefix(force_model)
            candidates = [{"model": force_model, "vendor": vendor, "price_in": None, "price_out": None}]
            in_pool = False
    note_forced = "" if not (forced and not in_pool) else "；[人工强制指定模型（非官方候选池），结果需核验]"

    # A8：dry-run 不落盘——仅解析决策链（无副作用）；问题4：非池 force api_id 未验证标记
    if dry_run:
        for c in candidates:
            cli, api_id, mt = resolve_cli(models_yaml, c.get("model"), c.get("vendor"))
            chain.append({"model": c.get("model"), "cli": cli, "api_id": api_id, "ok": bool(cli),
                          "dry_run": True,
                          "api_id_unverified": forced and not in_pool and bool(cli)})
        first = next((c for c in chain if c.get("ok")), None)
        if not first:
            return 3, {"decision": "ranked", "task_type": ttype, "model": None, "chain": chain,
                       "errors": [f"{c.get('model')}: 无可用桥接 CLI" for c in candidates],
                       "note": "候选全部无可用 CLI（dry-run）", "duration_s": round(time.time() - started, 1)}
        return 0, {"decision": "ranked", "task_type": ttype, "model": first["model"], "cli": first["cli"],
                   "chain": chain, "out": out_path, "dry_run": True, "forced": forced, "in_pool": in_pool,
                   "duration_s": round(time.time() - started, 1)}

    # P0-1：真实调用必须指定 --out（产出落盘契约；dry-run 已在上方返回）
    if not out_path:
        return 2, {"decision": "manual", "task_type": ttype,
                   "note": "真实承办调用必须 --out <产出回收路径>（产出落盘契约）", "chain": chain,
                   "duration_s": round(time.time() - started, 1)}
    # P0-2：mkstemp 唯一 0600 payload（A5/A7），异常入兜底
    try:
        fd, payload_file = tempfile.mkstemp(prefix="lead-", suffix=".task.json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
    except OSError as e:
        return 3, {"decision": "ranked", "task_type": ttype, "model": None, "chain": chain,
                   "errors": [f"payload 临时文件创建失败: {e}"], "note": "payload 落盘失败",
                   "duration_s": round(time.time() - started, 1)}
    errors = []
    try:
        for c in candidates:
            model = c.get("model")
            vendor = c.get("vendor")
            cli, api_id, mt = resolve_cli(models_yaml, model, vendor)
            if not cli:
                errors.append(f"{model}: 无可用桥接 CLI（vendor={vendor}）")
                chain.append({"model": model, "ok": False, "err": "无 CLI"})
                continue
            print(f"[lead] 承办候选: {model} via {cli} --model {api_id}", file=sys.stderr)
            caller = _lead_call or call_lead
            ok, content = caller(cli, api_id, payload_file, payload["诉求"], system, mt)
            chain.append({"model": model, "cli": cli, "api_id": api_id, "ok": ok,
                          "err": None if ok else content[:200]})
            if ok:
                try:
                    if out_path:
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(content)
                except OSError as e:
                    # A2：写盘失败 = 该候选失败，进降级链
                    errors.append(f"{model}: 产出写盘失败 {e}")
                    chain[-1]["err"] = f"write_fail: {e}"
                    continue
                return 0, {"decision": "ranked", "task_type": ttype, "model": model, "cli": cli,
                           "chain": chain, "out": out_path, "forced": forced, "in_pool": in_pool,
                           "duration_s": round(time.time() - started, 1),
                           "note": f"承办产出由 {model} 生成（类型路由推荐/降级链第 {len(chain)} 位）{note_forced}"}
            errors.append(f"{model}: {content[:150]}")
    finally:
        try:
            os.unlink(payload_file)  # 敏感任务信息临时文件清理（全路径）
        except OSError:
            pass
    # 全败
    return 3, {"decision": "ranked", "task_type": ttype, "model": None,
               "chain": chain, "errors": errors, "forced": forced, "in_pool": in_pool,
               "note": f"候选全部失败——回退当前会话承办 + 人工核查（候选 api_id 未内置时可用 --force-model 指定）{note_forced}",
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
    c0 = r.get("chain", [{}])[0] if r.get("chain") else {}
    check(r.get("model") == "hy3" and c0.get("cli") == "hunyuan-audit",
          "data_analysis → hy3 via hunyuan-audit", f"hy3 解析实得 model={r.get('model')} chain={r.get('chain')}")
    # exclude_vendor 生效
    code, r = route_and_execute({"title": "实现用户登录接口", "exclude_vendor": "minimax"}, models_yaml, dry_run=True)
    check(r.get("model") == "doubao-2.1-turbo", "exclude_vendor=minimax → doubao-2.1-turbo",
          f"exclude 期望 doubao 实得 {r.get('model')}")
    # force-model
    code, r = route_and_execute({"title": "实现用户登录接口"}, models_yaml, dry_run=True, force_model="kimi-k2.7-code")
    check(r.get("model") == "kimi-k2.7-code", "force-model=kimi-k2.7-code 生效", f"force 实得 {r.get('model')}")
    # A4：force 非候选池 + glm 前缀 vendor 推断
    code, r = route_and_execute({"title": "实现用户登录接口"}, models_yaml, dry_run=True, force_model="glm-5.3-flash")
    c0 = (r.get("chain") or [{}])[0]
    check(r.get("model") == "glm-5.3-flash" and c0.get("cli") == "glm-audit" and c0.get("api_id") == "glm-5.3-flash",
          "force-model=glm-5.3-flash → glm-audit（A4 前缀推断）", f"A4 实得 {r}")
    # A4b：无法识别 vendor 的 force → 无 CLI 进降级
    code, r = route_and_execute({"title": "实现用户登录接口"}, models_yaml, dry_run=True, force_model="unknown-xyz")
    check(code == 3, "force-model=unknown-xyz → exit 3（vendor 不可解析）", f"A4b 实得 {code}/{r}")

    # ---- 问题1：session 席模型防自环（vendor 推断不得复活 session 席模型）----
    fake_yaml = dict(models_yaml)
    fake_yaml["seats"] = dict(models_yaml.get("seats") or {})
    fake_yaml["seats"]["l1_lead"] = {"model": "deepseek-v4-flash", "cli": "session",
                                     "api_id": "deepseek-v4-flash", "max_tokens": 16384}
    cli, api_id, mt = resolve_cli(fake_yaml, "deepseek-v4-flash", "deepseek")
    check(cli is None, "session 席模型（deepseek-v4-flash）→ 无 CLI（防自环）",
          f"session 防自环失败: cli={cli}")

    # ---- P1-4：异常/真实路径单测（mock _lead_call 注入，不真调外部模型）----
    print("== 异常路径（mock）==")
    global _lead_call
    saved = _lead_call

    # ① 无 out_path 真实调用 → exit 2（P0-1）
    code, r = route_and_execute({"title": "实现用户登录接口"}, models_yaml, out_path=None)
    check(code == 2, "真实调用无 --out → exit 2（P0-1）", f"P0-1 实得 {code}")

    # ② mock 全失败 → 降级链走完 → exit 3
    _lead_call = lambda cli, api_id, pf, ask, sys_, mt: (False, "[mock] 网关失败")
    code, r = route_and_execute({"title": "实现用户登录接口"}, models_yaml, out_path="/tmp/lead-mock-out.md")
    check(code == 3 and len(r.get("chain", [])) >= 3, "mock 全败 → exit 3 + 降级链记录",
          f"mock 全败实得 {code} chain={len(r.get('chain', []))}")
    check(not os.path.exists("/tmp/lead-mock-out.md"), "全败不产生产出文件", "全败残留产出文件")

    # ③ mock 成功 → exit 0 + 产出落盘
    _lead_call = lambda cli, api_id, pf, ask, sys_, mt: (True, "# 承办产出 mock\n完整内容")
    code, r = route_and_execute({"title": "实现用户登录接口"}, models_yaml, out_path="/tmp/lead-mock-ok.md")
    check(code == 0 and os.path.exists("/tmp/lead-mock-ok.md") and "承办产出 mock" in open("/tmp/lead-mock-ok.md").read(),
          "mock 成功 → exit 0 + 产出落盘", f"mock 成功实得 {code}")
    os.unlink("/tmp/lead-mock-ok.md")

    # ④ LEAD_PROMPT 缺失 → exit 2（A6）
    saved_prompt = globals()["LEAD_PROMPT"]
    globals()["LEAD_PROMPT"] = "/nonexistent/lead-v1.txt"
    code, r = route_and_execute({"title": "实现用户登录接口"}, models_yaml, out_path="/tmp/x.md", dry_run=False)
    globals()["LEAD_PROMPT"] = saved_prompt
    check(code == 2, "承办模板缺失 → exit 2（A6）", f"A6 实得 {code}")

    _lead_call = saved
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
            if a in ("--out", "--force-model") and not args:
                print(f"✗ 参数错误：{a} 需指定值", file=sys.stderr)
                sys.exit(2)
            if a == "--out":
                out_path = args.pop(0)
            elif a == "--force-model":
                force_model = args.pop(0)
            elif a == "--dry-run":
                dry_run = True
            else:
                print(f"✗ 未知参数：{a}", file=sys.stderr)
                sys.exit(2)
        rules = load_rules()
        models_yaml = load_models()[0]
    except Exception as e:
        print(f"✗ lead_route 启动错误: {e}", file=sys.stderr)
        sys.exit(2)
    try:
        code, result = route_and_execute(task, models_yaml, out_path, force_model, dry_run)
    except Exception as e:  # P2-6：统一兜底，退出码语义 0/2/3 不破坏
        result = {"decision": "error", "task_type": "?", "note": f"未预期异常: {type(e).__name__}: {e}"}
        code = 3
    # combo 注入：审级路由结果随承办路由一并输出（一次调用 = 立案全量，消除双跑）
    try:
        combo, combo_reason, _ = route(task, rules)
        result["combo"] = combo
        result["combo_reason"] = combo_reason
    except Exception as e:
        result["combo"] = "error"
        result["combo_reason"] = str(e)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
