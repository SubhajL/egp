#!/bin/sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$WEB_ROOT/../.." && pwd)"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON:-python}"
fi

GENERATED_SCHEMA="$WEB_ROOT/src/lib/generated/openapi.json"
GENERATED_TYPES="$WEB_ROOT/src/lib/generated/api-types.ts"
TMP_SCHEMA="$TMP_DIR/openapi.json"
TMP_TYPES="$TMP_DIR/api-types.ts"

"$PYTHON_BIN" "$REPO_ROOT/scripts/export_openapi_schema.py" --output "$TMP_SCHEMA"
"$WEB_ROOT/node_modules/.bin/openapi-typescript" "$TMP_SCHEMA" -o "$TMP_TYPES"

if ! cmp -s "$TMP_SCHEMA" "$GENERATED_SCHEMA"; then
  echo "OpenAPI schema is out of date. Run: cd apps/web && npm run generate:api-types" >&2
  exit 1
fi

if ! cmp -s "$TMP_TYPES" "$GENERATED_TYPES"; then
  echo "Generated API types are out of date. Run: cd apps/web && npm run generate:api-types" >&2
  exit 1
fi

echo "OpenAPI schema and generated API types are current."
