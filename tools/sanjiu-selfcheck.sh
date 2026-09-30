#!/usr/bin/env bash
# 三审九方开工前自检（零依赖）：工具链 + 密钥 + 席位配置一致性（红线 #12 运行侧）
# 用法：bash tools/sanjiu-selfcheck.sh
set -uo pipefail

FAIL=0
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== 工具链 =="
for c in hunyuan-audit glm-audit kimi doubao-audit minimax-audit qwen-text-audit sanjiu_cli.py deepseek-audit qwen-vision glm-image qwen-image; do
  if command -v "$c" >/dev/null 2>&1; then
    echo "  ✓ $c"
  else
    echo "  ✗ $c 缺失"
    FAIL=1
  fi
done

echo "== 密钥（仅检查是否设置，不显示值）=="
for v in HUNYUAN_API_KEY GLM_API_KEY MOONSHOT_API_KEY QWEN_API_KEY ARK_API_KEY MINIMAX_API_KEY DEEPSEEK_API_KEY; do
  if [ -n "${!v:-}" ]; then
    echo "  ✓ $v"
  else
    echo "  ✗ $v 未配置（可回落 ~/.env）"
    FAIL=1
  fi
done

echo "== 席位配置（tools/sanjiu-models.yaml）=="
if [ -f "$REPO_ROOT/eep-tools/sanjiu-models.yaml" ]; then
  grep -q "deepseek-v4-flash" "$REPO_ROOT/eep-tools/sanjiu-models.yaml" && echo "  ✓ l1_lead" || { echo "  ✗ l1_lead"; FAIL=1; }
  grep -q "hunyuan-hy3" "$REPO_ROOT/eep-tools/sanjiu-models.yaml" && echo "  ✓ l1_antagonist" || { echo "  ✗ l1_antagonist"; FAIL=1; }
  grep -q "deepseek-audit" "$REPO_ROOT/eep-tools/sanjiu-models.yaml" && echo "  ✓ l1_judge(deepseek-audit)" || { echo "  ✗ l1_judge"; FAIL=1; }
  grep -q "qwen-vl-plus" "$REPO_ROOT/eep-tools/sanjiu-models.yaml" && echo "  ✓ vision_read(qwen-vl-plus)" || { echo "  ✗ vision_read"; FAIL=1; }
  grep -q "cogview-4" "$REPO_ROOT/eep-tools/sanjiu-models.yaml" && echo "  ✓ image_gen(cogview-4)" || { echo "  ✗ image_gen"; FAIL=1; }
else
  echo "  ✗ sanjiu-models.yaml 缺失"
  FAIL=1
fi

echo "== 机制文档一致性（红线 #12：yaml ↔ AGENTS.md ↔ 机制包）=="
WS_AGENTS="/Users/sun/codex-workspace/AGENTS.md"
EEP_DOCS="/Users/sun/codex-workspace/01_projects/eep-platform/checkout/docs/mechanism-pack"
if grep -q "cogview-4" "$WS_AGENTS" 2>/dev/null; then
  echo "  ✓ AGENTS.md 含 image_gen(cogview-4)"
else
  echo "  ✗ AGENTS.md 缺 image_gen(cogview-4)"; FAIL=1
fi
if grep -q "glm-image" "$EEP_DOCS/15-AGENTS规范-v7.2-2026-08-15.md" 2>/dev/null; then
  echo "  ✓ 机制包15 含 glm-image"
else
  echo "  ✗ 机制包15 缺 glm-image"; FAIL=1
fi
if grep -q "读图再验收" "$EEP_DOCS/16-审计对象与依据标准-执行细则.md" 2>/dev/null; then
  echo "  ✓ 机制包16 含 读图再验收"
else
  echo "  ✗ 机制包16 缺 读图再验收"; FAIL=1
fi
VIS_OK=1
# 视觉验收流 v1 字段级断言：4 副本须同时含「视觉验收流 v1」+「裁决链」（不进三审
# 裁决链的边界）+「L3」（三级契约核心）。工作区副本（fip-1-2-3/work）为开发产物，
# 显式豁免出本断言（见审计报告 2026-08-15 视觉验收流 §六 说明）。
for f in "$WS_AGENTS" "$EEP_DOCS/07-API配置与九方模型清单.md" "$EEP_DOCS/15-AGENTS规范-v7.2-2026-08-15.md" "$EEP_DOCS/16-审计对象与依据标准-执行细则.md"; do
  grep -q "视觉验收流 v1" "$f" 2>/dev/null || { echo "  ✗ $f 缺 视觉验收流 v1"; VIS_OK=0; }
  grep -q "裁决链" "$f" 2>/dev/null || { echo "  ✗ $f 缺 裁决链 边界"; VIS_OK=0; }
  grep -q "L3" "$f" 2>/dev/null || { echo "  ✗ $f 缺 L3 契约"; VIS_OK=0; }
done
if [ "$VIS_OK" -eq 1 ]; then
  echo "  ✓ 视觉验收流 v1 四处一致（AGENTS.md ↔ 机制包 07/15/16）"
else
  FAIL=1
fi

echo "== 机制锚定校验（sanjiu-core 事实源，红线 12 v2：一处事实源+版本锚定）=="
CORE_DIR="$HOME/codex-workspace/00_global-shared/mechanisms/sanjiu-core"
if [ -f "$CORE_DIR/tools/sync-local.sh" ]; then
  if bash "$CORE_DIR/tools/sync-local.sh" --check >/tmp/sync-check.log 2>&1; then
    echo "  ✓ sanjiu-core 锚定一致（$(grep -o '锚定一致.*' /tmp/sync-check.log | head -1)）"
  else
    echo "  ✗ sanjiu-core 锚定校验失败（详见 /tmp/sync-check.log）——跑 sync-local.sh 重新生成"; FAIL=1
  fi
else
  echo "  ✗ sanjiu-core 机制仓缺失（bootstrap.sh 未跑？）"; FAIL=1
fi

echo "== 输出治理 + 复盘改进机制（MECH-09，2026-09-02 三审终裁方案 C）=="
# 机制存在性校验（缺失禁止开工）：AGENTS.md 条款 + ledger 文件 + bridge_core 注入实现
if grep -q "输出硬约束" "$WS_AGENTS" 2>/dev/null && grep -q "复盘门禁" "$WS_AGENTS" 2>/dev/null; then
  echo "  ✓ AGENTS.md 含 输出硬约束 + 复盘门禁（§十·四）"
else
  echo "  ✗ AGENTS.md 缺 §十·四 条款（输出治理/复盘机制）"; FAIL=1
fi
if [ -f "$REPO_ROOT/eep-tools/errors-ledger.jsonl" ]; then
  _n=$(grep -c '"id"' "$REPO_ROOT/eep-tools/errors-ledger.jsonl" 2>/dev/null || echo 0)
  echo "  ✓ errors-ledger.jsonl 存在（${_n} 模式）"
else
  echo "  ✗ errors-ledger.jsonl 缺失"; FAIL=1
fi
if grep -q "_build_system_prompt" "$REPO_ROOT/eep-tools/bridge_core.py" 2>/dev/null; then
  echo "  ✓ bridge_core 含错误模式注入实现"
else
  echo "  ✗ bridge_core 缺注入实现（_build_system_prompt）"; FAIL=1
fi

echo "== 桥接内核单一实现 + yaml 调度配置（2026-08-31 换芯，R10 去漂移防分叉）=="
if [ -f "$REPO_ROOT/eep-tools/bridge_core.py" ]; then
  echo "  ✓ bridge_core.py 存在"
else
  echo "  ✗ bridge_core.py 缺失"; FAIL=1
fi
for c in hunyuan_audit.py glm_audit.py sanjiu_cli.py deepseek_audit.py; do
  if grep -q "from bridge_core import main" "$REPO_ROOT/$([ -f "$REPO_ROOT/eep-tools/$c" ] && echo "eep-tools/$c" || echo "codex-tools/kimi-bridge/$c")" 2>/dev/null; then
    echo "  ✓ $c 已换芯（bridge_core 转发）"
  else
    echo "  ✗ $c 未换芯（同源分叉风险）"; FAIL=1
  fi
done
grep -q "import bridge_core" "$REPO_ROOT/codex-tools/kimi-bridge/kimi.py" 2>/dev/null && echo "  ✓ kimi.py audit 已转发 bridge_core" || { echo "  ✗ kimi.py 未转发"; FAIL=1; }
if grep -q "bridge: {ttft" "$REPO_ROOT/eep-tools/sanjiu-models.yaml"; then
  echo "  ✓ yaml 席位 bridge 调度配置存在"
else
  echo "  ✗ yaml 缺 bridge 调度配置"; FAIL=1
fi

echo "== 下一迭代强制跟踪（一审裁决登记，显式清单）=="
echo "  ⚠ FIP06-T1 双时间窗滑块（设计态未实施，关闭需 DOM/截图证据）"
echo "  ⚠ FIP06-T2 git hook 自动读图（设计态未实施，关闭需 hook+selfcheck 状态）"
echo "  ⚠ FIP06-T3 P1-3 生产真实重算（演示降级放行，关闭需引擎环境端到端证据）"
echo "  ✓ FIP06-T4 DEMO_ONLY 物理隔离（已实现，回归证据见 console tests/auth.test.ts）"

if [ "$FAIL" -eq 0 ]; then
  echo "自检通过"
else
  echo "自检失败：补齐上述缺项后再开工"
  exit 1
fi
