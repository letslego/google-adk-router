#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
export MEMORYLAYER_EMBEDDING_PROVIDER=hash
export MEMORYLAYER_ENRICHMENT_POLICY=deterministic
export MEMORYLAYER_SESSION_SERVICE=persistent
export MEMORYLAYER_SQLITE_STORAGE_PATH="$PROJECT_DIR/.adk/memorylayer.sqlite3"
exec .memorylayer-server-venv/bin/memorylayer serve --host 127.0.0.1 --port 61001
