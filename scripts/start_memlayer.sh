#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
MEMLAYER_NODE="${MEMLAYER_NODE:-node}"
if ! "$MEMLAYER_NODE" -e 'const {DatabaseSync}=require("node:sqlite");const d=new DatabaseSync(":memory:");d.exec("CREATE VIRTUAL TABLE t USING fts5(text)")' >/dev/null 2>&1; then
  MEMLAYER_NODE="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
  "$MEMLAYER_NODE" -e 'const {DatabaseSync}=require("node:sqlite");const d=new DatabaseSync(":memory:");d.exec("CREATE VIRTUAL TABLE t USING fts5(text)")' >/dev/null 2>&1 || { echo 'Set MEMLAYER_NODE to Node 24 with SQLite FTS5 support.' >&2; exit 1; }
fi
exec "$MEMLAYER_NODE" --import "$PROJECT_DIR/.memlayer-source/node_modules/tsx/dist/loader.mjs" bridge/memlayer.mjs
