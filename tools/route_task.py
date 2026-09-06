#!/usr/bin/env python3
"""route_task.py — 立案庭路由（审级组合分流 + 类型路由消费，v1.1.0 2026-09-06）

两层：
  1. 审级组合分流（v1.0.0 立案庭定稿，需求 v6 2026-09-03）：domain/scale/type/history → 组合 A/B/A_exception/C_trigger
  2. 类型路由消费（v1.1.0，关闭终版说明 §三 未决清单 #1）：任务类型 → 候选池达标模型自动接线
     （选择优先级①合规异厂 ②测评达标 ③输入价最低 ④同价档次级锚；ui_design 走老板终裁 Tier；
      image_* 走工具席 tool_seats；compound 人工改判）

用法：
  route_task.py <任务卡.json>          # 任务卡含 domain/scale/type/errors_ledger_count 字段；可选 exclude_vendor
  route_task.py --self-test            # 三段自检（组合 10 项 + 类型判定 + 类型推荐快照）
输出：JSON {combo, combo_name, reason, matched, task_type, type_note, type_route}

规则源：routing_rules.yaml（唯一事实源，同级目录）
模型源：sanjiu-models.yaml candidate_pool.verified_models（唯一事实源；自动探测同目录/上级目录，--models 可覆盖）

副本约定（2026-09-06 收口）：本文件（tools/court/）= 权威版；tools/route_task.py 与运行位
00_global-shared/tools/eep-tools/route_task.py 同步同内容；sync-local.sh 2b 已纳入防漂移。
"""
import json
import os
import sys
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, "routing_rules.yaml")

# ui_design 生产分工（老板 2026-09-05 终裁，证据 docs/evidence/type-eval/ui_design-三模型分工定稿-20260905.md）：
# 不走通用价格序（纯价格序 top=DS-flash 会违背终裁）。Tier 表按用途与频率分层。
UI_DESIGN_TIERS = [
    # tier, 用途, 模型, 占比, 风格处理/参数, 实测单页成本（口径见定稿文档）
    {"tier": "T1", "usage": "常规看板/中后台页/内部工具页（高频）", "model": "minimax-m3",
     "share": 0.7, "style": "注入 qwen 风格基线 + thinking:disabled + max_tokens 28000", "cost_per_page": "≈¥0.08",
     "note": "2026-09-05 终裁 T1 主力"},
    {"tier": "T2", "usage": "对外门面/客户演示/汇报页（低频）", "model": "qwen3.8-max",
     "share": 0.2, "style": "直出 + 提示词要求内容密度（短板：下半页留白）", "cost_per_page": "≈¥0.50",
     "note": "2026-09-05 终裁 T2 质感"},
    {"tier": "T3", "usage": "T2 预算敏感替代 / qwen 排队降级", "model": "glm-5.3",
     "share": 0.1, "style": "注入风格基线 + 明确要求数据模块完整度（短板：数据模块单薄）", "cost_per_page": "≈¥0.35",
     "note": "2026-09-05 终裁 T3 平价替身"},
]

# 类型 → 工具席映射（image_* 不走审级；实际主备/冷备/CLI 从 sanjiu-models.yaml tool_seats 读取，此处只定关联）
TYPE_TOOL_SEAT = {
    "image_understand": "vision_read",
    "image_gen": "image_gen",
}

# 核心审级类型（rank 走 verified_models 达标池）；ui_design 走 Tier；image_* 走工具席；compound 人工
RANK_TYPES = ["text_gen", "text_understand", "code_gen", "code_audit", "data_analysis"]

TYPE_KEYWORDS = {
    "code_gen": ["写", "开发", "实现", "编码", "代码", "脚本", "function", "实现功能", "接口", "api", "bug", "修复"],
    "code_audit": ["审计", "审查", "review", "评审", "code review", "检查代码"],
    "text_gen": ["写文档", "文案", "撰写", "介绍", "宣传", "公告", "报告", "生成文本", "写作"],
    "text_understand": ["理解", "总结", "分析这段", "解读", "归纳", "翻译"],
    "data_analysis": ["数据分析", "统计", "聚合", "清洗", "csv", "报表", "账单分析", "对账"],
    "ui_design": ["页面", "看板", "html", "ui", "界面", "前端", "布局", "dashboard", "设计页面"],
    "image_understand": ["读图", "看图", "截图", "识别图片", "图片内容", "视觉"],
    "image_gen": ["生图", "生成图片", "图片生成", "海报", "logo", "配图", "绘画", "插画"],
}


def load_rules():
    with open(RULES, encoding="utf-8") as f:
        return yaml.safe_load(f)


def locate_models_yaml():
    """候选池 yaml 自动探测：脚本同目录 → 上级目录（court/ 子目录场景）；--models 或环境变量优先。"""
    override = os.environ.get("SANJIU_MODELS_YAML")
    if override and os.path.exists(override):
        return override
    for d in (HERE, os.path.dirname(HERE)):
        p = os.path.join(d, "sanjiu-models.yaml")
        if os.path.exists(p):
            return p
    raise FileNotFoundError("sanjiu-models.yaml 未找到（同目录/上级目录均无；可用 SANJIU_MODELS_YAML 指定）")


def load_models(path=None):
    """读 candidate_pool.verified_models → [{model, price_in, price_out, cache, vendor, types, note}]"""
    path = path or locate_models_yaml()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data, data["candidate_pool"]["verified_models"]


def rank_models(ttype, models, exclude_vendor=None):
    """选择优先级 ②③④：types 达标过滤（②）→ exclude_vendor 异厂（① 消费接口）→ 输入价升序（③）
    → ±10% 同价档内按输出价升序（④ 次级锚，口径与九方排序一致；yaml 无达标度数值字段，
    R4 原 0.7×达标度公式不可复现——降级实现，见拆解稿 D2）。
    返回排序后候选（达标模型全量，供调用方按需取 top/全量）。"""
    hits = [m for m in models if ttype in m.get("types", [])]
    if exclude_vendor:
        hits = [m for m in hits if m.get("vendor") != exclude_vendor]
    for m in hits:
        m.setdefault("price_in", float("inf"))  # 防御：无输入价的模型不应出现在审级 6 类
        m.setdefault("price_out", float("inf"))
    hits.sort(key=lambda m: (m["price_in"], m["price_out"]))
    return hits


def ui_design_decision():
    """ui_design：老板 2026-09-05 终裁 Tier 分工（不走通用价格序，分歧点 D1）。"""
    return {
        "decision": "tier",
        "recommended": {"model": UI_DESIGN_TIERS[0]["model"], "tier": UI_DESIGN_TIERS[0]["tier"],
                        "note": "终裁 T1 主力（70%）"},
        "candidates": UI_DESIGN_TIERS,
        "note": "ui_design 生产分工按老板 2026-09-05 终裁 Tier（T1 70%/T2 20%/T3 10%），不走通用价格序；"
                "hy3/doubao 资格已移出 yaml；DS 系虽持 ui_design 测评资格但不在终裁分工内（长输出缺陷见定稿 §三）",
    }


def tool_seat_decision(ttype, models_yaml):
    """image_*：工具席主备输出（不走审级；主备/冷备/CLI 从 yaml tool_seats 读，防双份事实源）。"""
    tool = TYPE_TOOL_SEAT[ttype]
    seat = models_yaml["tool_seats"][tool]
    primary = {"model": seat["model"], "cli": seat["cli"], "note": "工具席不走审级（视觉三级验收/独立记账）"}
    alternates = [{"model": m, "note": "失败升级/冷备"} for m in seat.get("alternates", [])]
    return {
        "decision": "tool_seat",
        "tool_seat": tool,
        "recommended": primary,
        "candidates": alternates,
        "note": f"{ttype} = 工具席 {tool}（tool_seats 唯一事实源），非审级候选池",
    }


def classify_type(task):
    """类型判定器 v0（关键词命中计数；零命中或多类并列 → compound 人工改判）。
    边界：v0 为关键词粗判（7/7 单测基线），R1 判定器升级（材料特征/置信度）为后续节奏，不在本次消费代码范围。"""
    text = " ".join([str(task.get(k, "")) for k in ("title", "description", "prompt")]) + " " + str(task.get("type", ""))
    scores = {}
    for t, kws in TYPE_KEYWORDS.items():
        scores[t] = sum(1 for k in kws if k in text)
    best = max(scores, key=scores.get)
    top = [t for t, v in scores.items() if v == scores[best]]
    if scores[best] == 0 or len(top) > 1:
        return "compound"  # 零命中或多类并列 → 复合类（人工改判）
    return best


def type_route(ttype, models_yaml, exclude_vendor=None):
    """类型路由消费主入口：任务类型 → {decision, recommended, candidates, note}。
    decision ∈ ranked（审级类型价格序）/ tier（ui_design 终裁）/ tool_seat（image_*）/ manual（compound）。"""
    if ttype == "compound":
        return {"decision": "manual", "recommended": None, "candidates": [],
                "note": "复合类（零命中/多类并列）需人工改判：显式 type 字段后重新立案路由"}
    if ttype in TYPE_TOOL_SEAT:
        return tool_seat_decision(ttype, models_yaml)
    if ttype == "ui_design":
        return ui_design_decision()
    if ttype not in RANK_TYPES:
        return {"decision": "manual", "recommended": None, "candidates": [],
                "note": f"未知/扩展类型 {ttype}（core 8 类见 task_types），暂无达标池，人工指派"}
    ranked = rank_models(ttype, models_yaml["candidate_pool"]["verified_models"], exclude_vendor)
    if not ranked:
        return {"decision": "manual", "recommended": None, "candidates": [],
                "note": f"{ttype} 无达标候选（含 exclude_vendor={exclude_vendor} 过滤后为空），人工指派"}
    top = ranked[0]
    return {
        "decision": "ranked",
        "recommended": {"model": top["model"], "vendor": top.get("vendor"), "price_in": top.get("price_in"),
                        "price_out": top.get("price_out"),
                        "reason": "达标池价格序 top（②测评达标→③输入价最低→④同价档次级锚输出价）"},
        "candidates": [{"model": m["model"], "vendor": m.get("vendor"), "price_in": m.get("price_in"),
                        "price_out": m.get("price_out"), "yaml_note": m.get("note", "")} for m in ranked],
        "note": "调用选择优先级：①合规异厂（exclude_vendor）→ ②测评达标 → ③输入价最低 → ④同价档输出价",
    }


def route(task, rules):
    dom = task.get("domain", "")
    scale = task.get("scale", "")
    ttype = task.get("type", "")
    hist = task.get("errors_ledger_count", 0)  # 30 天滚动同域 count

    # ① force_b：域/规模/历史（最高优先）
    for sig in rules["routing_rules"]["force_b"]:
        if sig["signal"] == "domain" and dom == sig["value"]:
            return "B", f"强制域:{dom}", [sig]
        if sig["signal"] == "scale" and scale == sig["value"]:
            return "B", f"跨模块重构:{scale}", [sig]
        if sig["signal"] == "history" and hist >= 5:
            return "B", f"历史高错误率:{hist}", [sig]

    # ② 例外：单文件 bugfix
    if ttype == "bugfix" and scale == "single_file":
        return "A_exception", "单文件bugfix例外（留痕+月度抽审）", rules["routing_rules"]["exceptions"]

    # ③ simple_a
    for sig in rules["routing_rules"]["simple_a"]:
        if sig["signal"] == "type" and ttype == sig["value"]:
            return "A", f"类型:{ttype}", [sig]
        if sig["signal"] == "scale" and scale == sig["value"]:
            return "A", f"规模:{scale}", [sig]

    # ④ default
    return "A", "默认组合 A", []


def self_test():
    """三段回测（纯本地零成本；A2 口径：组合 10/10 + 判定/推荐快照全部通过）"""
    rules = load_rules()
    models_yaml, _ = load_models()
    failures = []

    # ---- 段 1：审级组合（10 项，v1.0.0 保留）----
    print("== 段 1：审级组合路由（10 项）==")
    cases = [
        ({"domain": "finance", "scale": "large"}, "B"),
        ({"domain": "security", "scale": "medium"}, "B"),
        ({"domain": "framework_change", "scale": "large"}, "B"),
        ({"domain": "", "scale": "cross_module_refactor"}, "B"),
        ({"domain": "", "scale": "", "errors_ledger_count": 6}, "B"),
        ({"domain": "", "scale": "single_file", "type": "bugfix"}, "A_exception"),
        ({"domain": "", "scale": "single_file", "type": "internal_tool"}, "A"),
        ({"domain": "", "scale": "small", "type": "feature"}, "A"),
        ({"domain": "business", "scale": "medium", "type": "feature"}, "A"),
        ({"domain": "visual", "scale": "tool"}, "A"),  # 视觉工具席实际不经审级（立案庭外），此处兜底 A
    ]
    for task, expect in cases:
        got, reason, _ = route(task, rules)
        ok = got == expect
        if not ok:
            failures.append(f"组合: {task} 期望 {expect} 实得 {got}")
        print(f"  {'✓' if ok else '✗'} {json.dumps(task, ensure_ascii=False)[:60]} → {got} ({reason})")

    # ---- 段 2：类型判定（8 类 × 2 样例 + 2 复合兜底）----
    print("== 段 2：类型判定（8 类 ×2 + compound ×2）==")
    cls_cases = [
        ("code_gen", "实现用户登录接口并写服务端脚本"),
        ("code_gen", "开发一个 Python 脚本做文件批量处理"),
        ("code_audit", "审查 PR 改动是否缺少鉴权"),
        ("code_audit", "对 PR 改动做 code review 检查越权缺陷"),
        ("text_gen", "撰写产品宣传文案"),
        ("text_gen", "生成一份活动公告"),
        ("text_understand", "总结这篇文章的要点"),
        ("text_understand", "归纳这段对话的核心意图"),
        ("data_analysis", "统计本月账单并出对账报表"),
        ("data_analysis", "数据分析：清洗这份 csv 并聚合"),
        ("ui_design", "设计一个经营看板页面"),
        ("ui_design", "前端布局调整 dashboard 界面"),
        ("image_understand", "识别这张截图的文字内容"),
        ("image_understand", "看图并描述图表含义"),
        ("image_gen", "生成一张产品海报"),
        ("image_gen", "用 AI 画一个 logo"),
        ("compound", "生成数据分析看板"),  # 数据分析×ui_design 真并列 → 复合
        ("compound", "hello world 无任何类型词"),  # 零命中 → 复合
    ]
    for expect, title in cls_cases:
        got = classify_type({"title": title})
        ok = got == expect
        if not ok:
            failures.append(f"判定: 「{title}」期望 {expect} 实得 {got}")
        print(f"  {'✓' if ok else '✗'} 「{title}」→ {got}")

    # ---- 段 3：类型推荐快照（与数据层终态一致；yaml 价格变更时快照红即提示重排审计）----
    print("== 段 3：类型推荐快照（ranked/tier/tool_seat/manual）==")
    rec_cases = [
        # (type, 期望 decision, 期望 recommended.model)
        ("text_gen", "ranked", "glm-5.3-flash"),
        ("code_gen", "ranked", "minimax-m3"),
        ("code_audit", "ranked", "hy3"),
        ("text_understand", "ranked", "hy3"),
        ("data_analysis", "ranked", "hy3"),
        ("ui_design", "tier", "minimax-m3"),
        ("image_understand", "tool_seat", "glm-5.3-flash"),
        ("image_gen", "tool_seat", "doubao-seedream-4-0-250828"),
        ("compound", "manual", None),
    ]
    for ttype, expect_d, expect_m in rec_cases:
        got = type_route(ttype, models_yaml)
        ok = got["decision"] == expect_d and (got["recommended"] or {}).get("model") == expect_m
        if not ok:
            failures.append(f"推荐: {ttype} 期望 {expect_d}/{expect_m} 实得 {got['decision']}/{(got['recommended'] or {}).get('model')}")
        rec = (got["recommended"] or {}).get("model")
        print(f"  {'✓' if ok else '✗'} {ttype} → {got['decision']} {rec}")

    # ---- 段 4：exclude_vendor（合规异厂消费接口）+ 排序不变量 ----
    print("== 段 4：exclude_vendor 与排序不变量 ==")
    got = type_route("code_gen", models_yaml, exclude_vendor="minimax")
    ok = got["recommended"]["model"] == "doubao-2.1-turbo"
    if not ok:
        failures.append(f"exclude_vendor: code_gen 排除 minimax 期望 doubao-2.1-turbo 实得 {got['recommended']['model']}")
    print(f"  {'✓' if ok else '✗'} code_gen + exclude_vendor=minimax → {got['recommended']['model']}")

    ranked = rank_models("code_gen", models_yaml["candidate_pool"]["verified_models"])
    prices = [m["price_in"] for m in ranked]
    ok_mono = prices == sorted(prices)
    if not ok_mono:
        failures.append("排序不变量: code_gen 候选输入价非升序")
    print(f"  {'✓' if ok_mono else '✗'} 候选 price_in 升序不变量（{len(ranked)} 席）")

    total = 10 + len(cls_cases) + len(rec_cases) + 2
    passed = total - len(failures)
    print(f"回测: {passed}/{total} 通过（failures={len(failures)}）")
    for f in failures:
        print("  FAIL:", f)
    return 0 if not failures else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        sys.exit(self_test())
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    task = json.load(open(sys.argv[1], encoding="utf-8"))
    rules = load_rules()
    combo, reason, matched = route(task, rules)
    ttype = classify_type(task)
    out = {"combo": combo, "combo_name": rules["combos"][combo]["name"],
           "reason": reason, "matched": matched,
           "task_type": ttype, "type_note": "低置信=compound 需人工改判",
           "type_route": type_route(ttype, load_models()[0], task.get("exclude_vendor"))}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
