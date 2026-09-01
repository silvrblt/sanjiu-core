# MECH-09：输出治理与复盘改进机制（v1.0，2026-09-02 三审终裁方案 C 生效）

> 审计链：一审 Hy3（退回 4+3 全接受）→ 三审对抗 Qwen3.8 Max 终裁（方案 C + 7 落地要求）
> 老板拍板（2026-09-02）：① 输出约束落地；② 重复 ≥2 次错误固化进执行/验收纪律、落到所有模型、对抗审计额外关注；③ 复盘/反思/改进机制必须刚性落实——**机制必强制，否则等于强制没机制**。
> 关联：AGENTS.md §十·四（红线级条款）；v6.1 附录条款 4（信息传递软限）的执行化。

## 一、输出治理（工具层强制）

- 落点：`tools/eep-tools/bridge_core.py` SYSTEM 默认值（全席位生效；显式 `--system` 可覆盖，留痕）；
- 规则：结构化报告（结论 → 问题点清单 → 分歧点），总输出 ≤3000 token（逐条核验 ≤6000）；严禁推理链泄漏、复述材料、客套铺垫；每个问题点必须附可执行修改建议；无新增问题明确写"无新增问题"；
- 实证（2026-09-02）：同类复核调用 30-60s/500-800 token → 13s/~300 token，输出 token 收敛 ~60%，审计能力不削弱。

## 二、历史高频错误模式库（errors-ledger，唯一事实源）

- 文件：`tools/eep-tools/errors-ledger.jsonl`（本仓库 tools/ 同步副本；工作区 `00_global-shared/tools/eep-tools/` 为运行位）
- Schema（12 字段，缺 source_refs/evidence_hash 不得入账）：`id / title / pattern / scope / severity / count / status / source_refs / evidence_hash / decision_ref / updated_at / version`
- 状态机：active（count≥2 进注入）→ solidified（已固化，退出注入、转验收清单）→ 复发复活（count+2、severity 升级）
- 初版 7 模式（2026-09-02，统计源 = cost-opt 审计链四席问题清单 + AGENTS.md 十三历史红线）：
  PM-6 文档与实现脱节（10 次）/ PM-4 口径不一致（4）/ PM-5 验收不可核验（3）/ PM-1 证据转录失真（2）/ PM-2 无实测基线写参数（2）/ PM-3 算术口径错误（2）/ PM-7 需求原文未闭环（1，防御性）；PM-8 输出失控已固化（本机制即其固化结果）。

## 三、注入机制（工具层强制，任何会话绕不过）

- bridge_core 每次审计/裁决/承办调用自动注入：count≥2 且 active、按 count 降序 top5；
- 文案 = 只读检查项（"检查材料是否犯此模式"），**禁止可执行指令语义**（命令/URL/变量替换）；
- 附 ledger SHA-256（版本锚定）；**加载失败显式降级标记（高风险模式），禁止静默跳过**；
- 全席位含承办（自查前置）；按任务相关度过滤，无相关项注入空并记录原因，禁止全量灌输。

## 四、复盘门禁（流程纪律，红线级）

- 任务 done 前必须跑 retrospect 复盘（skill：`~/.agents/skills/retrospect/`），产出 retrospect_ref 落 decision.jsonl；**无复盘记录任务不得进入完成态**；
- 流程五步：收集问题 → 对照 ledger 归类（命中 count+1 / 新候选提报）→ 根因归因 → 双控提报 → 固化建议；
- 月度 03:00 复盘批量补跑；开工前 selfcheck 校验机制条款存在性，缺失禁止开工。

## 五、更新双控（防污染，红线）

1. 任何席位/窗口可**提报**（decision.jsonl 记录，禁止直改 ledger 文件）；
2. 对抗席复核（Hy3/二审对抗）→ 通过后由维护动作更新 ledger + 记录新旧 SHA-256；
3. 同一事件禁止重复计数（绑定问题编号去重）；月度复核：清洗、命中率统计、连续未命中降级。

## 六、固化判据（老板拍板原文纪律）

同一错误重复出现 ≥2 次 → 必须固化进执行/验收纪律；**固化 = 三层齐备**：工具注入（刚性）+ 纪律条款（AGENTS.md §十·四）+ skill（流程）；缺一即视为未固化。不只落犯错模型——所有模型经注入覆盖，对抗审计额外关注。

## 七、五处一致

本文件 ↔ AGENTS.md §十·四 ↔ bridge_core.py 实现 ↔ errors-ledger.jsonl ↔ retrospect skill；selfcheck 校验关键词：`输出硬约束 / errors-ledger / retrospect / 复盘门禁`。
