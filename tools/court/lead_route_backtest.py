#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""30 任务回测（方案 A B5 验收证据；lead_route dry-run 批量，零模型成本）"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lead_route import route_and_execute, load_models  # noqa: E402

# 30 个合成任务：期望 decision +（ranked 时）期望首选模型
CASES = [
    # code_gen ×4
    ("code_gen", {"title": "实现用户登录接口", "description": "写后端代码"}, "minimax-m3"),
    ("code_gen", {"title": "开发一个 Python 脚本做文件批量处理"}, "minimax-m3"),
    ("code_gen", {"title": "实现购物车结算功能"}, "minimax-m3"),
    ("code_gen", {"title": "写一个条件规则解析器"}, "minimax-m3"),
    # code_audit ×3
    ("code_audit", {"title": "审查 PR 改动是否缺少鉴权"}, "hy3"),
    ("code_audit", {"title": "对仓库代码做安全审计"}, "hy3"),
    ("code_audit", {"title": "检查这段代码的越权缺陷"}, "hy3"),
    # text_gen ×4
    ("text_gen", {"title": "撰写产品宣传文案"}, "glm-5.3-flash"),
    ("text_gen", {"title": "生成一份活动公告"}, "glm-5.3-flash"),
    ("text_gen", {"title": "写一篇行业分析报告"}, "glm-5.3-flash"),
    ("text_gen", {"title": "生成产品介绍文案"}, "glm-5.3-flash"),
    # text_understand ×3
    ("text_understand", {"title": "总结这篇文章的要点"}, "hy3"),
    ("text_understand", {"title": "归纳这段对话的核心意图"}, "hy3"),
    ("text_understand", {"title": "解读这份合同关键条款"}, "hy3"),
    # data_analysis ×4
    ("data_analysis", {"title": "统计本月账单并出对账报表"}, "hy3"),
    ("data_analysis", {"title": "数据分析：清洗这份 csv 并聚合"}, "hy3"),
    ("data_analysis", {"title": "对销售数据做统计分析"}, "hy3"),
    ("data_analysis", {"title": "生成月度经营数据报表"}, "hy3"),
    # ui_design ×3（tier 指引）
    ("ui_design_tier", {"title": "设计一个经营看板页面"}, None),
    ("ui_design_tier", {"title": "前端布局调整 dashboard 界面"}, None),
    ("ui_design_tier", {"title": "做一套后台管理页面 UI"}, None),
    # image_understand ×2（tool_seat）
    ("image_tool", {"title": "识别这张截图的文字内容"}, None),
    ("image_tool", {"title": "看图并描述图表含义"}, None),
    # image_gen ×2（tool_seat）
    ("image_tool", {"title": "生成一张产品海报"}, None),
    ("image_tool", {"title": "用 AI 画一个 logo"}, None),
    # compound ×2（manual）
    ("compound", {"title": "生成数据分析看板"}, None),
    ("compound", {"title": "hello world 无任何类型词"}, None),
    # bugfix 回归 ×3（classify 不读 type 字段；标题驱动）
    ("code_gen", {"type": "bugfix", "title": "修复登录接口 token 校验 bug"}, "minimax-m3"),
    ("code_gen", {"type": "bugfix", "title": "修复导出功能日期格式错误"}, "minimax-m3"),
    ("compound", {"type": "bugfix", "title": "修正周报模板的错别字"}, None),
]
assert len(CASES) == 30, f"样例数={len(CASES)}"


def main():
    models_yaml = load_models()[0]
    ok_n = 0
    rows = []
    for expect_kind, task, expect_model in CASES:
        code, r = route_and_execute(task, models_yaml, dry_run=True)
        decision = r.get("decision")
        model = r.get("model")
        if expect_kind == "compound":
            good = decision == "manual"
        elif expect_kind == "ui_design_tier":
            good = decision == "tier"
        elif expect_kind == "image_tool":
            good = decision == "tool_seat"
        else:
            good = decision == "ranked" and model == expect_model
        ok_n += good
        rows.append({"ok": good, "title": (task.get("title") or "")[:24], "expect": expect_kind,
                     "decision": decision, "model": model})
        print(f"{'✓' if good else '✗'} [{expect_kind}] {rows[-1]['title']} → {decision} {model}")
    rate = ok_n / len(CASES)
    print(f"\n30 任务回测：{ok_n}/30 命中（命中率 {rate:.0%}，验收线 ≥90%）")
    # 输出证据 JSON
    ev_dir = os.path.join(os.path.dirname(HERE), "docs", "type-route", "evidence")
    os.makedirs(ev_dir, exist_ok=True)
    out = os.path.join(ev_dir, "lead_route-30任务回测-20260907.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"total": len(CASES), "hit": ok_n, "rate": rate, "cases": rows,
                   "note": "dry-run 批量（零模型成本）；期望表 = 类型路由快照基线 2026-09-06"}, f,
                  ensure_ascii=False, indent=1)
    print("证据落盘:", out)
    return 0 if rate >= 0.90 else 1


if __name__ == "__main__":
    sys.exit(main())
