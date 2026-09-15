#!/usr/bin/env bash
# sync-correction-log.sh —— 机制包 14「人工纠正复盘」生成与镜像（防多副本漂移）
#
# 背景：AGENTS.md §十三 第 12 条要求机制变更做一致性同步；§十三 引言要求红线清单
# 同时存在于「本文件」与「机制包 14-人工纠正复盘.md」。此前 14 号机制包**并不存在**，
# 属悬空引用（2026-09-15 机制变更审计必改项 P0-2）。
#
# 本脚本把 §十三（含管理规则 + 全量红线清单 + 复盘机制）从 AGENTS.md **抽取生成**到：
#   $CORE/docs/14-人工纠正复盘.md          ← 唯一事实源（内容由 AGENTS.md 生成，不手改）
#   $CODEX_AGENTS/docs/14-人工纠正复盘.md  ← 同哈希镜像（机制包分发用）
# 并校验两者 SHA-256 一致、打印结果；不一致即失败。**手改本文件会被下次生成覆盖**。
#
# 用法：tools/sync-correction-log.sh [--check]
#   --check：只校验（不写文件），供 sync-local / 开工自检调用
# 退出码：0 一致/已生成；1 校验失败；2 前置缺失
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="$(cd "$HERE/.." && pwd)"
CODEX_AGENTS="$(cd "$CORE/.." && pwd)/codex-agents"
AGENTS="$CORE/AGENTS.md"
SRC_OUT="$CORE/docs/14-人工纠正复盘.md"
MIRROR_OUT="$CODEX_AGENTS/docs/14-人工纠正复盘.md"
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

[ -f "$AGENTS" ] || { echo "  ✗ 缺 $AGENTS" >&2; exit 2; }
[ -d "$CODEX_AGENTS/docs" ] || { echo "  ⚠ 机制包目录不存在，跳过镜像：$CODEX_AGENTS/docs"; }

gen() {
  python3 - "$AGENTS" <<'PYEOF'
import hashlib, re, sys
src = open(sys.argv[1], encoding='utf-8').read()
start = src.index('## 十三、人工纠正复盘')
end = src.index('## 十四、')
body = src[start:end].rstrip()
sha = hashlib.sha256(src.encode('utf-8')).hexdigest()
print(f"""# 机制包 14：人工纠正复盘（既往错误红线清单）

> **本文件由 `tools/sync-correction-log.sh` 从 `AGENTS.md` §十三 自动生成，请勿手改**
> ——手改会被下次生成覆盖；修订请改 AGENTS.md §十三 后重跑本脚本。
> 生成来源：`AGENTS.md`（SHA-256 `{sha}`）｜ 生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> 管理规则：①老板人工纠正过的事项 = 最高优先级红线，必须进本清单（实体 + 程序双维度）；
> ②每条纠正按「根因（实体知识漏洞 / 程序流程漏洞 / 工具缺陷 / 表述失误）→ 整改 → 本清单追加」；
> ③新增/修订须同步 AGENTS.md §十三 与本文件（及 codex-agents 镜像），并保持 SHA-256 一致；
> ④每日 03:00 复盘与每次验收对照本清单自查；⑤机制自身查出的错误按 11-评价评分体系打分。

---

{body}
""")
PYEOF
}

if [ "$CHECK" -eq 1 ]; then
  tmp=$(mktemp); gen > "$tmp"
  fail=0
  for f in "$SRC_OUT" "$MIRROR_OUT"; do
    [ -f "$f" ] || { echo "  ✗ 缺 ${f}（跑一次 tools/sync-correction-log.sh 生成）"; fail=1; continue; }
    if diff -q "$tmp" "$f" >/dev/null 2>&1; then echo "  ✓ $(basename "$(dirname "$f")")/14-人工纠正复盘.md 与 §十三 一致"
    else echo "  ✗ $f 与 AGENTS.md §十三 不一致（内容漂移）"; fail=1; fi
  done
  rm -f "$tmp"
  exit $fail
fi

gen > "$SRC_OUT"
cp "$SRC_OUT" "$MIRROR_OUT" 2>/dev/null || true
a=$(shasum -a 256 "$SRC_OUT" | cut -d' ' -f1)
b=$([ -f "$MIRROR_OUT" ] && shasum -a 256 "$MIRROR_OUT" | cut -d' ' -f1 || echo "（无镜像）")
echo "  ✓ 已生成 $SRC_OUT"
echo "     SHA-256 ${a:0:16}…"
if [ "$b" != "（无镜像）" ]; then
  [ "$a" = "$b" ] && echo "  ✓ 镜像一致 ${MIRROR_OUT}（${b:0:16}…）" || { echo "  ✗ 镜像不一致！" >&2; exit 1; }
else
  echo "  ⚠ 未生成镜像（机制包目录缺失）"
fi
