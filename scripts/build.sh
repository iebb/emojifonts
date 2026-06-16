#!/usr/bin/env bash
# Build one or more sets individually, e.g.:
#   scripts/build.sh twemoji
#   scripts/build.sh noto blobmoji
#   scripts/build.sh            # (no args) → list sets
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$HERE/.venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$HERE/requirements.txt"
export PATH="$VENV/bin:$PATH"        # so nanoemoji's picosvg/ninja resolve
if [ "$#" -eq 0 ]; then
  "$VENV/bin/python" -c "import json;print('sets:',' '.join(json.load(open('$HERE/sources.json'))))"
  exit 0
fi
"$VENV/bin/python" "$HERE/build.py" build "$@"
echo "→ dist/"
