#!/usr/bin/env bash
# sync-local.sh v2 — sanjiu-core 机制同步与产物生成（2026-09-02，红线 12 v2：一处事实源+版本锚定）
# 用法：bash sync-local.sh [--check]
#   默认：拉取 sanjiu-core → 生成工作区产物（AGENTS.md + 运行位文件）→ 锚定校验
#   --check：仅校验（不生成），供 selfcheck/开工检查调用
# 退出码：0=一致；1=校验失败/缺失（禁止开工）；2=机制仓缺失
set -uo pipefail

WS="$HOME/codex-workspace"
CORE="$WS/00_global-shared/mechanisms/sanjiu-core"
EEP_TOOLS="$WS/00_global-shared/tools/eep-tools"
WS_AGENTS="$WS/AGENTS.md"
FAIL=0

header_version() {  # 从产物头部提取锚定版本
  head -3 "$1" 2>/dev/null | grep -o 'sanjiu-core@v[^ ]*' | head -1 | sed 's/sanjiu-core@//'
}

core_head() {  # 机制仓最新 tag（含 commit 短哈希）
  git -C "$CORE" describe --tags --abbrev=7 2>/dev/null
}

# ---- 备份保留策略（2026-09-18 三审九方 combo A 定稿：KEEP_BAKS 硬上限 + 溢出归档）----
# 原实现为裸 cp 且无上限，工作区根因此堆积 25 个 AGENTS.md.bak-*（1.5M）。
KEEP_BAKS="${KEEP_BAKS:-5}"
BAK_ARCHIVE_ROOT="$WS/03_codex-archive/bak-archive"

backup_target() {  # $1=待备份文件 $2=标记(可空)；产出 <name>.bak-<mark><ts>-<pid>，超出上限者入归档区
  local target="$1" mark="${2:-}" dir base stamp pattern n overflow dest
  [ -f "$target" ] || return 0
  dir=$(dirname "$target"); base=$(basename "$target")
  stamp=$(date +%Y%m%d-%H%M%S)-$$
  cp -p "$target" "$target.bak-${mark}${stamp}" 2>/dev/null || return 0
  pattern="$base.bak-${mark}*"
  n=$(find "$dir" -maxdepth 1 -type f -name "$pattern" 2>/dev/null | wc -l | tr -d ' ')
  overflow=$((n - KEEP_BAKS))
  [ "$overflow" -gt 0 ] || return 0
  case "$base" in
    AGENTS.md) dest="$BAK_ARCHIVE_ROOT/AGENTS.md" ;;
    *)         dest="$BAK_ARCHIVE_ROOT/misc" ;;
  esac
  mkdir -p "$dest"
  find "$dir" -maxdepth 1 -type f -name "$pattern" 2>/dev/null | sort | head -n "$overflow" | \
    while IFS= read -r old; do
      rel=$(printf '%s' "$old" | sed "s|^$WS/||; s|/|__|g")
      mv "$old" "$dest/$rel" 2>/dev/null || true
    done
  return 0
}

# ---- 0. 机制仓存在性 ----
if [ ! -d "$CORE/.git" ]; then
  echo "  ✗ sanjiu-core 机制仓缺失（${CORE}）——新机请先 clone codex-agents 并执行 bootstrap.sh"; exit 2
fi

# ---- 1. 拉取最新 tag（网络失败降级本地 tag 并告警）----
if ! git -C "$CORE" fetch --tags --quiet 2>/dev/null; then
  echo "  ⚠ sanjiu-core fetch 失败（离线？），使用本地 tag 校验（告警：团队公告渠道 sync-mismatch）" >&2
fi
CORE_VER=$(core_head)
[ -z "$CORE_VER" ] && { echo "  ✗ sanjiu-core 无 tag（应打 vX.Y.Z）"; exit 1; }

# ---- 2. 生成产物模式 ----
if [ "${1:-}" != "--check" ]; then
  # 2a. 工作区根 AGENTS.md = 版本头 + 机制全文
  NEW="$WS_AGENTS.new"
  {
    echo "<!-- AUTO-GENERATED from sanjiu-core@${CORE_VER} — DO NOT EDIT BY HAND; run sync-local.sh to regenerate -->"
    cat "$CORE/AGENTS.md"
  } > "$NEW"
  if [ -f "$WS_AGENTS" ] && diff -q "$NEW" "$WS_AGENTS" >/dev/null 2>&1; then
    rm -f "$NEW"; echo "  ✓ 工作区 AGENTS.md 已是最新产物（${CORE_VER}）"
  else
    [ -f "$WS_AGENTS" ] && backup_target "$WS_AGENTS"
    mv "$NEW" "$WS_AGENTS"; echo "  ✓ 工作区 AGENTS.md 已生成（${CORE_VER}，旧版已备份）"
  fi
  # 2b. 运行位文件拉取（yaml/ledger/selfcheck/bridge_core）
  for f in sanjiu-models.yaml errors-ledger.jsonl sanjiu-selfcheck.sh bridge_core.py; do
    if ! diff -q "$CORE/tools/$f" "$EEP_TOOLS/$f" >/dev/null 2>&1; then
      backup_target "$EEP_TOOLS/$f" "sync-"
      cp "$CORE/tools/$f" "$EEP_TOOLS/$f" && echo "  ✓ 运行位 tools/$f 已更新（旧版备份）"
    else
      echo "  ✓ 运行位 tools/$f 一致"
    fi
  done
  # 2b2. 立案庭运行位拉取（court 权威：route_task.py + routing_rules.yaml + flow_gate.py + schemas/；2026-09-29 状态机 v0 入同步清单）
  for f in route_task.py routing_rules.yaml flow_gate.py lead_dispatch.py; do
    if ! diff -q "$CORE/tools/court/$f" "$EEP_TOOLS/$f" >/dev/null 2>&1; then
      backup_target "$EEP_TOOLS/$f" "sync-"
      cp "$CORE/tools/court/$f" "$EEP_TOOLS/$f" && echo "  ✓ 运行位 court/$f 已更新（旧版备份）"
    else
      echo "  ✓ 运行位 court/$f 一致"
    fi
  done
  # 2b3. 流转状态机 schemas 目录同步（2026-09-29）
  if [ -d "$CORE/tools/court/schemas" ]; then
    mkdir -p "$EEP_TOOLS/schemas"
    cp -p "$CORE/tools/court/schemas/"*.json "$EEP_TOOLS/schemas/" && echo "  ✓ 运行位 schemas/ 已更新"
  fi
  # 2c. 机制 skill 同步（retrospect）
  mkdir -p "$HOME/.agents/skills"
  if [ -d "$CORE/tools/skills/retrospect" ] && ! diff -q "$CORE/tools/skills/retrospect/SKILL.md" "$HOME/.agents/skills/retrospect/SKILL.md" >/dev/null 2>&1; then
    rm -rf "$HOME/.agents/skills/retrospect"; cp -r "$CORE/tools/skills/retrospect" "$HOME/.agents/skills/retrospect"
    echo "  ✓ 机制 skill retrospect 已同步"
  else
    echo "  ✓ 机制 skill retrospect 一致"
  fi
fi

# ---- 3. 锚定校验（--check 与生成后均执行）----
ANCHOR=$(header_version "$WS_AGENTS")
if [ -z "$ANCHOR" ]; then
  echo "  ✗ 工作区 AGENTS.md 缺版本锚头（应为 AUTO-GENERATED from sanjiu-core@vX.Y.Z）"; FAIL=1
elif [ "$ANCHOR" != "$CORE_VER" ]; then
  echo "  ✗ 锚定不匹配：工作区 ${ANCHOR} vs 机制仓 ${CORE_VER} —— 请跑 sync-local.sh 重新生成（告警：团队公告渠道 sync-mismatch）"; FAIL=1
else
  echo "  ✓ 锚定一致：${ANCHOR}"
fi
# 脏工作区检查（机制仓有未提交改动 = 事实源不干净，禁止开工）
if [ -n "$(git -C "$CORE" status --porcelain 2>/dev/null)" ]; then
  echo "  ✗ sanjiu-core 有未提交改动（事实源不干净），提交或 stash 后再开工"; FAIL=1
fi

# ---- 4. 项目级机制映射检查（2026-09-03 §十一 规则；缺映射提示，不自动改项目仓库）----
echo "== 项目机制映射（sanjiu-core 唯一事实源）=="
for d in "$WS"/01_projects/*/; do
  pf="$d/AGENTS.md"
  [ -f "$pf" ] || continue
  if head -6 "$pf" | grep -q "sanjiu-core"; then
    echo "  ✓ $(basename "$d") 已映射"
  fi
  PROJECT_EXCEPTIONS=${PROJECT_EXCEPTIONS:-business-repos}
  if [ -n "$PROJECT_EXCEPTIONS" ] && echo "$PROJECT_EXCEPTIONS" | grep -qFx "$(basename "$d")"; then  # 业务仓例外（配置项 PROJECT_EXCEPTIONS）
    echo "  ○ 业务仓独立分叉（项目声明，不随 sanjiu-core 自动同步——知悉例外）"
  else
    echo "  ⚠ $(basename "$d") 缺机制映射头（建议注入 MECH-MAP 引用或删除旧机制全文副本）"
  fi
done

# 2e. 机制包 14（人工纠正复盘）与 AGENTS §十三 一致性（防悬空引用与多副本漂移）
if [ -x "$CORE/tools/check-correction-log-sync.sh" ]; then
  echo "  -- 机制包 14（EEP）与 §十三 条目一致性 --"
  if ! bash "$CORE/tools/check-correction-log-sync.sh"; then
    echo "  ✗ 机制包 14 缺条目（禁止开工：把 §十三 新增条目镜像进 EEP 机制包 14）" >&2
    FAIL=1
  fi
fi

# 最终判定：显式 if 分支 —— 原写法 `[ cond ] && echo 通过 || echo 失败` 在中间插入语句后
# 会断链恒真，导致失败被静默（2026-09-15 自引入并修复：工具自身的静默失败也要防）
if [ "$FAIL" -eq 0 ]; then
  echo "== sync-local 校验全部通过 =="
  exit 0
else
  echo "== sync-local 校验失败（FAIL=1，禁止开工）=="
  exit 1
fi
