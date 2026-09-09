---
name: sanjiu-court
description: 三审九方立案庭——说「三审九方 <任务>」即自动分流审级组合（A 一审+二审/B 二审+三审/单文件例外/升级触发器 C），路由规则与脚本见 eep-tools（routing_rules.yaml 唯一事实源）
metadata:
  version: "1.0"
---

# Skill: sanjiu-court（三审九方立案庭）

**触发**：任务以「三审九方」开头（或明确要求走三审九方）时，先跑立案庭路由，再按路由组合执行审计链。需求文档：`01_projects/cost-opt/docs/需求文档-审级组合化与立案庭-v1.md`（v6 定稿）。

## 路由（第一步，必做）

1. 提取任务特征：domain（external_delivery/finance/legal/security/framework_change/business/visual…）、scale（single_file/small/medium/large/cross_module_refactor）、type（bugfix/feature/internal_tool/analysis/mechanism…）、errors_ledger_count（30 天滚动同域）；
2. 写任务卡 JSON 到临时文件，运行：
   ```bash
   python3 /Users/sun/codex-workspace/00_global-shared/tools/eep-tools/route_task.py <任务卡.json>
   ```
   或直接用人工判定表（routing_rules.yaml 同构）；
3. 输出 combo（A/B/A_exception/C_trigger）→ 按组合执行：
   - **A 一审+二审**：一审承办产出 → 一审对抗 Hy3 全量 →（无分歧/分歧 M3）→ **二审对抗 DS Pro 终核（必经）**；分歧裁决 K2.7 可上诉；
   - **B 二审+三审**：二审承办（doubao l2_lead）起步 → 二审对抗 →（分歧 K2.7）→ 三审对抗 Qwen 终核（必经）→ 分歧 K3 终局；
   - **A_exception 单文件 bugfix**：一审承办自审 + 立案庭留痕（decision.jsonl）+ 二审月度抽审覆盖；
   - **C_trigger（运行中升级）**：A 执行中一审对抗出现 l1_kappa<0.2 且拦截>30% 或 P0 → 升三审对抗 Qwen 终核。

## 组合判定速查（人工兜底）

| 信号 | 组合 |
|---|---|
| domain ∈ 五强制域 / 跨模块重构 / 历史错误 count≥5 | B |
| 单文件 bugfix | A_exception（留痕+月度抽审） |
| 其余（内部工具/常规功能/分析） | A（二审终核必经） |
| A 中一审分歧重大 | 升 C_trigger |

## 纪律

- 强制域清单任务 100% 到 B（不因组合化降质——老板铁律）；
- 视觉/工具席不经审级（视觉三级验收 L1-L3 另行）；
- 路由结果写入任务卡/决策台账留痕（红线 12：可回溯）；
- 规则调参：回测 30 任务命中率 ≥90%（A2 验收）后才可改 routing_rules.yaml，改动走审计。
