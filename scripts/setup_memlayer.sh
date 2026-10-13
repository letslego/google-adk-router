#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
if [ ! -d .memlayer-source/.git ]; then
  gh repo clone letslego/memlayer .memlayer-source
fi
MEMLAYER_REVISION=$(.venv/bin/python -c 'import json;print(json.load(open("memlayer-dependency.json"))["commit"])')
git -C .memlayer-source fetch origin "$MEMLAYER_REVISION"
git -C .memlayer-source checkout --detach "$MEMLAYER_REVISION"
cd .memlayer-source
pnpm install --frozen-lockfile
