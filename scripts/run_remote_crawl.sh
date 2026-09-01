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
#   scripts/run_remote_crawl.sh wait-database # bounded tunnel/database readiness check
#   scripts/run_remote_crawl.sh doctor        # read-only sanitized runtime diagnosis
#   scripts/run_remote_crawl.sh crawl [N]     # drain N pending prod jobs once, then exit
#   scripts/run_remote_crawl.sh crawl-canary <private-target.json>
#   scripts/run_remote_crawl.sh watch         # continuously claim + crawl prod jobs
#   scripts/run_remote_crawl.sh supervise <seconds> --evidence <runtime-evidence.json>
#   scripts/run_remote_crawl.sh observe-canary --keyword K --receipt <path>
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
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
  export PYTHONDONTWRITEBYTECODE=1
}

run_module() {  # guard → load validated env → exec a venv python module
  guard_check
  load_validated_env
  local release_sha
  release_sha="$(git -C "$ROOT" rev-parse --verify HEAD 2>/dev/null || true)"
  if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "unable to derive exact release revision from tracked source" >&2
    exit 1
  fi
  if ! git -C "$ROOT" diff --quiet --; then
    echo "tracked source is dirty (unstaged changes)" >&2
    exit 1
  fi
  if ! git -C "$ROOT" diff --cached --quiet --; then
    echo "tracked source is dirty (staged changes)" >&2
    exit 1
  fi
  local untracked_runtime_source
  untracked_runtime_source="$(
    git -C "$ROOT" ls-files --others --exclude-standard -- \
      pyproject.toml uv.lock apps/api apps/worker packages
  )"
  local untracked_runtime_executable
  while IFS= read -r untracked_path; do
    case "$untracked_path" in
      pyproject.toml|uv.lock|*.py|*.pyc|*.pth|*.so|*.pyd)
        untracked_runtime_executable="$untracked_path"
        break
        ;;
    esac
  done <<< "$untracked_runtime_source"
  if [[ -n "${untracked_runtime_executable:-}" ]]; then
    echo "untracked runtime source detected; refusing remote crawl" >&2
    exit 1
  fi
  local ignored_runtime_source
  ignored_runtime_source="$(
    git -C "$ROOT" ls-files --others --ignored --exclude-standard -- \
      pyproject.toml uv.lock apps/api apps/worker packages
  )"
  local ignored_runtime_executable=""
  while IFS= read -r ignored_path; do
    case "$ignored_path" in
      pyproject.toml|uv.lock|*.py|*.pyc|*.pth|*.so|*.pyd)
        ignored_runtime_executable="$ignored_path"
        break
        ;;
    esac
  done <<< "$ignored_runtime_source"
  if [[ -n "$ignored_runtime_executable" ]]; then
    echo "ignored runtime source detected; refusing remote crawl" >&2
    exit 1
  fi
  cd /
  export EGP_RELEASE_SHA="$release_sha"
  exec "$PY" -m "$@"
}

run_observation_canary() {
  guard_check
  load_validated_env
  local release_sha
  release_sha="$(git -C "$ROOT" rev-parse --verify HEAD 2>/dev/null || true)"
  if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "unable to derive exact release revision from tracked source" >&2
    exit 1
  fi
  if ! git -C "$ROOT" diff --quiet --; then
    echo "tracked source is dirty (unstaged changes)" >&2
    exit 1
  fi
  if ! git -C "$ROOT" diff --cached --quiet --; then
    echo "tracked source is dirty (staged changes)" >&2
    exit 1
  fi
  local untracked_runtime_source
  untracked_runtime_source="$(
    git -C "$ROOT" ls-files --others --exclude-standard -- \
      pyproject.toml uv.lock apps/api apps/worker packages
  )"
  local untracked_runtime_executable
  while IFS= read -r untracked_path; do
    case "$untracked_path" in
      pyproject.toml|uv.lock|*.py|*.pyc|*.pth|*.so|*.pyd)
        untracked_runtime_executable="$untracked_path"
        break
        ;;
    esac
  done <<< "$untracked_runtime_source"
  if [[ -n "${untracked_runtime_executable:-}" ]]; then
    echo "untracked runtime source detected; refusing observation canary" >&2
    exit 1
  fi
  local ignored_runtime_source
  ignored_runtime_source="$(
    git -C "$ROOT" ls-files --others --ignored --exclude-standard -- \
      pyproject.toml uv.lock apps/api apps/worker packages
  )"
  local ignored_runtime_executable=""
  while IFS= read -r ignored_path; do
    case "$ignored_path" in
      pyproject.toml|uv.lock|*.py|*.pyc|*.pth|*.so|*.pyd)
        ignored_runtime_executable="$ignored_path"
        break
        ;;
    esac
  done <<< "$ignored_runtime_source"
  if [[ -n "$ignored_runtime_executable" ]]; then
    echo "ignored runtime source detected; refusing observation canary" >&2
    exit 1
  fi
  cd /
  export EGP_RELEASE_SHA="$release_sha"
  unset DATABASE_URL EGP_ARTIFACT_STORE SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY
  unset SUPABASE_STORAGE_BUCKET AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
  unset AWS_SESSION_TOKEN AWS_SECURITY_TOKEN AWS_PROFILE
  unset S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY S3_SESSION_TOKEN
  unset R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_ACCOUNT_ID CLOUDFLARE_API_TOKEN
  exec "$PY" "$ROOT/scripts/diagnose_search_rows.py" \
    --observation-canary --max-pages 15 "$@"
}

run_supervise() {
  if [[ $# -ne 3 || "$2" != "--evidence" ]]; then
    echo "usage: $0 supervise <seconds> --evidence <runtime-evidence.json>" >&2
    exit 2
  fi
  local duration_seconds="$1"
  local runtime_evidence="$3"
  guard_check
  load_validated_env
  local release_sha
  release_sha="$(git -C "$ROOT" rev-parse --verify HEAD 2>/dev/null || true)"
  if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "unable to derive exact release revision from tracked source" >&2
    exit 1
  fi
  if ! git -C "$ROOT" diff --quiet --; then
    echo "tracked source is dirty (unstaged changes)" >&2
    exit 1
  fi
  if ! git -C "$ROOT" diff --cached --quiet --; then
    echo "tracked source is dirty (staged changes)" >&2
    exit 1
  fi
  local command_json
  command_json="$("$PY" -c 'import json, sys; print(json.dumps(sys.argv[1:]))' \
    "$ROOT/scripts/run_remote_crawl.sh" "watch")"
  local doctor_command_json
  doctor_command_json="$("$PY" -c 'import json, sys; print(json.dumps(sys.argv[1:]))' \
    "$ROOT/scripts/run_remote_crawl.sh" "doctor")"
  exec "$PY" "$ROOT/scripts/supervise_remote_crawl.py" \
    --duration-seconds "$duration_seconds" \
    --expected-release-sha "$release_sha" \
    --runtime-evidence "$runtime_evidence" \
    --command-json "$command_json" \
    --doctor-command-json "$doctor_command_json"
}

case "${1:-check}" in
  check)        require_env_file; guard_check; echo "OK — safe to crawl production." ;;
  # Python execs the ssh argv directly (no bash word-split / option injection).
  tunnel)       require_env_file; exec "$PY" "$GUARD" tunnel-exec --env-file "$ENV_FILE" ;;
  wait-database) require_env_file; shift || true; exec "$PY" "$GUARD" wait-database --env-file "$ENV_FILE" "$@" ;;
  warm-profile) require_env_file; run_module egp_worker.warmup ;;
  doctor)       require_env_file; run_module egp_api.executors.discovery_doctor ;;
  crawl)        require_env_file; shift || true; run_module egp_api.executors.discovery_dispatch --once --limit "${1:-5}" ;;
  crawl-canary) require_env_file; if [[ $# -ne 2 ]]; then echo "usage: $0 crawl-canary <private-target.json>" >&2; exit 2; fi; target_file="$2"; run_module egp_api.executors.discovery_dispatch --once --limit 1 --target-file "$target_file" ;;
  watch)        require_env_file; run_module egp_api.executors.discovery_dispatch --poll-interval-seconds 2 ;;
  supervise)    require_env_file; shift || true; run_supervise "$@" ;;
  # Read-only WS0 diagnostic: dump search rows for a keyword (no persistence, no DB).
  diagnose)     require_env_file; shift || true; guard_check; load_validated_env; exec "$PY" "$ROOT/scripts/diagnose_search_rows.py" "$@" ;;
  observe-canary) require_env_file; shift || true; run_observation_canary "$@" ;;
  *) echo "usage: $0 {check|tunnel|wait-database [options]|warm-profile|doctor|crawl [N]|crawl-canary <private-target.json>|watch|supervise <seconds> --evidence <runtime-evidence.json>|diagnose [--keyword K --max-pages N --attach]|observe-canary --keyword K --receipt PATH}" >&2; exit 2 ;;
esac
