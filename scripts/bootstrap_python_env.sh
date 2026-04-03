#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -e . -e "$REPO_ROOT/apps/api[dev]" -e "$REPO_ROOT/apps/worker[dev]"

echo "Virtualenv ready at $VENV_DIR"
echo "Activate with: source \"$VENV_DIR/bin/activate\""
