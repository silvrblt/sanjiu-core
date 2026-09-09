---
name: sanjiu-court
description: 三审九方立案庭——建卡阈值内任务进入即自动立案分流（A 一审+二审/B 二审+三审/单文件例外/升级触发器 C）并自动路由承办模型（lead_route v1.0.2）；说「三审九方 X」= 快捷触发；规则与脚本见 eep-tools（routing_rules.yaml 唯一事实源）
metadata:
  version: "1.2"
---

# Skill: sanjiu-court（三审九方立案庭）

**触发**：所有建卡阈值内任务（预估产出 ≥300 字 / 需留痕 / 需审级，A1 2026-09-07 扩展——不依赖用户先说「三审九方」）进入即自动立案 + 承办路由；说「三审九方 X」= 显式快捷触发。纯工具类短问答直接会话答复。需求文档：`01_projects/cost-opt/docs/需求文档-审级组合化与立案庭-v1.md`（v6 定稿）+ 类型路由 v5（candidate_pool 数据层 + type_route 消费层 v1.2.3）+ 承办自动路由 v1（方案 A，2026-09-07 老板拍板）。

## 路由（第一步，必做——自动立案）

1. 任务进入先写任务卡 JSON（含 title/description；type 判定自动；domain/scale/errors_ledger_count
   可人工标注或省略走默认），运行**自动立案 + 承办路由（一次调用 = 立案全量）**：
   ```bash
   python3 00_global-shared/tools/eep-tools/lead_route.py <任务卡.json> --out <承办产出路径>
   ```
   stdout JSON 含全量字段：combo（审级 A/B/A_exception/C_trigger）+ task_type + type_route
   + decision + 承办模型；`--dry-run` 先看决策不真调；`--force-model` 人工指定承办模型
   （非候选池模型将标注"人工强制，结果需核验"）。
2. **承办模型自动路由（v1.0 关键变化）**：`lead_route` 决策分流——
   - `ranked`：承办产出由类型路由推荐模型经桥接生成（推荐 ≠ 当前窗口模型时**自动换模型承办**，
     窗口会话 = 编排/验收角色；候选失败自动降级链，全败回退会话）；
   - `manual`（compound/零命中）：人工改判任务卡 type 后重新立案；
   - `tool_seat`（image_*）：工具席原链（glm-vision/ark-image，视觉三级验收）；
   - `tier`（ui_design）：模板库/生成规范 v1 资产生成链（2026-09-05 终裁分工，不直调）。
3. 输出 combo（A/B/A_exception/C_trigger）→ 按组合执行：
   - **A 一审+二审**：承办产出（lead_route 生成）→ 一审对抗 Hy3 全量 →（无分歧/分歧 M3）→ **二审对抗 DS Pro 终核（必经）**；分歧裁决 K2.7 可上诉；
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
- **承办产出一律过 lead_route 路由**（推荐 ≠ 窗口模型即自动换模型；`--force-model` 例外需留痕）；
  **建卡阈值（D3 执行细则）**：预估产出 ≥300 字 / 需留痕 / 需审级的任务必须建卡走路由；
  纯工具类短问答（如「XX 命令怎么用」）可直接会话答复，不立案不路由；
- 视觉/工具席不经审级（视觉三级验收 L1-L3 另行）；
- 路由结果写入任务卡/决策台账留痕（红线 12：可回溯）；
- 规则调参：回测 30 任务命中率 ≥90%（A2 验收）后才可改 routing_rules.yaml，改动走审计。
