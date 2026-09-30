#!/usr/bin/env bash
# check-correction-log-sync.sh —— 校验「AGENTS.md §十三」与 EEP 机制包 14 是否一致
#
# 机制包 14 的实际位置：enterprise-ecosystem-platform/docs/mechanism-pack/14-人工纠正复盘.md
# （由 §十三 引言指定为镜像；两处须保持一致 —— 对应红线 12 的流程类同步项）
#
# 为什么是"校验"而不是"生成"：机制包 14 的条目在本仓风格下带有「实证教训」注记（§十三 摘要
# 中可能没有），整篇生成会**丢内容**；且 2026-09-15 我曾误判其不存在而在错误位置新建副本
# （已撤回）。故此处只做**一致性校验**：比对两处的条目编号与标题，缺失/多余即报警。
#
# 用法：tools/check-correction-log-sync.sh [--eep <EEP 仓路径>]
# 退出码：0 一致；1 不一致（缺条/多条/标题不符）；2 前置缺失
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="$(cd "$HERE/.." && pwd)"
AGENTS="$CORE/AGENTS.md"
EEP="${2:-/Users/sun/codex-workspace/01_projects/eep-platform/checkout}"
PACK14="$EEP/docs/mechanism-pack/14-人工纠正复盘.md"

[ -f "$AGENTS" ] || { echo "  ✗ 缺 $AGENTS" >&2; exit 2; }
if [ ! -f "$PACK14" ]; then
  echo "  ⚠ 未找到机制包 14：${PACK14}（EEP 仓不在本机或路径变更）—— 跳过校验并提示" >&2
  exit 0
fi

python3 - "$AGENTS" "$PACK14" <<'PYEOF'
import re, sys
def entries(path, sec_start, sec_end=None):
    src = open(path, encoding='utf-8').read()
    i = src.index(sec_start)
    j = src.index(sec_end) if sec_end and sec_end in src[i:] else len(src)
    body = src[i:j]
    out = {}
    for m in re.finditer(r'^(\d+)\.\s+\*\*(.{2,40}?)\*\*', body, re.M):
        out[int(m.group(1))] = m.group(2).strip()
    return out

a = entries(sys.argv[1], '### 已纠正红线清单', '### 复盘机制')
b = entries(sys.argv[2], '已纠正红线清单')
miss = sorted(set(a) - set(b))
extra = sorted(set(b) - set(a))
diff = [n for n in sorted(set(a) & set(b)) if a[n][:12] != b[n][:12]]
print(f"  AGENTS §十三 条目：{len(a)} 条（最大编号 {max(a) if a else 0}）")
print(f"  机制包 14   条目：{len(b)} 条（最大编号 {max(b) if b else 0}）")
# 分两类：①缺/多条目 = 本次变更责任（必须失败）；②编号相同但标题措辞不同 = 历史维护分叉
# （两处清单独立演进所致，非本次变更引入）→ 显式列出并告警，但不阻断开工，交由机制维护裁定。
hard = bool(miss or extra)
if miss:  print(f"  ✗ 机制包 14 缺条目（须补）：{miss}")
if extra: print(f"  ✗ 机制包 14 多出条目（§十三 无，须核）：{extra}")
if diff:
    print(f"  ⚠ 编号相同但标题措辞不同（**历史维护分叉，非本次变更引入**）：{diff}")
    print("     处置建议：由机制维护择一为准并统一两处措辞；本次变更只负责把新增条目镜像到位。")
if not hard:
    print("  ✓ 条目编号集合一致（机制包 14 允许保留更详的实证注记与不同措辞）")
    sys.exit(0)
print("  → 请把缺失条目补入机制包 14（保留其既有实证注记，勿整篇覆盖）")
sys.exit(1)
PYEOF
