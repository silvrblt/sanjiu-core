#!/usr/bin/env python3
"""route_task.py — 立案庭路由（审级组合分流 + 类型路由消费，v1.2.2 2026-09-06 三审终核二轮补正）

两层：
  1. 审级组合分流（审级组合需求 v6 定稿 2026-09-03）：domain/scale/type/history → 组合 A/B/A_exception/C_trigger
  2. 类型路由消费（类型路由需求 v5 定稿 2026-09-03）：任务类型 → 候选池达标模型自动接线，
     即终版说明 §三 未决清单 #1 的消费侧部分（未决清单整体**暂缓关闭**——D5 三审终裁：
     R1 完整判定器/R3 逐审级席位路由/R4 达标度公式未闭环，遗留见 docs/type-route/审计链记录 §四；
     选择优先级①合规异厂 ②测评达标 ③输入价最低 ④±10% 同价档内输出价升序（降级实现：
     yaml 无达标度数值字段，R4 原 0.7×达标度公式待月度补测补字段后恢复）；
     ui_design 走老板终裁 Tier（share 加权调度）；image_* 走工具席 tool_seats；compound 人工改判）
  3. 审计修正履历：
     v1.2.0（组合 B 二审共识，2026-09-06）：doubao 承办 P1-P12 + DS Pro 对抗 A1-A5 → 全部处置（见
       docs/type-route/审计链记录-类型路由消费代码-20260906.md；P6/P8/P11 = R1 判定器升级后续节奏）
     v1.2.1（Qwen 三审终核一轮打回 T1-T12 补正，2026-09-06）：动态计数/位置无关副本校验/配置结构防御/
       exclude_vendor 覆盖 Tier 与 tool_seat 边界/0 价防御/数值防御/快照+动态不变量/双需求口径/yaml 注记清理
     v1.2.2（Qwen 三审终核二轮打回 Q1-Q11 补正，2026-09-06）：Q1 未决清单口径（暂缓关闭，移除"关闭"表述）/
       Q2 load_rules 全结构校验 + main 全段捕获 / Q3 yaml 降级口径注记与 updated_at /
       Q4 段 6 固定预期副本清单 + env 覆盖 / Q5 sync-local 2b2 证据入审计记录 /
       Q6 ui_design 输出 selection_policy / Q7 exclude_vendor 支持 list / Q8 未知 vendor 警告 /
       Q9 video_read.note 价格口径 / Q10 _threshold 非法回退 / Q11 sha256 + with open + 全 inf 不变量收口

依赖：PyYAML ≥ 5.0（pip install pyyaml）；其余仅标准库。

用法：
  route_task.py <任务卡.json>          # 任务卡含 domain/scale/type/errors_ledger_count 字段；可选 exclude_vendor
  route_task.py --self-test            # 六段自检（组合/判定/推荐/异厂/边界/副本一致性；动态计数）
输出：JSON {combo, combo_name, reason, matched, task_type, type_note, type_route}

规则源：routing_rules.yaml（唯一事实源；探测顺序 = SANJIU_ROUTING_YAML → 同目录 → 上级目录 → 同目录/court）
模型源：sanjiu-models.yaml（唯一事实源；探测顺序 = SANJIU_MODELS_YAML → 同目录 → 上级目录）

副本约定（2026-09-06 收口）：tools/court/route_task.py = 权威版；tools/route_task.py 与运行位
00_global-shared/tools/eep-tools/route_task.py 为同步副本（sync-local.sh 2b2 纳入；self_test 段 6 校验）。
"""
import json
import os
import sys
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


class ConfigError(Exception):
    """路由/模型配置缺失或结构异常（T5）。"""


def locate_rules():
    """routing_rules.yaml 探测：SANJIU_ROUTING_YAML → 同目录 → 上级目录 → 同目录/court（顺序即优先级）。"""
    override = os.environ.get("SANJIU_ROUTING_YAML")
    if override:
        if os.path.exists(override):
            return override
        raise ConfigError(f"SANJIU_ROUTING_YAML 指定文件不存在: {override}")
    for d in (HERE, os.path.dirname(HERE), os.path.join(HERE, "court")):
        p = os.path.join(d, "routing_rules.yaml")
        if os.path.exists(p):
            return p
    raise ConfigError("routing_rules.yaml 未找到（同目录/上级目录/同目录court 均无；可用 SANJIU_ROUTING_YAML 指定）")


def locate_models_yaml():
    """sanjiu-models.yaml 探测：SANJIU_MODELS_YAML → 同目录 → 上级目录。"""
    override = os.environ.get("SANJIU_MODELS_YAML")
    if override:
        if os.path.exists(override):
            return override
        raise ConfigError(f"SANJIU_MODELS_YAML 指定文件不存在: {override}")
    for d in (HERE, os.path.dirname(HERE)):
        p = os.path.join(d, "sanjiu-models.yaml")
        if os.path.exists(p):
            return p
    raise ConfigError("sanjiu-models.yaml 未找到（同目录/上级目录均无；可用 SANJIU_MODELS_YAML 指定）")


def load_rules():
    try:
        with open(locate_rules(), encoding="utf-8") as f:
            rules = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"routing_rules.yaml 解析失败: {e}")
    if not isinstance(rules, dict):
        raise ConfigError("routing_rules.yaml 顶层须为 dict")
    rr = rules.get("routing_rules")
    if not isinstance(rr, dict):
        raise ConfigError("routing_rules.yaml 结构异常：缺 routing_rules 节")
    for key in ("force_b", "simple_a", "exceptions"):
        if not isinstance(rr.get(key), list):
            raise ConfigError(f"routing_rules.yaml 结构异常：routing_rules.{key} 须为 list")
    combos = rules.get("combos")
    if not isinstance(combos, dict) or any(c not in combos or not isinstance(combos[c], dict) or not combos[c].get("name")
                                           for c in ("A", "B", "A_exception", "C_trigger")):
        raise ConfigError("routing_rules.yaml 结构异常：combos 须含 A/B/A_exception/C_trigger 且各有 name")
    return rules


def load_models(path=None):
    """读 sanjiu-models.yaml 全量 → (data, verified_models)；T5 结构校验。"""
    path = path or locate_models_yaml()
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"sanjiu-models.yaml 解析失败: {e}")
    pool = (data or {}).get("candidate_pool")
    verified = (pool or {}).get("verified_models")
    if not isinstance(verified, list):
        raise ConfigError("sanjiu-models.yaml 结构异常：缺 candidate_pool.verified_models 列表")
    return data, verified


def _find_core_root(start):
    """向上查找 sanjiu-core 仓根（含 tools/court/routing_rules.yaml 的最近祖先）；找不到返回 None（T3 位置无关）。"""
    p = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(p, "tools", "court", "routing_rules.yaml")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


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
    修正履历：A1（v1.2.0）输入仅 title/description/prompt——审级 type 字段的 "bugfix" 子串 "bug"
    会误命中 code_gen 关键词（原 bugfix 任务全误判 code_gen）。
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
    """数值化防御：非正数/非数值一律 inf（T7：anchor≤0 不做除法；None/字符串不参与排序）。"""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else float("inf")


def _int_hist(v):
    """T8：errors_ledger_count 任务侧数值防御——非法输入置 0。"""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else 0


def _threshold(v):
    """Q10：规则侧 history threshold 防御——缺失/非法/非正回退默认 5（防 threshold 被归 0 导致全量触发 B）。"""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return v
    return 5


def _norm_excludes(exclude_vendor):
    """Q7：exclude_vendor 归一化为集合（支持 str | list[str] | None；空值 = 不过滤）。"""
    if exclude_vendor is None:
        return set()
    if isinstance(exclude_vendor, str):
        return {exclude_vendor} if exclude_vendor else set()
    if isinstance(exclude_vendor, (list, tuple)):
        return {v for v in exclude_vendor if isinstance(v, str) and v}
    return set()


def rank_models(ttype, models, exclude_vendor=None):
    """选择优先级 ②③④：types 达标过滤（②）→ exclude_vendor 异厂（① 消费接口，支持 str/list）→
    输入价升序（③）→ ±10% 同价档内按输出价升序（④ 次级锚，降级实现——yaml 无达标度数值字段，
    R4 原 0.7×达标度公式不可复现；月度补测补字段后恢复原公式）。
    同价档规则：以档首（最小）price_in 为锚，与锚差 ≤10% 归同档（不链式传播；anchor≤0 单独成档），
    档内按 price_out 升序。A4：候选复制后排序，不原地修改 yaml 解析对象。返回排序后候选全量。"""
    ex = _norm_excludes(exclude_vendor)
    hits = [dict(m) for m in models if ttype in (m.get("types") or [])]
    if ex:
        hits = [m for m in hits if m.get("vendor") not in ex]
    hits.sort(key=lambda m: _num(m.get("price_in")))
    result = []
    i = 0
    while i < len(hits):
        j = i
        anchor = _num(hits[i].get("price_in"))
        while (j + 1 < len(hits)
               and anchor != float("inf") and _num(hits[j + 1].get("price_in")) != float("inf")
               and (_num(hits[j + 1].get("price_in")) - anchor) / anchor <= 0.10):
            j += 1
        result.extend(sorted(hits[i:j + 1], key=lambda m: _num(m.get("price_out"))))
        i = j + 1
    return result


def _vendor_of(models_yaml, model):
    """从 verified_models 查模型 vendor（Tier/tool_seat 异厂过滤用）；查不到 None。"""
    for m in (models_yaml.get("candidate_pool") or {}).get("verified_models") or []:
        if m.get("model") == model:
            return m.get("vendor")
    return None


def ui_design_tiers(models_yaml):
    """yaml candidate_pool.ui_design_tiers 为事实源；缺节/结构异常 → 内置 fallback（P3）。"""
    tiers = (models_yaml.get("candidate_pool") or {}).get("ui_design_tiers")
    if isinstance(tiers, list) and tiers and all(isinstance(t, dict) and "model" in t and "share" in t for t in tiers):
        return tiers, False
    return list(UI_DESIGN_TIERS_FALLBACK), True


def ui_design_decision(models_yaml, exclude_vendor=None):
    """ui_design：老板 2026-09-05 终裁 Tier 分工（不走通用价格序，D1 终裁采纳）。
    T6/Q7：exclude_vendor（str/list）命中 tier 模型厂商时剔除该档，降级取次档；全剔除 → manual。
    Q6：recommended = 最高可用档展示值，实际生产按 share 加权调度（selection_policy 明示）。
    Q8：tier 模型在 verified_models 查不到 vendor 且存在 exclude 时 → note 显式警告。"""
    tiers, fell_back = ui_design_tiers(models_yaml)
    note = ("ui_design 生产分工按老板 2026-09-05 终裁 Tier（yaml candidate_pool.ui_design_tiers 事实源），"
            "不走通用价格序；hy3/doubao 资格已移出 yaml；DS 系虽持 ui_design 测评资格但不在终裁分工内；"
            "recommended 为最高可用档展示值，生产按 share 加权调度（70/20/10）")
    if fell_back:
        note += "；[fallback] yaml ui_design_tiers 缺失，使用内置常量"
    ex = _norm_excludes(exclude_vendor)
    if ex:
        kept = []
        unknown = []
        for t in tiers:
            v = _vendor_of(models_yaml, t["model"])
            if v is None:
                unknown.append(t["model"])
                kept.append(t)  # vendor 不可知不盲剔（Q8）
            elif v not in ex:
                kept.append(t)
        tiers = kept
        note += f"；exclude_vendor={sorted(ex)} 过滤后取剩余档"
        if unknown:
            note += f"；[警告] {unknown} vendor 未在 verified_models 登记，未参与过滤"
    if not tiers:
        return {"decision": "manual", "recommended": None, "candidates": [],
                "note": f"ui_design 无可用 Tier（exclude_vendor={exclude_vendor} 过滤后为空），人工指派"}
    return {
        "decision": "tier",
        "selection_policy": "weighted_by_share",
        "recommended": {"model": tiers[0]["model"], "tier": tiers[0]["tier"],
                        "note": "按 share 加权调度，此处展示最高可用档"},
        "candidates": tiers,
        "note": note,
    }


def tool_seat_decision(ttype, models_yaml, exclude_vendor=None):
    """image_*：工具席主备输出（不走审级；主备/冷备/CLI 从 yaml tool_seats 读，防双份事实源）。
    A5：配置缺失/异常 → manual + 明确错误。T6：工具席失败升级链不做异厂过滤（异厂约束适用审级链），
    但 exclude_vendor 与 primary 同厂时输出显式提示。"""
    tool = TYPE_TOOL_SEAT[ttype]
    seat = (models_yaml.get("tool_seats") or {}).get(tool)
    if not isinstance(seat, dict) or not seat.get("model"):
        return {"decision": "manual", "recommended": None, "candidates": [],
                "note": f"工具席配置缺失/异常（tool_seats.{tool}），人工指派"}
    alternates = seat.get("alternates") if isinstance(seat.get("alternates"), list) else []
    primary = {"model": seat["model"], "cli": seat.get("cli"), "note": "工具席不走审级（视觉三级验收/独立记账）"}
    note = f"{ttype} = 工具席 {tool}（tool_seats 唯一事实源），非审级候选池；失败升级链不做异厂过滤"
    if exclude_vendor and _vendor_of(models_yaml, seat["model"]) == exclude_vendor:
        note += f"；[提示] primary 与 exclude_vendor={exclude_vendor} 同厂——工具席不受审级异厂约束，若需异厂替代请人工指定"
    return {
        "decision": "tool_seat",
        "tool_seat": tool,
        "recommended": primary,
        "candidates": [{"model": m, "note": "失败升级/冷备"} for m in alternates],
        "note": note,
    }


def type_route(ttype, models_yaml, exclude_vendor=None):
    """类型路由消费主入口：任务类型 → {decision, recommended, candidates, note}。
    decision ∈ ranked / tier / tool_seat / manual。D3：本层为单层「任务执行模型」推荐，非逐审级席位替换。"""
    if ttype == "compound":
        return {"decision": "manual", "recommended": None, "candidates": [],
                "note": "复合类（零命中/多类并列）需人工改判：显式 type 字段后重新立案路由"}
    if ttype in TYPE_TOOL_SEAT:
        return tool_seat_decision(ttype, models_yaml, exclude_vendor)
    if ttype == "ui_design":
        return ui_design_decision(models_yaml, exclude_vendor)
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
    dom = str(task.get("domain", ""))
    scale = str(task.get("scale", ""))
    ttype = str(task.get("type", ""))
    hist = _int_hist(task.get("errors_ledger_count", 0))  # 30 天滚动同域 count（T8 数值防御）

    # ① force_b：域/规模/历史（最高优先；history 阈值从 rules 读——A2，routing_rules.yaml 结构化）
    for sig in rules["routing_rules"]["force_b"]:
        if sig.get("signal") == "domain" and dom == sig.get("value"):
            return "B", f"强制域:{dom}", [sig]
        if sig.get("signal") == "scale" and scale == sig.get("value"):
            return "B", f"跨模块重构:{scale}", [sig]
        if sig.get("signal") == "history" and hist >= _threshold(sig.get("threshold", 5)):
            return "B", f"历史高错误率:{hist}", [sig]

    # ② 例外：单文件 bugfix
    if ttype == "bugfix" and scale == "single_file":
        return "A_exception", "单文件bugfix例外（留痕+月度抽审）", rules["routing_rules"]["exceptions"]

    # ③ simple_a
    for sig in rules["routing_rules"]["simple_a"]:
        if sig.get("signal") == "type" and ttype == sig.get("value"):
            return "A", f"类型:{ttype}", [sig]
        if sig.get("signal") == "scale" and scale == sig.get("value"):
            return "A", f"规模:{scale}", [sig]

    # ④ default
    return "A", "默认组合 A", []


def _file_sha256(path):
    """Q11：文件完整性校验用 sha256（与审计口径一致）。"""
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def self_test():
    """六段自检（纯本地零成本）。动态计数（T1/T2）：passed/skipped/failures 分开，缺失副本计 skipped 不计通过。"""
    rules = load_rules()
    models_yaml, verified = load_models()
    failures = []
    passed = 0
    skipped = 0

    def check(ok, label, failmsg):
        nonlocal passed
        if ok:
            passed += 1
            print(f"  ✓ {label}")
        else:
            failures.append(failmsg)
            print(f"  ✗ {label}")

    def skip(label):
        nonlocal skipped
        skipped += 1
        print(f"  ○ {label}（本机不存在，跳过）")

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
        check(got == expect,
              f"{json.dumps(task, ensure_ascii=False)[:56]} → {got}",
              f"组合: {task} 期望 {expect} 实得 {got}（{reason}）")

    # ---- 段 2：类型判定（8 类 ×2 + compound ×2 + bugfix 回归 ×2）----
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
        check(got == expect, f"「{(task.get('title') or '')[:36]}」→ {got}",
              f"判定: 「{task}」期望 {expect} 实得 {got}")

    # ---- 段 3：类型推荐（快照：价格基线 2026-09-06，价格 watch 重排时同步更新；T9 附动态不变量）----
    print("== 段 3：类型推荐快照 + 动态不变量（价格基线 2026-09-06）==")
    rec_cases = [
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
        check(ok, f"{ttype} → {got['decision']} {(got['recommended'] or {}).get('model')}",
              f"推荐快照: {ttype} 期望 {expect_d}/{expect_m} 实得 {got['decision']}/{(got['recommended'] or {}).get('model')}")
        # T9 动态不变量（不依赖快照值，与 ±10% 同价档语义一致）：
        # ①全候选 types 达标；②序列无 >10% 的输入价逆序（同档内按输出价排序允许 ≤10% 回退）；
        # ③top 属于最低价档（价 ≤ 最低×1.1）且为该档内输出价最小者。
        if expect_d == "ranked":
            cands = got["candidates"]
            prices = [_num(c.get("price_in")) for c in cands]
            vm = {v.get("model"): (v.get("types") or []) for v in verified}
            all_qual = all(ttype in vm.get(c["model"], []) for c in cands)
            no_big_inv = all(
                a <= b or (b != float("inf") and (a - b) / b <= 0.10)
                for a, b in zip(prices, prices[1:]))
            top_ok = False
            if prices:
                pmin = min(prices)
                if pmin == float("inf"):
                    top_ok = False  # Q11：全异常价不得宽松通过（正常数据 pmin 恒有限）
                else:
                    low_band = [c for c in cands if _num(c.get("price_in")) <= pmin * 1.1 + 1e-9]
                    low_outs = [_num(c.get("price_out")) for c in low_band]
                    top_ok = (_num(got["recommended"].get("price_in")) <= pmin * 1.1 + 1e-9
                              and _num(got["recommended"].get("price_out")) == min(low_outs))
            check(all_qual and no_big_inv and top_ok,
                  f"[不变量] {ttype} 全达标 + 无>10%逆序 + top∈最低价档且档内输出价最低",
                  f"不变量: {ttype} all_qual={all_qual} no_big_inv={no_big_inv} top_ok={top_ok}")

    # ---- 段 4：exclude_vendor（合规异厂）+ 同价档排序 ----
    print("== 段 4：exclude_vendor / 同价档 / Tier 异厂过滤 ==")
    got = type_route("code_gen", models_yaml, exclude_vendor="minimax")
    check(got["recommended"]["model"] == "doubao-2.1-turbo",
          f"code_gen + exclude_vendor=minimax → {got['recommended']['model']}",
          f"exclude_vendor: code_gen 排除 minimax 期望 doubao-2.1-turbo 实得 {got['recommended']['model']}")

    ranked = rank_models("code_gen", verified)
    expect_order = ["minimax-m3", "doubao-2.1-turbo", "kimi-k2.7-code", "doubao-seed-2.1-pro", "kimi-k2.7-code-highspeed"]
    got_order = [m["model"] for m in ranked]
    check(got_order == expect_order, f"code_gen 候选序 → {got_order}",
          f"同价档: code_gen 候选序 期望 {expect_order} 实得 {got_order}")

    got_t = type_route("ui_design", models_yaml, exclude_vendor="minimax")
    check(got_t["decision"] == "tier" and got_t["recommended"]["model"] == "qwen3.8-max",
          f"ui_design + exclude_vendor=minimax → {got_t['recommended']['model']}（降级取 T2）",
          f"Tier 异厂: 期望剔除 minimax 后取 qwen3.8-max 实得 {got_t['recommended']}")

    # Q7：exclude_vendor list 支持（多厂商排除）
    got_l = type_route("code_gen", models_yaml, exclude_vendor=["minimax", "doubao"])
    check(got_l["recommended"]["model"] == "kimi-k2.7-code",
          f"code_gen + exclude_vendor=[minimax,doubao] → {got_l['recommended']['model']}",
          f"exclude list: 期望 kimi-k2.7-code 实得 {got_l['recommended']}")
    # Q6：ui_design 输出 selection_policy
    got_p = type_route("ui_design", models_yaml)
    check(got_p.get("selection_policy") == "weighted_by_share",
          "ui_design 输出含 selection_policy=weighted_by_share（Q6）",
          f"selection_policy 缺失: {got_p}")

    # ---- 段 5：边界（未知扩展类/空候选/Tier 完整性/工具席缺失防御/0 价防御）----
    print("== 段 5：边界（扩展类/空候选/Tier/工具席缺失/0 价）==")
    r1 = type_route("code_debug", models_yaml)  # 扩展类未入 RANK_TYPES
    check(r1["decision"] == "manual", "扩展类型 code_debug → manual",
          f"扩展类型 code_debug 期望 manual 实得 {r1['decision']}")

    stripped = dict(models_yaml)
    stripped["candidate_pool"] = dict(models_yaml["candidate_pool"])
    stripped["candidate_pool"]["verified_models"] = [
        m for m in verified if "text_gen" not in (m.get("types") or [])]
    r2 = type_route("text_gen", stripped)
    check(r2["decision"] == "manual", "text_gen 达标池清空 → manual",
          f"空候选 text_gen 期望 manual 实得 {r2['decision']}")

    tiers, fell = ui_design_tiers(models_yaml)
    models_in_tier = sorted(t["model"] for t in tiers)
    share_sum = round(sum(t.get("share", 0) for t in tiers), 6)
    check(models_in_tier == ["glm-5.3", "minimax-m3", "qwen3.8-max"] and share_sum == 1.0,
          f"ui_design Tier 完整性（3 模型 + share=1.0，fallback={fell}）",
          f"Tier 完整性: 期望 [glm-5.3, minimax-m3, qwen3.8-max] share=1.0 实得 {models_in_tier} share={share_sum}")

    broken = dict(models_yaml)
    broken["tool_seats"] = {}
    r4 = type_route("image_understand", broken)
    check(r4["decision"] == "manual", "tool_seats 缺失 → manual（A5 防御）",
          f"工具席缺失防御: 期望 manual 实得 {r4['decision']}")

    # T7：0 价/异常价 = inf 排末位且不与正常价同档（无除零）
    fake = [{"model": "x-free", "vendor": "vx", "price_in": 0, "price_out": 1, "types": ["code_audit"]},
            {"model": "x-1", "vendor": "vx", "price_in": 1.0, "price_out": 4, "types": ["code_audit"]}]
    r5 = rank_models("code_audit", fake)
    check([m["model"] for m in r5] == ["x-1", "x-free"] and _num(r5[1]["price_in"]) == float("inf"),
          "price_in=0 异常价排末位且不除零（T7）",
          f"0 价防御: 期望 [x-1, x-free(末位)] 实得 {[m['model'] for m in r5]}")

    # Q10：threshold 非法值回退 5（不归 0 全量触发）
    rr_bad = {"signal": "history", "value": "error_rate_high_30d_ge5", "threshold": -1}
    check(route({"errors_ledger_count": 2}, {"routing_rules": {"force_b": [rr_bad], "simple_a": [], "exceptions": []}, "combos": {}})[0] == "A",
          "threshold=-1 回退 5 → hist=2 不触发 B（Q10）",
          "threshold 防御: -1 应回退 5 且 hist=2 不触发")
    rr_str = {"signal": "history", "value": "error_rate_high_30d_ge5", "threshold": "x"}
    check(route({"errors_ledger_count": 9}, {"routing_rules": {"force_b": [rr_str], "simple_a": [], "exceptions": []}, "combos": {}})[0] == "B",
          "threshold='x' 回退 5 → hist=9 触发 B（Q10）",
          "threshold 防御: 'x' 应回退 5 且 hist=9 触发")

    # ---- 段 6：副本一致性（Q4：固定预期副本清单——存在即比 sha256，缺失显式 skip；env 可覆盖路径）----
    print("== 段 6：副本 sha256 一致性（P5 防漂移；缺失=skipped）==")
    here_sha = _file_sha256(os.path.abspath(__file__))
    # 预期副本：主仓 court/tools + 运行位 eep-tools；默认布局 = 主仓上两级 00_global-shared/tools/eep-tools
    core_root = os.environ.get("SANJIU_CORE_ROOT") or (_find_core_root(HERE) or "")
    eep_dir = os.environ.get("SANJIU_EEP_DIR") or (os.path.join(os.path.dirname(os.path.dirname(core_root)), "tools", "eep-tools") if core_root else "")
    expected_peers = []
    if core_root:
        expected_peers.append(("主仓 tools/route_task.py", os.path.join(core_root, "tools", "route_task.py")))
    if eep_dir:
        expected_peers.append(("运行位 tools/eep-tools/route_task.py", os.path.join(eep_dir, "route_task.py")))
        expected_peers.append(("运行位 tools/eep-tools/routing_rules.yaml", os.path.join(eep_dir, "routing_rules.yaml")))
    if not expected_peers:
        skip("段 6（无仓根/运行位定位：SANJIU_CORE_ROOT/SANJIU_EEP_DIR 未设且探测失败）")
    seen = set()
    for label, p in expected_peers:
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        if not os.path.exists(p):
            skip(f"{label}（{p} 不存在）")
            continue
        if "routing_rules.yaml" in p:
            same = _file_sha256(p) == _file_sha256(locate_rules())
        else:
            same = _file_sha256(p) == here_sha
        check(same, f"{label} 一致", f"副本漂移: {label}（{p}）")

    total = passed + len(failures) + skipped
    print(f"回测: {passed}/{total} 通过，{len(failures)} 失败，{skipped} 跳过（动态计数）")
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
        try:
            with open(sys.argv[1], encoding="utf-8") as f:
                task = json.load(f)
        except (json.JSONDecodeError, OSError) as e:  # 任务卡非法 → 友好报错
            print(f"✗ 任务卡读取/解析失败：{e}", file=sys.stderr)
            sys.exit(2)
        if not isinstance(task, dict):
            print("✗ 任务卡须为 JSON 对象", file=sys.stderr)
            sys.exit(2)
        rules = load_rules()
        models_yaml = load_models()[0]
        combo, reason, matched = route(task, rules)
        ttype = classify_type(task)
        out = {"combo": combo, "combo_name": rules["combos"][combo]["name"],
               "reason": reason, "matched": matched,
               "task_type": ttype, "type_note": "低置信=compound 需人工改判",
               "type_route": type_route(ttype, models_yaml, task.get("exclude_vendor"))}
    except (ConfigError, KeyError, TypeError, AttributeError) as e:  # Q2：配置/结构异常全段友好退出
        print(f"✗ 路由执行错误：{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
