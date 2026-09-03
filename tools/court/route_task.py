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
    out = {"combo": combo, "combo_name": rules["combos"][combo]["name"],
           "reason": reason, "matched": matched}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
