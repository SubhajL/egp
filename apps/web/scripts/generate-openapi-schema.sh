#!/bin/sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$WEB_ROOT/../.." && pwd)"

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON:-python}"
fi

"$PYTHON_BIN" "$REPO_ROOT/scripts/export_openapi_schema.py" \
  --output "$WEB_ROOT/src/lib/generated/openapi.json"
