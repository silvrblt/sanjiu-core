# META-INDEX — 开源引入统一登记权威（2026-08-29 建立）

> **唯一登记权威**：所有开源对象/Skill/工具库的引入登记一律入本表（open-source-intake 关〇.5 单点登记铁律，决策人 2026-08-29 拍板方案 C）。
> 统辖全部子索引（ai-design-tools/INDEX-*.md 等历史主题索引已降级为**归档子索引**，其记录以本表为准，新对象一律只入本表）。
> 指针规约：工作区内资产 = 相对工作区根路径（/Users/sun/codex-workspace/，git 同步场景即仓库根）；全局 skill = `global-skill:<name>`；**禁止绝对路径（含 ~、/Users/...）入库**。
> 状态枚举：待定-阻塞 / 已引入 / 方法论层 / 复用既有 / 不引入。

| 对象名 | 来源 URI | 许可（核验结论） | 归属 | 状态 | 登记指针 |
|---|---|---|---|---|---|
| frontend-slides | https://github.com/zarazhangrui/frontend-slides | MIT（2026-08-29 核验） | 总库 | 已引入 | global-skill:frontend-slides |
| frontend-slides-editable | https://github.com/archlizheng/frontend-slides-editable | MIT（2026-08-29 核验） | 总库 | 已引入 | global-skill:frontend-slides-editable |
| heytea-style | https://github.com/Hchen1218/heytea-style | MIT（2026-08-29 核验） | 总库 | 已引入 | global-skill:heytea-style |
| WeMM-Embedding | https://github.com/Tencent/WeMM-Embedding | Apache-2.0（腾讯声明版，2026-08-29 核验） | 总库 | 已引入（登记，不本地部署） | 04_reference-library/open-source-list/WeMM-Embedding-使用说明.md |
| gods-eye-view | https://github.com/bilawalsidhu/gods-eye-view | MIT（2026-08-29 核验）；⚠️ Google Maps key 计费 | 总库（标签 kai-osint） | 已引入（登记）；计费 key 未配置 | 04_reference-library/open-source-list/gods-eye-view-使用说明.md |
| HunyuanOCR | https://github.com/Tencent-Hunyuan/HunyuanOCR | 腾讯社区许可（自定义，地域限制 EU/UK/KR，2026-08-29 核验）；境内可用分发带 Notice | 总库 | 已引入（登记）；⚠️ 待决策人知悉确权 | 04_reference-library/open-source-list/HunyuanOCR-使用说明.md |
| guizang-ppt-skill | https://github.com/op7418/guizang-ppt-skill | AGPL-3.0 ⛔ | 方法论层 | 不引入代码 | 04_reference-library/open-source-list/批量审查报告-2026-08-29-归属识别与13条引入.md |
| wyckoff-trading-agent | https://github.com/YoungCan-Wang/WyckoffTradingAgent | AGPL-3.0 ⛔（GitHub API 确认） | 方法论层（交易项目） | 不引入代码 | 01_projects/learning-quantitative-trading/docs/assets/open-source-list/finance-tools-2026-08-27.md |
| factor-optimize（quantskills 系） | https://github.com/quantskills | GPL-3.0/无 LICENSE ⛔ | 方法论层（交易项目） | 不引入代码 | 01_projects/learning-quantitative-trading/docs/assets/open-source-list/finance-tools-2026-08-27.md |
| indicator（候选 B：YFOOOO/financial_agent） | https://github.com/YFOOOO/financial_agent（technical-indicators） | 无 LICENSE ⛔（本地+API 双确认） | 方法论层（交易项目）；**决策人 2026-08-29 指认候选 B（中文 talib 版，更适配 A 股）** | 不引入代码 | 01_projects/learning-quantitative-trading/docs/assets/open-source-list/finance-tools-2026-08-27.md |
| opensquilla | https://github.com/opensquilla/opensquilla | Apache-2.0（2026-08-29 核验） | 总库（重合闭环） | 复用既有（token-saviour）；借鉴 SquillaRouter 路由思想 | global-skill:token-saviour |
| personal-homepage-skill | https://github.com/powerycy/personal-homepage-skill | Non-Commercial ⛔（商用需书面许可） | 方法论层（**决策人 2026-08-29 拍板：不引入代码，按方法论层**） | 不引入代码 | 04_reference-library/open-source-list/批量审查报告-2026-08-29-归属识别与13条引入.md |
| 组合工作流（guizang→slides→editable） | 随 frontend-slides 等 | 随所属对象 | 不单独登记 | 随 2/3/4 使用说明记录 | — |

## 2026-08-30 第三轮 9 条（审查报告：批量审查报告-2026-08-30-第三轮9条.md v3.1，Hy3 三审放行附条件→补正完成）

| 对象名 | 来源 URI | 许可（核验结论） | 归属 | 状态 | 登记指针 |
|---|---|---|---|---|---|
| guard-skills | https://github.com/amElnagdy/guard-skills | MIT（2026-08-30 核验） | 总库 | 已引入（commit ffa2603 锁定，K2.7 裁决执行；触发规则 TRIGGER-RULES.md） | global-skill:guard-skills |
| awesome-agent-skills | https://github.com/JackyST0/awesome-agent-skills | CC0-1.0（2026-08-30 核验） | 总库 | 已引入（登记） | 04_reference-library/awesome-agent-skills/ |
| emilkowalski-skills（选录 4） | https://github.com/emilkowalski/skills | MIT（2026-08-30 核验） | 总库 | 已引入（reference_only，commit d23d7f8 锁定，K2.7 裁决执行） | 04_reference-library/ai-design-tools/emilkowalski-skills/ |
| MOSS-TTS-Nano | https://github.com/OpenMOSS/MOSS-TTS-Nano | Apache-2.0（代码+HF Model Card 已核；权重全栈 LICENSE 树未审） | 隔离待定池（quarantine，K2.7 裁决：不登记） | 不登记；5 项解锁条件完成后方可申请（disabled 登记+90 天复审） | 待定池记录：08_temp-work/zcode-tools-intake/audit/二审-K2.7裁决-第三轮9条-20260830.txt |
| free-claude-code | https://github.com/Alishahryar1/free-claude-code | MIT | — | 不引入（纯重合） | — |
| openhuman | https://github.com/tinyhumansai/openhuman | GPL-3.0 ⛔ | 方法论层（红线） | 不引入代码 | 方法论记录（留档隔离） |
| oh-my-hermes | https://github.com/rlaope/oh-my-hermes | MIT | 方法论层（重合） | 不引入 | 方法论记录（留档隔离） |
| perfect-image-to-code-skill | https://github.com/leonxlnx/taste-skill（skill: image-to-code-skill） | MIT（taste-skill LICENSE 双证据） | 复用不引入 | 已装 image-to-code-skill（SHA-256 全匹配） | global-skill:image-to-code-skill |
| OxshugO | 未识别（GitHub 全维度 404，模糊检索 0 合理候选） | — | 已归档（决策人 2026-08-30 拍板） | 归档关闭；后续可凭来源链接重新引入 | — |

## 2026-08-30 pentagi（第四轮单对象，Hy3 六轮收敛放行 v6）

| 对象名 | 来源 URI | 许可（核验结论） | 归属 | 状态 | 登记指针 |
|---|---|---|---|---|---|
| vxcontrol/pentagi | https://github.com/vxcontrol/pentagi | MIT + EULA（NOTICE 捆绑，冲突 MIT 优先） | 不引入（已评估） | 已归档（2026-08-30，决策人待确认；Hy3 六审放行） | 审查报告：04_reference-library/open-source-list/审查报告-2026-08-30-pentagi.md |

## 2026-08-31 第五轮 6 条（K3 三审终裁定稿，C1–C5 条件全满足）

| 对象名 | 来源 URI | 许可 | 归属/状态 | 处置 | 登记指针 |
|---|---|---|---|---|---|
| tt-a1i/archify | https://github.com/tt-a1i/archify | MIT | 已审复用 | 复用（基线 72 文件 SHA-256，月度核对上游） | global-skill:archify |
| HKUDS/CLI-Anything | https://github.com/HKUDS/CLI-Anything | Apache-2.0 | 概念参考 | 不引入（registry 设计要点入方法论，POC 独立编写） | 方法论-2026-08-30.md |
| Graphify-Labs/graphify | https://github.com/Graphify-Labs/graphify | Apache-2.0 | 已决不引入.冻结候选 | FROZEN（解锁条件：验签/NOTICE/MIT 保留） | check-intake-status.py 登记 |
| colbymchenry/codegraph | https://github.com/colbymchenry/codegraph | MIT | 已决不引入.冻结候选 | FROZEN（同上） | check-intake-status.py 登记 |
| headroomlabs-ai/headroom | https://github.com/headroomlabs-ai/headroom | Apache-2.0 | 已决不引入.冻结候选 | FROZEN（解冻前置：pip-audit 清白+沙箱+压测+命中源审计已完） | check-intake-status.py 登记 |
| DeusData/codebase-memory-mcp | https://github.com/DeusData/codebase-memory-mcp | MIT | REJECTED | 硬拒（1.3G+网络面，无解锁路径） | check-intake-status.py 登记 |

## 2026-08-31 第六轮 13 条（M3 应急终裁附条件同意，条件 A/B 已落实）

| 对象名 | 来源 URI | 许可 | 归属/状态 | 处置 | 登记指针 |
|---|---|---|---|---|---|
| s1dashu/ip-as-logo-skill | https://github.com/s1dashu/ip-as-logo-skill | MIT | 已引入（2026-08-31 全链路通过：fetch hash_ok/observe hits=0/重叠率<20%） | 已装 ~/.agents/skills/ip-as-logo-skill（5 文件哈希校验一致）；ui-design 内容图分支 | global-skill:ip-as-logo-skill |
| unclecode/crawl4ai | https://github.com/unclecode/crawl4ai | Apache-2.0 | pending | API 核验+沙箱观测+依赖审计齐备后评估 | — |
| JuliusBrussee/caveman | https://github.com/JuliusBrussee/caveman | skill: MIT / engine: BSL-1.1 | 代码不引入+方法论登记 | engine 层零接触（BSL 剥离验证） | 方法论记录（原始人语法） |
| santifer/career-ops | https://github.com/santifer/career-ops | MIT | 不引入 | ai-job-search 先例同判（三维比对已附） | — |
| MemPalace/mempalace | https://github.com/MemPalace/mempalace | MIT | 参考库登记 | 登记不部署（记忆体系演进候选） | 04_reference-library/ |
| mvanhorn/last30days-skill | https://github.com/mvanhorn/last30days-skill | MIT | 已收录复用 | 索引 §四 已收录 | INDEX-2026-08-25 |
| anti-ui-slop | 未定位（非 GitHub 对象） | pending_verification | **已归档**（决策人 2026-08-31 拍板） | 归档拒绝；凭来源链接可重新引入 | 无效来源黑名单 |
| web-design-guidelines | 未定位（非 GitHub 对象） | pending_verification | **已归档**（决策人 2026-08-31 拍板） | 归档拒绝；凭来源链接可重新引入 | 无效来源黑名单 |
| design-taste-frontend 等 5 项 | 已装/已评估 | Duplicated | 查重拦截 | 已装（taste/soft/redesign-skill）或已评估不装 | global-skill 对应 |
