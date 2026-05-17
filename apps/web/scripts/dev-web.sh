#!/bin/sh
set -eu

NEXT_DIST_DIR="${NEXT_DIST_DIR:-.next-dev}"

export NEXT_DIST_DIR

exec npx next dev "$@"
