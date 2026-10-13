#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
if [ ! -x .venv/bin/adk ]; then
  echo 'Run scripts/setup.sh first.' >&2
  exit 1
fi
.venv/bin/python scripts/check_config.py
export MEMORY_BACKEND="${MEMORY_BACKEND:-memlayer}"
export MEMLAYER_URL="${MEMLAYER_URL:-http://127.0.0.1:61002}"
export MEMORYLAYER_URL="${MEMORYLAYER_URL:-http://127.0.0.1:61001}"
exec .venv/bin/python server.py
