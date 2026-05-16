#!/bin/sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

"$SCRIPT_DIR/generate-openapi-schema.sh"
"$WEB_ROOT/node_modules/.bin/openapi-typescript" \
  "$WEB_ROOT/src/lib/generated/openapi.json" \
  -o "$WEB_ROOT/src/lib/generated/api-types.ts"
