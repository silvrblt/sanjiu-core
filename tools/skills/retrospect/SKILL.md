---
name: retrospect
description: 任务结项复盘——错误模式归类计数、≥2 次固化纪律提报（三审 Qwen 终裁方案 C 的复盘流程层，2026-09-02 生效）
metadata:
  skill-version: 1.0
---

# Skill: retrospect（任务结项复盘）

**触发（强制门禁）**：任务 done 前必须执行本复盘并产出 retrospect_ref（任务台账/决策台账引用）；无复盘记录任务不得进入完成态（三审终裁第 4 条）。月度 03:00 复盘时对本月全部任务批量补跑。

## 流程（五步，产出 ≤1000 token）

1. **收集**：列本任务全部已发现问题（对抗审计退回项 + 老板纠正项 + 自查发现项），逐条一句话；
2. **归类**：对照 `00_global-shared/tools/eep-tools/errors-ledger.jsonl` 现有模式——命中则该条 count+1（提报计数）；未命中且问题可能复发 → 提报新模式候选；
3. **归因**：每个问题标注根因类型（实体知识漏洞 / 程序流程漏洞 / 工具缺陷 / 表述失误）；
4. **提报**：计数变更与新候选写入 `docs/ledger/decision.jsonl`（decision-log.sh 或直接追加），**禁止直接改 errors-ledger.jsonl**（双控：对抗席复核后才由维护动作更新 ledger + 哈希）；
5. **固化建议**：某模式 count 达 ≥2 时，在提报中附「建议固化纪律」一句话（将进 AGENTS.md 十三 / 验收清单 / 注入清单）。

## 提报格式（decision.jsonl 一行）

```json
{"at":"<ISO>","who":"retrospect","decision":"retrospect:<任务id> PM-6+1 | 新候选 PM-9 <模式名>（<一句话>，建议固化：<纪律>）","basis":"<问题清单引用>","ref":"<任务/审计证据路径>"}
```

## 纪律

- 只归类不辩解；同一事件不得重复计数（绑定问题编号去重）；
- 已固化模式（solidified）复发 → 提报"复活"（count+2、severity 升级）；
- 本 skill 不改代码、不改 ledger 文件本体——只提报，更新走对抗复核。
