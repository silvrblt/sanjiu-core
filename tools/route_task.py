#!/usr/bin/env python3
"""route_task.py — 立案庭路由（审级组合分流，需求 v6 定稿 2026-09-03）

用法：
  route_task.py <任务卡.json>          # 任务卡含 domain/scale/type/errors_ledger_count 字段
  route_task.py --self-test            # 30 任务回测自检（A2，部分内置）
输出：JSON {combo, reason, factors}

规则源：routing_rules.yaml（唯一事实源，同级目录）
"""
import json
import os
import sys
import yaml

RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "routing_rules.yaml")


def load_rules():
    with open(RULES, encoding="utf-8") as f:
        return yaml.safe_load(f)


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
    """类型判定器 v0（关键词命中计数，≥2 命中或最高分判定；低置信人工改判）。"""
    text = " ".join([str(task.get(k, "")) for k in ("title", "description", "prompt")]) + " " + str(task.get("type", ""))
    scores = {}
    for t, kws in TYPE_KEYWORDS.items():
        scores[t] = sum(1 for k in kws if k in text)
    best = max(scores, key=scores.get)
    top = [t for t, v in scores.items() if v == scores[best]]
    if scores[best] == 0 or len(top) > 1:
        return "compound"  # 零命中或多类并列 → 复合类（人工改判）
    return best


def self_test():
    """内置回测样例（10 项；完整 30 项在附录 C，实施期补齐）"""
    cases = [
        # (任务, 期望组合)
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
    rules = load_rules()
    passed = 0
    for task, expect in cases:
        got, reason, _ = route(task, rules)
        ok = got == expect
        passed += ok
        print(f"  {'✓' if ok else '✗'} {json.dumps(task, ensure_ascii=False)[:60]} → {got} ({reason})")
    print(f"回测: {passed}/{len(cases)} 通过")
    return 0 if passed == len(cases) else 1


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
           "task_type": ttype, "type_note": "低置信=compound 需人工改判"}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
