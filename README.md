# sanjiu-core — 三审九方机制唯一事实源

> v1.0.0（2026-09-02）| 依据：需求文档 v3 三审终裁（方案 B）+ 老板 4 项拍板
> 层级：**宪法层**（老板拍板/红线，AGENTS.md 内）→ **机制层**（本仓：AGENTS.md 机制全文 + MECH-xx + yaml + errors-ledger）→ **执行层**（bridge_core/CLI）→ **项目层**（各工作区 AGENTS.md = 本仓生成产物）

## 内容

| 路径 | 说明 |
|---|---|
| `AGENTS.md` | 三审九方机制全文（唯一事实源；各工作区根 AGENTS.md 由本文件生成） |
| `docs/MECH-*.md` | 编号机制文件（08 E2E / 08b 可运行性 / 09 输出治理与复盘）；MECH-05/06 在 EEP 服务器侧，待迁移 |
| `docs/OPEN-SOURCE-META-INDEX.md` | 开源引入索引副本（代码本体在 04_reference-library，不入本仓） |
| `tools/sanjiu-models.yaml` | 九方席位/价格/调度唯一事实源 |
| `tools/errors-ledger.jsonl` | 错误模式库（MECH-09，双控更新） |
| `tools/bridge_core.py` | 桥接内核（审计调用统一入口：输出约束/错误注入/Q-EX0） |
| `tools/sanjiu-selfcheck.sh` | 开工自检（含锚定校验，缺失禁止开工） |
| `tools/skills/` | 机制 skill（retrospect 复盘等；通用 skill 在 silvrblt/agents-skills 仓） |
| `schema/` | 数据文件 JSON Schema（API 化预留） |

## 版本化与变更纪律

1. 机制修改 = 本仓 PR（分支纪律，禁直推 main）→ 合入 → **打 tag**（vX.Y.Z 语义版本）；
2. 各工作区运行 `sync-local.sh` 拉取生成产物，头部版本锚定；
3. 红线 12（v2 生效）：一处事实源 + 四处版本锚定 + selfcheck 校验（替代旧"五处全文 grep"）；
4. errors-ledger 更新走 MECH-09 双控（提报 → 对抗复核 → decision.jsonl → ledger + 哈希）。

## 新机接入

```
git clone git@github.com:silvrblt/codex-agents.git   # 引导仓（配置/提示词/环境变量清单）
bash codex-agents/bootstrap.sh                        # 拉取本仓 + 生成各工作区产物 + selfcheck
```
