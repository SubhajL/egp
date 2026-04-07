#!/bin/sh
set -eu

DATABASE_URL="${DATABASE_URL:-sqlite+pysqlite:////tmp/egp-web-dev.sqlite3}"
EGP_PAYMENT_CALLBACK_SECRET="${EGP_PAYMENT_CALLBACK_SECRET:-top-secret}"
EGP_AUTH_REQUIRED="${EGP_AUTH_REQUIRED:-false}"
EGP_JWT_SECRET="${EGP_JWT_SECRET:-dev-jwt-secret}"
EGP_SESSION_COOKIE_SECURE="${EGP_SESSION_COOKIE_SECURE:-false}"
EGP_WEB_ALLOWED_ORIGINS="${EGP_WEB_ALLOWED_ORIGINS:-http://127.0.0.1:3002,http://localhost:3002}"
EGP_WEB_BASE_URL="${EGP_WEB_BASE_URL:-http://127.0.0.1:3002}"
NEXT_PUBLIC_EGP_API_BASE_URL="${NEXT_PUBLIC_EGP_API_BASE_URL:-http://127.0.0.1:8000}"

export DATABASE_URL
export EGP_PAYMENT_CALLBACK_SECRET
export EGP_AUTH_REQUIRED
export EGP_JWT_SECRET
export EGP_SESSION_COOKIE_SECURE
export EGP_WEB_ALLOWED_ORIGINS
export EGP_WEB_BASE_URL
export NEXT_PUBLIC_EGP_API_BASE_URL

case "$DATABASE_URL" in
  postgresql://*|postgresql+psycopg://*)
    ../../.venv/bin/python -m egp_db.migration_runner \
      --database-url "$DATABASE_URL" \
      --migrations-dir ../../packages/db/src/migrations
    ;;
esac

../../.venv/bin/uvicorn src.main:app \
  --app-dir ../api \
  --reload \
  --reload-dir ../api/src \
  --reload-dir ../../packages \
  --host 127.0.0.1 \
  --port 8000 &
api_pid=$!

cleanup() {
  kill "$api_pid" 2>/dev/null || true
  wait "$api_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

./scripts/dev-web.sh --hostname 127.0.0.1 --port 3002
