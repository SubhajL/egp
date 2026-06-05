#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# TRACK C — REMOTE crawler. THIS MAC CRAWLS PRODUCTION. See:
#   docs/REMOTE_LOCAL_CRAWLER.md  and  TRACKS.md
#
# The deliberate inverse of scripts/run_local.sh (Track A): instead of refusing
# anything but localhost:5434, this runner REFUSES TO START unless every
# production safety rail is in place (scripts/remote_crawl_guard.py). It runs
# the discovery dispatcher + worker natively with REAL Mac Chrome and a warmed
# persistent profile, claiming jobs from the PRODUCTION queue (reached via an
# SSH tunnel, Topology A) and writing artifacts to Supabase + events to the API.
#
# The env file is NEVER `source`d (that would shell-evaluate it and break on
# values with spaces); it is parsed + validated by the Python guard, which
# emits NUL-delimited KEY=VALUE pairs we export safely.
#
# Usage:
#   scripts/run_remote_crawl.sh check         # validate .env.remotecrawl, fail closed
#   scripts/run_remote_crawl.sh tunnel        # open the SSH tunnel to prod Postgres (foreground)
#   scripts/run_remote_crawl.sh warm-profile  # warm the persistent Chrome profile (run once)
#   scripts/run_remote_crawl.sh crawl [N]     # drain N pending prod jobs once, then exit
#   scripts/run_remote_crawl.sh watch         # continuously claim + crawl prod jobs
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
ENV_FILE="${EGP_REMOTECRAWL_ENV_FILE:-$ROOT/.env.remotecrawl}"
PY="$ROOT/.venv/bin/python"
GUARD="$ROOT/scripts/remote_crawl_guard.py"

require_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "missing $ENV_FILE — copy the template first:" >&2
    echo "  cp .env.remotecrawl.example .env.remotecrawl && chmod 600 .env.remotecrawl" >&2
    exit 1
  fi
}

# Fail-closed safety gate; validates the strict-parsed env file (no shell eval).
guard_check() { "$PY" "$GUARD" check --env-file "$ENV_FILE"; }

# Export the validated env into THIS shell WITHOUT shell evaluation. print-env
# only emits after validation passes; guard_check above is the hard gate.
load_validated_env() {
  local kv
  while IFS= read -r -d '' kv; do
    export "$kv"
  done < <("$PY" "$GUARD" print-env --env-file "$ENV_FILE")
}

run_module() {  # guard → load validated env → exec a venv python module
  guard_check
  load_validated_env
  exec "$PY" -m "$@"
}

case "${1:-check}" in
  check)        require_env_file; guard_check; echo "OK — safe to crawl production." ;;
  # Python execs the ssh argv directly (no bash word-split / option injection).
  tunnel)       require_env_file; exec "$PY" "$GUARD" tunnel-exec --env-file "$ENV_FILE" ;;
  warm-profile) require_env_file; run_module egp_worker.warmup ;;
  crawl)        require_env_file; shift || true; run_module egp_api.executors.discovery_dispatch --once --limit "${1:-5}" ;;
  watch)        require_env_file; run_module egp_api.executors.discovery_dispatch --poll-interval-seconds 2 ;;
  *) echo "usage: $0 {check|tunnel|warm-profile|crawl [N]|watch}" >&2; exit 2 ;;
esac
