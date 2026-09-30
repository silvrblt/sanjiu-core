# flow_gate 用例清单（输入/期望/实际，K3 终局裁决物化条件）

| # | 用例 | 输入 | 期望 | 实际（2026-09-29 运行，sha 4764a7f2bbfbfa02） |
|---|---|---|---|---|
| 1 | lead_package 完整通过 | 全字段承办方案包 | ok=True | PASS |
| 2 | lead_package 缺 user_quote 拒绝 | 去 user_quote | FLOW_ERR_SCHEMA | PASS |
| 3 | appeal_package 通过 | 背景+异议包 | ok=True | PASS |
| 4 | appeal 带全量上下文拒绝 | +full_context | FLOW_ERR_SCHEMA | PASS |
| 5 | audit_package 修订版方案包通过 | verdict=revise+revised_proposal+diff_index(全字段) | ok=True | PASS |
| 6 | audit 未返还承办拒绝 | returned_to_lead=False | FLOW_ERR_SCHEMA | PASS |
| 7 | audit 缺修订版方案拒绝 | 去 revised_proposal | FLOW_ERR_SCHEMA | PASS |
| 8 | judge_input 四字段通过 | 四字段裁决输入包 | ok=True | PASS |
| 9 | final_package 通过 | 四字段终判包 | ok=True | PASS |
| 10 | lead_response_package 通过 | resolution+accepted+rejected(全字段) | ok=True | PASS |
| 11 | 第一轮对抗放行 | check_round 首次 | ok=True | PASS |
| 12 | 第二轮对抗熔断 | check_round 二次 | FLOW_ERR_MELTDOWN | PASS |
| 13 | 熔断态跨实例持久化 | 新 FlowGate 读状态 | meltdown 含任务 | PASS |
| 14 | 第二次上诉熔断 | appeal 二次 | FLOW_ERR_MELTDOWN | PASS |
| 15 | 合法回执通过 | 签发后 gate_check | ok=True | PASS |
| 16 | 任务卡被篡改拒绝 | 改 title 再验 | FLOW_ERR_BAD_RECEIPT | PASS |
| 17 | 无回执拒绝 | gate_check(None) | FLOW_ERR_NO_RECEIPT | PASS |
| 18 | 强制域→B | 含强制域关键词 | combo=B | PASS |
| 19 | 问答→direct | type=qa | combo=direct | PASS |
| 20 | 默认→A | 普通任务 | combo=A | PASS |
| 21 | 三选一无第四值 | 单文件bugfix | combo=A | PASS |

运行命令：`python3 tools/court/flow_gate.py --selftest`；证据 sha：4764a7f2bbfbfa02（完整输出存 merge-audit 案卷）。
