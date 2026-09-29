#!/usr/bin/env bash
# codex 分发冒烟证据脚本（合入审计证据物；可复现）
set -e
cd "$(dirname "$0")/.."
CARD=$(mktemp /tmp/codex_smoke_card.XXXX.json)
echo '{"title": "codex分发冒烟", "type": "text_gen"}' > "$CARD"
python3 lead_dispatch.py --combo codex --card "$CARD" --prompt "只回复一个字：好" --timeout 150 \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['mode']=='codex'; assert d['ok'] is True; print(json.dumps(d, ensure_ascii=False))"
rm -f "$CARD"
