#!/bin/sh
set -eu

next_env_file="next-env.d.ts"
next_env_backup="$(mktemp "${TMPDIR:-/tmp}/egp-next-env.XXXXXX")"

cp "$next_env_file" "$next_env_backup"

cleanup() {
  exit_status=$?
  trap - EXIT HUP INT TERM
  cp "$next_env_backup" "$next_env_file"
  rm -f "$next_env_backup"
  exit "$exit_status"
}

trap cleanup EXIT HUP INT TERM

npx playwright test "$@"
