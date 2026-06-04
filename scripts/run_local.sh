#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# TRACK A — LOCALHOST runner (this Mac only). See TRACKS.md.
#
# Keeps the local stack 100% isolated from production:
#   • never reads the prod-flavored root .env (always uses .env.localdev)
#   • never touches a non-localhost database (guard_localhost)
#   • crawls with REAL Mac Chrome natively (the in-container worker can't clear
#     Cloudflare — same failure as the Lightsail box)
#
# Usage:
#   scripts/run_local.sh up        # start Docker stack (UI/API/DB), auth ON
#   scripts/run_local.sh crawl [N] # one-shot native crawl of N pending jobs (real Chrome)
#   scripts/run_local.sh watch     # continuous native crawler (UI keyword adds auto-crawl)
#   scripts/run_local.sh status    # container status
#   scripts/run_local.sh down      # stop the stack
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
ENV_FILE="$ROOT/.env.localdev"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose-localdev.yml)
LOCAL_DB="postgresql://egp:egp_dev@localhost:5434/egp"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

bootstrap_env() {
  [[ -f "$ENV_FILE" ]] && return
  echo "Creating $ENV_FILE (local dev defaults — gitignored, no secrets)…"
  cat > "$ENV_FILE" <<'EOF'
# TRACK A — LOCALHOST only. Gitignored. No production secrets.
EGP_POSTGRES_DB=egp
EGP_POSTGRES_USER=egp
EGP_POSTGRES_PASSWORD=egp_dev
EGP_POSTGRES_PORT=5434
EGP_API_PORT=8010
EGP_WEB_PORT=3002
EGP_AUTH_REQUIRED=true
EGP_JWT_SECRET=dev-jwt-secret
EGP_SESSION_COOKIE_SECURE=false
EGP_PAYMENT_PROVIDER=mock_promptpay
# mock PromptPay builds the QR locally from this proxy id (no external acquirer).
EGP_PROMPTPAY_PROXY_ID=0899999999
EGP_ARTIFACT_STORE=local
EGP_BACKGROUND_RUNTIME_MODE=external
EOF
}

guard_localhost() {
  case "$LOCAL_DB" in
    *localhost*|*127.0.0.1*) : ;;
    *) echo "REFUSING: target DB is not localhost — track A must never touch production." >&2; exit 1 ;;
  esac
}

ensure_docker() { docker info >/dev/null 2>&1 || { echo "Starting OrbStack engine…"; orb start; }; }

native_env() {  # prints env assignments for the native crawler (localhost-only)
  guard_localhost
  printf 'DATABASE_URL=%s EGP_ARTIFACT_STORE=local EGP_ARTIFACT_ROOT=%s/artifacts ' "$LOCAL_DB" "$ROOT"
  printf 'EGP_BROWSER_CHROME_PATH=%s EGP_INTERNAL_API_BASE_URL=http://localhost:8010 ' "$CHROME"
  printf 'EGP_INTERNAL_WORKER_TOKEN=dev-internal-worker-token'
}

cmd_up() {
  ensure_docker; bootstrap_env
  "${COMPOSE[@]}" up -d --build
  # The in-container discovery-executor crawls headless-in-Linux and fails
  # Cloudflare (Chrome CDP unreachable) — stop it; we crawl natively instead.
  "${COMPOSE[@]}" stop discovery-executor >/dev/null 2>&1 || true
  echo "UI:  http://localhost:3002    API: http://localhost:8010/health    PG: localhost:5434"
}

cmd_crawl() {
  guard_localhost; ensure_docker
  env $(native_env) "$ROOT/.venv/bin/python" -m egp_api.executors.discovery_dispatch --once --limit "${1:-5}"
}

cmd_watch() {
  guard_localhost; ensure_docker
  echo "Native crawler watching the local queue (Ctrl-C to stop). Add keywords in the UI to trigger crawls."
  env $(native_env) "$ROOT/.venv/bin/python" -m egp_api.executors.discovery_dispatch --poll-interval-seconds 2
}

case "${1:-up}" in
  up)     cmd_up ;;
  crawl)  shift || true; cmd_crawl "${1:-5}" ;;
  watch)  cmd_watch ;;
  status) ensure_docker; "${COMPOSE[@]}" ps ;;
  down)   "${COMPOSE[@]}" down ;;
  *) echo "usage: $0 {up|crawl [N]|watch|status|down}"; exit 2 ;;
esac
