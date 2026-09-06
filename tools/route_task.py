#!/usr/bin/env python3
"""route_task.py — 立案庭路由（审级组合分流 + 类型路由消费，v1.2.0 2026-09-06 二审共识修正版）

两层：
  1. 审级组合分流（v1.0.0 立案庭定稿，需求 v6 2026-09-03）：domain/scale/type/history → 组合 A/B/A_exception/C_trigger
  2. 类型路由消费（v1.1.0 起，关闭终版说明 §三 未决清单 #1）：任务类型 → 候选池达标模型自动接线
     （选择优先级①合规异厂 ②测评达标 ③输入价最低 ④同价档（±10%）输出价次级锚；ui_design 走老板终裁 Tier；
      image_* 走工具席 tool_seats；compound 人工改判）
  3. v1.2.0 审计修正（组合 B：doubao 二审承办 P1-P12 + DS Pro 二审对抗 A1-A5，2026-09-06）：
     P1 规则文件自动探测 / P2 ±10% 同价档实现 / P3 ui_design Tier 结构化到 sanjiu-models.yaml /
     P5 副本同步与一致性校验 / P7 边界用例 / P9 友好报错 / P10 cost 数值化 / P12 依赖声明 /
     A1 classify 不再拼入审级 type 字段（bugfix 子串误命中） / A2 history 阈值从 rules 读 /
     A3 快照断言基线标注 / A4 rank 不原地改模型字典 / A5 工具席配置缺失防御
     （P4 image_gen 标识统一走 yaml 侧；P6/P8/P11 判定器升级、关键词配置化 = 后续 R1 节奏，见拆解稿边界）

依赖：PyYAML ≥ 5.0（pip install pyyaml）；其余仅标准库。

用法：
  route_task.py <任务卡.json>          # 任务卡含 domain/scale/type/errors_ledger_count 字段；可选 exclude_vendor
  route_task.py --self-test            # 六段自检（组合/判定/推荐快照/异厂/边界/副本一致性）
输出：JSON {combo, combo_name, reason, matched, task_type, type_note, type_route}

规则源：routing_rules.yaml（唯一事实源；自动探测：同目录 → 上级目录 → 同目录/court → SANJIU_ROUTING_YAML）
模型源：sanjiu-models.yaml（唯一事实源；自动探测：同目录 → 上级目录 → SANJIU_MODELS_YAML）

副本约定（2026-09-06 收口）：本文件（tools/court/）= 权威版；tools/route_task.py 与运行位
00_global-shared/tools/eep-tools/route_task.py 为同步副本（self_test 段 6 校验一致性；
sync-local.sh 2b 已纳入 route_task.py/routing_rules.yaml 防漂移）。
"""
import json
import os
import sys
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def locate_rules():
    """routing_rules.yaml 探测：SANJIU_ROUTING_YAML → 同目录 → 上级目录 → 同目录/court。"""
    override = os.environ.get("SANJIU_ROUTING_YAML")
    if override and os.path.exists(override):
        return override
    for d in (HERE, os.path.dirname(HERE), os.path.join(HERE, "court")):
        p = os.path.join(d, "routing_rules.yaml")
        if os.path.exists(p):
            return p
    raise FileNotFoundError("routing_rules.yaml 未找到（同目录/上级目录/同目录court 均无；可用 SANJIU_ROUTING_YAML 指定）")


def locate_models_yaml():
    """sanjiu-models.yaml 探测：SANJIU_MODELS_YAML → 同目录 → 上级目录（court/ 子目录场景）。"""
    override = os.environ.get("SANJIU_MODELS_YAML")
    if override and os.path.exists(override):
        return override
    for d in (HERE, os.path.dirname(HERE)):
        p = os.path.join(d, "sanjiu-models.yaml")
        if os.path.exists(p):
            return p
    raise FileNotFoundError("sanjiu-models.yaml 未找到（同目录/上级目录均无；可用 SANJIU_MODELS_YAML 指定）")


def load_rules():
    with open(locate_rules(), encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_models(path=None):
    """读 sanjiu-models.yaml 全量 → (data, verified_models)"""
    path = path or locate_models_yaml()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data, data["candidate_pool"]["verified_models"]


# ui_design Tier fallback（yaml candidate_pool.ui_design_tiers 为事实源；此处仅兜底，缺节时启用并注记）。
# 老板 2026-09-05 终裁，证据 docs/evidence/type-eval/ui_design-三模型分工定稿-20260905.md。
UI_DESIGN_TIERS_FALLBACK = [
    {"tier": "T1", "usage": "常规看板/中后台页/内部工具页（高频）", "model": "minimax-m3",
     "share": 0.7, "style": "注入 qwen 风格基线 + thinking:disabled + max_tokens 28000",
     "cost_per_page_yuan": 0.08, "note": "终裁 T1 主力（70%）"},
    {"tier": "T2", "usage": "对外门面/客户演示/汇报页（低频）", "model": "qwen3.8-max",
     "share": 0.2, "style": "直出 + 提示词要求内容密度（短板：下半页留白）",
     "cost_per_page_yuan": 0.5, "note": "终裁 T2 质感（20%）"},
    {"tier": "T3", "usage": "T2 预算敏感替代 / qwen 排队降级", "model": "glm-5.3",
     "share": 0.1, "style": "注入风格基线 + 明确要求数据模块完整度（短板：数据模块单薄）",
     "cost_per_page_yuan": 0.35, "note": "终裁 T3 平价替身（10%）"},
]

# 类型 → 工具席映射（image_* 不走审级；主备/冷备/CLI 从 sanjiu-models.yaml tool_seats 读取）
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


def classify_type(task):
    """类型判定器 v0（关键词命中计数；零命中或多类并列 → compound 人工改判）。
    A1 修正：输入仅 title/description/prompt，不拼入审级路由 type 字段——"bugfix" 含子串 "bug"
    会误命中 code_gen 关键词（bugfix 任务全部被误判 code_gen 的缺陷，v1.2.0 修复）。
    边界：v0 为关键词粗判，R1 判定器升级（材料特征/置信度/会话锁定/关键词配置化）为后续节奏。"""
    text = " ".join([str(task.get(k, "")) for k in ("title", "description", "prompt")])
    scores = {}
    for t, kws in TYPE_KEYWORDS.items():
        scores[t] = sum(1 for k in kws if k in text)
    best = max(scores, key=scores.get)
    top = [t for t, v in scores.items() if v == scores[best]]
    if scores[best] == 0 or len(top) > 1:
        return "compound"  # 零命中或多类并列 → 复合类（人工改判）
    return best


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else float("inf")


def rank_models(ttype, models, exclude_vendor=None):
    """选择优先级 ②③④：types 达标过滤（②）→ exclude_vendor 异厂（① 消费接口）→ 输入价升序（③）
    → ±10% 同价档内按输出价升序（④ 次级锚，P2 v1.2.0 实现；yaml 无达标度数值字段，R4 原
    0.7×达标度公式不可复现——降级实现见拆解稿 D2，月度补测可在 verified_models 补达标度字段后恢复）。
    同价档规则：以档首（最小）price_in 为锚，与锚差 ≤10% 归同档（不链式传播），档内按 price_out 升序。
    A4 修正：候选复制后排序，不原地修改 yaml 解析对象。返回排序后候选全量。"""
    hits = [dict(m) for m in models if ttype in (m.get("types") or [])]
    if exclude_vendor:
        hits = [m for m in hits if m.get("vendor") != exclude_vendor]
    hits.sort(key=lambda m: _num(m.get("price_in")))
    result = []
    i = 0
    while i < len(hits):
        j = i
        anchor = _num(hits[i].get("price_in"))
        while (j + 1 < len(hits) and anchor != float("inf")
               and _num(hits[j + 1].get("price_in")) != float("inf")
               and (_num(hits[j + 1].get("price_in")) - anchor) / anchor <= 0.10):
            j += 1
        result.extend(sorted(hits[i:j + 1], key=lambda m: _num(m.get("price_out"))))
        i = j + 1
    return result


def ui_design_tiers(models_yaml):
    """yaml candidate_pool.ui_design_tiers 为事实源；缺节/结构异常 → 内置 fallback（P3 v1.2.0）。"""
    tiers = (models_yaml.get("candidate_pool") or {}).get("ui_design_tiers")
    if isinstance(tiers, list) and tiers and all(isinstance(t, dict) and "model" in t for t in tiers):
        return tiers, False
    return UI_DESIGN_TIERS_FALLBACK, True


def ui_design_decision(models_yaml):
    """ui_design：老板 2026-09-05 终裁 Tier 分工（不走通用价格序，分歧点 D1 二审裁决采纳）。"""
    tiers, fell_back = ui_design_tiers(models_yaml)
    return {
        "decision": "tier",
        "recommended": {"model": tiers[0]["model"], "tier": tiers[0]["tier"], "note": "终裁 T1 主力"},
        "candidates": tiers,
        "note": "ui_design 生产分工按老板 2026-09-05 终裁 Tier（T1 70%/T2 20%/T3 10%，yaml candidate_pool.ui_design_tiers 事实源），"
                "不走通用价格序；hy3/doubao 资格已移出 yaml；DS 系虽持 ui_design 测评资格但不在终裁分工内"
                + ("；[fallback] yaml ui_design_tiers 缺失，使用内置常量" if fell_back else ""),
    }


def tool_seat_decision(ttype, models_yaml):
    """image_*：工具席主备输出（不走审级；主备/冷备/CLI 从 yaml tool_seats 读）。
    A5 修正：tool_seats 缺失/结构异常 → manual + 明确错误信息，不裸 KeyError。"""
    tool = TYPE_TOOL_SEAT[ttype]
    seat = (models_yaml.get("tool_seats") or {}).get(tool)
    if not isinstance(seat, dict) or not seat.get("model"):
        return {"decision": "manual", "recommended": None, "candidates": [],
                "note": f"工具席配置缺失/异常（tool_seats.{tool}），人工指派"}
    alternates = seat.get("alternates") if isinstance(seat.get("alternates"), list) else []
    return {
        "decision": "tool_seat",
        "tool_seat": tool,
        "recommended": {"model": seat["model"], "cli": seat.get("cli"), "note": "工具席不走审级（视觉三级验收/独立记账）"},
        "candidates": [{"model": m, "note": "失败升级/冷备"} for m in alternates],
        "note": f"{ttype} = 工具席 {tool}（tool_seats 唯一事实源），非审级候选池",
    }


def type_route(ttype, models_yaml, exclude_vendor=None):
    """类型路由消费主入口：任务类型 → {decision, recommended, candidates, note}。
    decision ∈ ranked（审级类型价格序）/ tier（ui_design 终裁）/ tool_seat（image_*）/ manual（compound/未知/空候选）。"""
    if ttype == "compound":
        return {"decision": "manual", "recommended": None, "candidates": [],
                "note": "复合类（零命中/多类并列）需人工改判：显式 type 字段后重新立案路由"}
    if ttype in TYPE_TOOL_SEAT:
        return tool_seat_decision(ttype, models_yaml)
    if ttype == "ui_design":
        return ui_design_decision(models_yaml)
    if ttype not in RANK_TYPES:
        return {"decision": "manual", "recommended": None, "candidates": [],
                "note": f"未知/扩展类型 {ttype}（core 8 类见 task_types，扩展类待月度补测），暂无达标池，人工指派"}
    ranked = rank_models(ttype, models_yaml["candidate_pool"]["verified_models"], exclude_vendor)
    if not ranked:
        return {"decision": "manual", "recommended": None, "candidates": [],
                "note": f"{ttype} 无达标候选（含 exclude_vendor={exclude_vendor} 过滤后为空），人工指派"}
    top = ranked[0]
    return {
        "decision": "ranked",
        "recommended": {"model": top["model"], "vendor": top.get("vendor"), "price_in": top.get("price_in"),
                        "price_out": top.get("price_out"),
                        "reason": "达标池价格序 top（②测评达标→③输入价最低→④±10%同价档内输出价低者）"},
        "candidates": [{"model": m["model"], "vendor": m.get("vendor"), "price_in": m.get("price_in"),
                        "price_out": m.get("price_out"), "yaml_note": m.get("note", "")} for m in ranked],
        "note": "调用选择优先级：①合规异厂（exclude_vendor）→ ②测评达标 → ③输入价最低 → ④±10%同价档内输出价低者",
    }


def route(task, rules):
    dom = task.get("domain", "")
    scale = task.get("scale", "")
    ttype = task.get("type", "")
    hist = task.get("errors_ledger_count", 0)  # 30 天滚动同域 count

    # ① force_b：域/规模/历史（最高优先；history 阈值从 rules 读——A2 v1.2.0，routing_rules.yaml 结构化）
    for sig in rules["routing_rules"]["force_b"]:
        if sig["signal"] == "domain" and dom == sig["value"]:
            return "B", f"强制域:{dom}", [sig]
        if sig["signal"] == "scale" and scale == sig["value"]:
            return "B", f"跨模块重构:{scale}", [sig]
        if sig["signal"] == "history" and hist >= sig.get("threshold", 5):
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


def _md5(path):
    import hashlib
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def self_test():
    """六段回测（纯本地零成本）：组合 10 / 判定 20 / 推荐快照 9 / 异厂+不变量 2 / 边界 5 / 副本一致性。"""
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

    # ---- 段 2：类型判定（8 类 ×2 + compound ×2 + A1 bugfix 回归 ×2）----
    print("== 段 2：类型判定（8 类 ×2 + compound ×2 + bugfix 回归 ×2）==")
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
        # A1 回归：bugfix 任务不再因审级 type 字段的 "bug" 子串被强制加码 code_gen
        ("code_gen", {"type": "bugfix", "title": "修复登录接口 token 校验 bug"}),   # 标题含接口/bug → code_gen 合理
        ("compound", {"type": "bugfix", "title": "修正周报模板的错别字"}),           # 纯文档修复无代码词 → 不再误判 code_gen
    ]
    for expect, title in cls_cases:
        task = title if isinstance(title, dict) else {"title": title}
        got = classify_type(task)
        ok = got == expect
        if not ok:
            failures.append(f"判定: 「{task}」期望 {expect} 实得 {got}")
        print(f"  {'✓' if ok else '✗'} 「{(task.get('title') or '')[:36]}」→ {got}")

    # ---- 段 3：类型推荐快照（价格基线 2026-09-06；T3 周五价格 watch 重排时同步更新本节，A3 标注）----
    print("== 段 3：类型推荐快照（ranked/tier/tool_seat/manual；价格基线 2026-09-06）==")
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
    # P2 同价档（6.0 doubao-seed-2.1-pro 与 6.5 kimi-k2.7-code 差 8.3% ≤10% 同档 → 档内按输出价 27<30 → kimi 先）
    expect_order = ["minimax-m3", "doubao-2.1-turbo", "kimi-k2.7-code", "doubao-seed-2.1-pro", "kimi-k2.7-code-highspeed"]
    got_order = [m["model"] for m in ranked]
    ok = got_order == expect_order
    if not ok:
        failures.append(f"同价档: code_gen 候选序 期望 {expect_order} 实得 {got_order}")
    print(f"  {'✓' if ok else '✗'} code_gen 候选序（±10% 同价档内输出价升序）→ {got_order}")

    # ---- 段 5：边界用例（P7/A5 补充）----
    print("== 段 5：边界（未知扩展类/空候选/Tier 完整性/工具席缺失防御）==")
    r1 = type_route("code_debug", models_yaml)  # 扩展类未入 RANK_TYPES
    ok = r1["decision"] == "manual"
    if not ok:
        failures.append(f"扩展类型 code_debug 期望 manual 实得 {r1['decision']}")
    print(f"  {'✓' if ok else '✗'} 扩展类型 code_debug → manual")

    stripped = dict(models_yaml)
    stripped["candidate_pool"] = dict(models_yaml["candidate_pool"])
    stripped["candidate_pool"]["verified_models"] = [
        m for m in models_yaml["candidate_pool"]["verified_models"] if "text_gen" not in (m.get("types") or [])]
    r2 = type_route("text_gen", stripped)  # 达标候选被清空 → manual
    ok = r2["decision"] == "manual"
    if not ok:
        failures.append(f"空候选 text_gen 期望 manual 实得 {r2['decision']}")
    print(f"  {'✓' if ok else '✗'} text_gen 达标池清空 → manual")

    r3 = ui_design_tiers(models_yaml)
    tiers, fell = r3
    models_in_tier = [t["model"] for t in tiers]
    share_sum = round(sum(t.get("share", 0) for t in tiers), 6)
    ok = sorted(models_in_tier) == ["glm-5.3", "minimax-m3", "qwen3.8-max"] and share_sum == 1.0
    if not ok:
        failures.append(f"Tier 完整性: 期望 [glm-5.3, minimax-m3, qwen3.8-max] share=1.0 实得 {models_in_tier} share={share_sum}")
    print(f"  {'✓' if ok else '✗'} ui_design Tier 完整性（3 模型 + share 合计 1.0，fallback={fell}）")

    broken = dict(models_yaml)
    broken["tool_seats"] = {}  # 工具席缺失 → manual 不裸 KeyError
    r4 = type_route("image_understand", broken)
    ok = r4["decision"] == "manual"
    if not ok:
        failures.append(f"工具席缺失防御: 期望 manual 实得 {r4['decision']}")
    print(f"  {'✓' if ok else '✗'} tool_seats 缺失 → manual（A5 防御）")

    # ---- 段 6：副本一致性（court 权威 ↔ tools ↔ 运行位；仅本机存在时校验，P5）----
    print("== 段 6：副本 md5 一致性（P5 防漂移）==")
    # 段 6 副本路径：HERE=.../sanjiu-core/tools/court → 4 层 dirname = .../00_global-shared
    here_md5 = _md5(os.path.abspath(__file__))
    ws_shared = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
    peers = {"tools/route_task.py": os.path.join(os.path.dirname(HERE), "route_task.py"),
             "运行位 eep-tools/route_task.py": os.path.join(ws_shared, "tools", "eep-tools", "route_task.py")}
    for label, p in peers.items():
        if not os.path.exists(p):
            print(f"  ○ {label} 不在本机（跳过校验）")
            continue
        same = _md5(p) == here_md5
        if not same:
            failures.append(f"副本漂移: {label} 与权威版不一致（本文件 md5={here_md5[:12]}）")
        print(f"  {'✓' if same else '✗'} {label} 与权威版{'一致' if same else '漂移！'}")
    rules_peers = {"运行位 eep-tools/routing_rules.yaml": os.path.join(ws_shared, "tools", "eep-tools", "routing_rules.yaml")}
    for label, p in rules_peers.items():
        if not os.path.exists(p):
            print(f"  ○ {label} 不在本机（跳过校验）")
            continue
        same = _md5(p) == _md5(os.path.join(HERE, "routing_rules.yaml"))
        if not same:
            failures.append(f"副本漂移: {label} 与权威 rules 不一致")
        print(f"  {'✓' if same else '✗'} {label} 与权威 rules{'一致' if same else '漂移！'}")

    total = 10 + len(cls_cases) + len(rec_cases) + 3 + 4 + 4
    passed = total - len(failures)
    print(f"回测: {passed}/{total} 通过（failures={len(failures)}）")
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
        task = json.load(open(sys.argv[1], encoding="utf-8"))
        rules = load_rules()
        models_yaml = load_models()[0]
    except FileNotFoundError as e:  # P9：友好报错替代栈追踪
        print(f"✗ 路由/模型配置缺失：{e}", file=sys.stderr)
        sys.exit(2)
    combo, reason, matched = route(task, rules)
    ttype = classify_type(task)
    out = {"combo": combo, "combo_name": rules["combos"][combo]["name"],
           "reason": reason, "matched": matched,
           "task_type": ttype, "type_note": "低置信=compound 需人工改判",
           "type_route": type_route(ttype, models_yaml, task.get("exclude_vendor"))}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
