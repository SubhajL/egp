#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
UV_VERSION="${UV_VERSION:-0.11.32}"
UV_TOOL_DIR="${UV_TOOL_DIR:-$REPO_ROOT/.tools/uv-$UV_VERSION}"
UV_BIN="$UV_TOOL_DIR/bin/uv"

if [[ ! -x "$UV_BIN" ]]; then
    "$PYTHON_BIN" -m venv "$UV_TOOL_DIR"
    "$UV_TOOL_DIR/bin/python" -m pip install \
        --disable-pip-version-check \
        --no-deps \
        "uv==$UV_VERSION"
fi

uv() {
    "$UV_BIN" "$@"
}

UV_PROJECT_ENVIRONMENT="$VENV_DIR" \
UV_PYTHON="$PYTHON_BIN" \
    uv sync --frozen --all-packages --all-extras

echo "Virtualenv ready at $VENV_DIR"
echo "Activate with: source \"$VENV_DIR/bin/activate\""
