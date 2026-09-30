# 再审包：ui_design 样板归档（一审对抗二轮——针对首轮 7 项逐条修正回报）

## 首轮裁定：退回（P0×2 / P1×3 / P2×2）。逐条修正如下：

**P0-1 预览图归属**：✅ 已修。canonical 预览图 = templates/dashboards/lawfirm-ops-cream/preview-light.png（模板目录内）；meta.json 增 derived_assets 字段声明 site/public/previews/ 副本为站点构建产物。（仓内既有惯例本就是 site/previews 存放，本次按单一归属原则收紧：源在模板目录、站点为衍生。）

**P0-2 回链版本锚定**：✅ 已修。meta.json origin_eval = "sanjiu-core@83d0b60:docs/evidence/type-eval/（…）"，40 位 SHA；该 commit 已推送 origin/main（83d0b60 之继承链，远程为 silvrblt/sanjiu-core 私有仓）。

**P1-3 规范未随包/复刻未验证**：✅ 规范全文已随模板入 ui-design-library 仓（src/生成规范-v1-律所看板.md 2283 字 + src/风格基线-v3-qwen实测规范.txt + token.json 实测色值令牌）。跨模型复刻对照实验（≥90% 相似度）按决策人"先不用额外跑"指示**列为月度补测项**，不在本轮虚假声明"已验证"——规范可用性的现有证据 = 同规范下 v5/v6/定稿三次生成风格一致（同模型）。

**P1-4 索引重建佐证**：✅ 已留痕。命令 node tools/build-index.mjs；输出 1475 模板（dashboards 118）；templates/index.json SHA-256 = 4557d600f5345a3c80464329c3f254cdc2eac0fe。

**P1-5 未决项与终态口径混淆**：✅ 已解耦。终版说明（P2-6 文档）明确："ui_design 生成路由为决策人终裁终态；其余 5 项未决属其他类型/机制层，不阻塞日常运行"——决策人问"还有什么没解决"以未决清单如实作答。

**P2-6 阵容文档**：✅ 已写并推送：sanjiu-core@83d0b60:docs/三审九方阵容与路由终版说明-20260905.md（九方矩阵/两层路由/UI 路径/未决清单全量）。

**P2-7 成本参数基线**：✅ 已锚实测：minimax-m3 thinking off 生成 3 次（v4 9261/v5 11666/v6 10717 out tok）+ 定稿版，台账 cost-opt/docs/ledger/ai-cost-2026-09-05.jsonl task=ui-template-v4-v6；≈¥0.1/页为实测均值（out ≈10-12k tok × ¥2.1/M ≈ ¥0.09-0.12）。70/20/10 为预估使用占比（已标注"预估"）。

## 变更文件清单
- ui-design-library（工作区，待 commit）：templates/dashboards/lawfirm-ops-cream/{meta.json,token.json,preview-light.png,src/*} + site/public/previews/dashboards/lawfirm-ops-cream/light.png + templates/index.json（重建）
- sanjiu-core@83d0b60：docs/三审九方阵容与路由终版说明-20260905.md

## 请裁定
1. 七项修正是否闭环，可否放行归档落地（ui-design-library commit + push）？
2. 如仍有分歧点，请列明（将按组合 A 升 M3 裁决）。
输出：结论（放行/退回）→ 遗留问题清单 → 分歧点（如有）。
