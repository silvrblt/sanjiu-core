# 审计就绪包：ui_design 样板归档与规范管理（组合 A 一审对抗）

## 一、需求（决策人原话，2026-09-05）
1. 「落实好此次样板，放到该放的地方，下次要能在别的窗口调得出来。我们是不是还有一个 ui-design 的项目来着，要做好管理。尤其是以后关于 ui 设计的路径和思路、规范。——这个要走三审九方，务必确认好文件管理，不要东放一个文件西放一个，到处乱放。」
2. 「关于选模型的问题，现在都落实好了吗？还有什么没解决的？最终的最新的三审九方全模型阵容是怎么样，任务是怎么分工的，怎么做的路由的？」

## 二、承办产出（待审）
### A. 样板归档方案（文件管理单一归属）
- **UI 资产唯一事实源 = ui-design-library 仓**（templates/dashboards/lawfirm-ops-cream/）：
  - meta.json（含 boss_ruling 与 origin_eval 回链）/ token.json（设计令牌实测提取）/ src/dashboard.html（定稿代码）/ src/生成规范-v1-律所看板.md（可复刻规范单文件）/ src/风格基线-v3-qwen实测规范.txt（视觉规范源）
  - 预览图 site/public/previews/dashboards/lawfirm-ops-cream/light.png
  - index.json 已重建（1475 模板，dashboards 118）——其他窗口经 templates/index.json AI 索引按 tags 可检出
- **机制过程证据唯一事实源 = sanjiu-core 仓**（docs/evidence/type-eval/，v3.7.1 已推送）：测评原始产出/双盲/复核表/三模型分工定稿/风格迁移实验全过程——历史证据，不重复归档到 UI 仓，防两处漂移
- **迭代中间产物（v1/v2/v4/v5/v6 html/png）= workspace docs/evidence/type-eval/style-transfer/**：工作区过程件，不入两仓（v2 已废弃留证）；定稿与规范已提走
- 对照红绝 4（决策人要的直接给）：定稿图已在对话窗口直发

### B. ui_design 类型路由生效路径（生成类分工，决策人终裁）
- T1 主力 minimax-m3（+生成规范 v1 注入，thinking off，≈¥0.1/页，70%）/ T2 质感 qwen3.8-max（直出，20%）/ T3 替身 glm-5.3（10%）；hy3/doubao 已移出 ui_design
- 工具席不审级：image_gen=seedream-4.0（决策人盲选）；vision_read=glm-5.3-flash→kimi-k3
- 后续 UI 任务标准动作：ui-design-library 选型（index.json）→ 无匹配则按生成规范注入产新模板 → R10 入库 → 读图复核

### C. 选模型机制盘点（详见配套文档 sanjiu-core docs/三审九方阵容与路由终版说明-20260905.md）
- 九方矩阵不变（MECH-03 v8）；类型路由数据层 v3.7.1 终态；未决清单：①types→席位选择的消费代码（运行仓，需机制审计）②image 双类型专项补测③hy3 code_gen 复测④候选层月度补测

## 三、请对抗席重点审计
1. 文件管理是否有"东放一个西放一个"风险：三处归属（UI 仓/机制仓/工作区）边界是否清晰、是否有重复与漂移风险？
2. 规范完备性：生成规范 v1 + token.json 是否足以让其他窗口/模型复刻同风格？
3. 回链有效性：meta.json 的 origin_eval 是否足以溯源？
4. 遗漏检査：决策人两点需求是否全部覆盖，有无未落实项？

输出格式：结论（放行/退回）→ 问题点清单（P0/P1/P2）→ 分歧点（如有）。
