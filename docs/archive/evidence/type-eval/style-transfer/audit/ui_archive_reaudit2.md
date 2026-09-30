# 三审包：ui_design 样板归档（一审对抗三轮——二轮 4 项修正回报）

**二轮裁定：退回（P0-1/P0-2/P1-3/P2-7）。逐条修正：**

**P0-1 衍生映射**：✅ meta.json derived_assets.mapping 显式声明 "preview-light.png → site/public/previews/dashboards/lawfirm-ops-cream/light.png"（源→目标逐文件映射）。

**P0-2 全哈希统一**：✅ origin_eval 内嵌 40 位完整 SHA（已程序化验证 len=40 且 grep 命中 1 处）：sanjiu-core@83d0b60e92bf3c0639e5e67ec8476a3803995fbe 之前的提交链；本轮后以最新 push 的 HEAD 为准（归档 commit 完成后回写 meta 不再变更——评估文档在独立 commit，模板回链指向 evidence 所在 commit 83d0b60e92bf3c0639e5e67ec8476a3803995fbe 即可，无需随主仓每次提交滚动更新）。

**P1-3 路径精确化**：✅ 规范三文件精确路径 = templates/dashboards/lawfirm-ops-cream/src/ 下：生成规范-v1-律所看板.md / 风格基线-v3-qwen实测规范.txt / dashboard.html；token.json 与 meta.json 在模板根目录。

**P2-7 成本证据内联**：✅ 实测台账行内联：{"model":"minimax-m3","in":2600,"out":44000,"cost":0.3751,"estimate":false,"task":"ui-template-v4-v6"}（cost-opt/docs/ledger/ai-cost-2026-09-05.jsonl，real 口径，4 次生成汇总）→ 单页实测 = ¥0.3751/4 ≈ ¥0.094/页。**声明：¥0.1/页仅作文档说明，不写入任何配置/预算硬顶字段。**

**变更清单（相对二轮）**：仅 meta.json（mapping+全哈希）+ 本回报文案。

## 请裁定
七项（首轮）+ 四项（二轮）是否全部闭环？可否放行 ui-design-library 归档 commit？
输出：结论（放行/退回）→ 遗留 → 分歧。
