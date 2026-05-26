#!/usr/bin/env bash
#
# pg_backup.sh — dump Postgres, gzip, sha256 sidecar, upload to backup target.
#
# Required env vars:
#   DATABASE_URL                       — Postgres URL to back up
#   EGP_BACKUP_TARGET                  — r2 | local-fs
#   EGP_BACKUP_LOCAL_CACHE_DIR         — local cache directory (always required)
#
# Optional env vars:
#   EGP_BACKUP_LOCAL_RETENTION_DAYS    — default 14
#   EGP_BACKUP_LOCAL_KEEP_MIN          — default 3
#   EGP_BACKUP_R2_*                    — required when target=r2 (see runbook)
#
# Exit codes: 0 success, non-zero on any failure.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${EGP_PYTHON_BIN:-${REPO_ROOT}/.venv/bin/python}"

usage() {
    cat <<'EOF'
Usage: pg_backup.sh [--help]

Dumps the database at $DATABASE_URL using pg_dump -Fc -Z0, gzips the output,
writes a .sha256 sidecar, uploads both to the configured EGP_BACKUP_TARGET,
then rotates the local cache.

Required environment variables:
    DATABASE_URL                    Postgres connection URL
    EGP_BACKUP_TARGET               r2 | local-fs
    EGP_BACKUP_LOCAL_CACHE_DIR      local cache directory

Optional environment variables:
    EGP_BACKUP_LOCAL_RETENTION_DAYS    (default 14)
    EGP_BACKUP_LOCAL_KEEP_MIN          (default 3)
    EGP_BACKUP_R2_ACCOUNT_ID           required when target=r2
    EGP_BACKUP_R2_ACCESS_KEY_ID        required when target=r2
    EGP_BACKUP_R2_SECRET_ACCESS_KEY    required when target=r2
    EGP_BACKUP_R2_BUCKET               required when target=r2
    EGP_BACKUP_R2_OBJECT_PREFIX        optional (e.g. prod/, staging/)

See docs/BACKUP_AND_RESTORE.md for full setup.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

require_binary() {
    local name="$1"
    if ! command -v "$name" >/dev/null 2>&1; then
        echo "error: required binary '$name' not found on PATH" >&2
        echo "       see docs/BACKUP_AND_RESTORE.md for installation help" >&2
        exit 127
    fi
}

require_binary pg_dump
require_binary gzip
require_binary df
# flock is preferred when available (Linux); on macOS we fall back to
# mkdir-based locking below.

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${EGP_BACKUP_TARGET:?EGP_BACKUP_TARGET is required (r2 | local-fs)}"
: "${EGP_BACKUP_LOCAL_CACHE_DIR:?EGP_BACKUP_LOCAL_CACHE_DIR is required}"

retention_days="${EGP_BACKUP_LOCAL_RETENTION_DAYS:-14}"
keep_min="${EGP_BACKUP_LOCAL_KEEP_MIN:-3}"

mkdir -p "$EGP_BACKUP_LOCAL_CACHE_DIR"

# Disk-space pre-flight: require free MB ≥ 256 (Postgres dumps are normally <100 MB compressed for this app).
free_mb="$(df -Pm "$EGP_BACKUP_LOCAL_CACHE_DIR" | awk 'NR==2 {print $4}')"
if [[ -n "$free_mb" && "$free_mb" -lt 256 ]]; then
    echo "error: insufficient free disk in $EGP_BACKUP_LOCAL_CACHE_DIR (${free_mb} MB available, need >= 256 MB)" >&2
    exit 28
fi

lockdir="${EGP_BACKUP_LOCAL_CACHE_DIR}/.pg_backup.lockdir"

run_backup() {
    local timestamp
    timestamp="$(date -u +%Y-%m-%dT%H%M%SZ)"

    local git_sha
    if git -C "$REPO_ROOT" rev-parse --short=7 HEAD >/dev/null 2>&1; then
        git_sha="$(git -C "$REPO_ROOT" rev-parse --short=7 HEAD)"
    else
        git_sha="0000000"
    fi

    local archive_name="egp-pg-${timestamp}-${git_sha}.dump.gz"
    local archive_path="${EGP_BACKUP_LOCAL_CACHE_DIR}/${archive_name}"
    local sidecar_path="${archive_path}.sha256"
    local tmp_archive
    tmp_archive="$(mktemp "${EGP_BACKUP_LOCAL_CACHE_DIR}/.pg_backup.XXXXXX.dump.gz")"

    cleanup() {
        rm -f "$tmp_archive" "${tmp_archive}.sha256"
    }
    trap cleanup EXIT INT TERM

    echo "==> pg_dump -> ${tmp_archive}" >&2
    # Redact DATABASE_URL from any error trace; -Fc -Z0 -> external gzip
    set +x
    pg_dump -Fc -Z0 "$DATABASE_URL" | gzip > "$tmp_archive"

    mv "$tmp_archive" "$archive_path"
    trap - EXIT INT TERM

    echo "==> computing sha256 sidecar" >&2
    "$PYTHON_BIN" -c "
import sys
from pathlib import Path
from egp_db.backup_files import sha256_file, write_sha256_sidecar

archive = Path(sys.argv[1])
digest = sha256_file(archive)
sidecar = write_sha256_sidecar(archive, digest=digest)
print(sidecar)
" "$archive_path" >/dev/null

    echo "==> uploading to target=${EGP_BACKUP_TARGET}" >&2
    "$PYTHON_BIN" -m egp_db.backup_targets upload \
        --archive "$archive_path" \
        --sidecar "$sidecar_path"

    echo "==> rotating local cache (retention=${retention_days}d, keep_min=${keep_min})" >&2
    "$PYTHON_BIN" -c "
import sys
from datetime import datetime, UTC
from pathlib import Path
from egp_db.backup_files import rotate_local_backup_cache

deleted = rotate_local_backup_cache(
    Path(sys.argv[1]),
    retention_days=int(sys.argv[2]),
    keep_min=int(sys.argv[3]),
    now=datetime.now(UTC),
)
for path in deleted:
    print(f'deleted {path}')
" "$EGP_BACKUP_LOCAL_CACHE_DIR" "$retention_days" "$keep_min"

    echo "==> done: ${archive_path}" >&2
    echo "$archive_path"
}

# Portable advisory lock via mkdir (atomic on POSIX filesystems).
# Stale lockdir cleanup: if owner PID is gone, reclaim.
if ! mkdir "$lockdir" 2>/dev/null; then
    if [[ -f "$lockdir/owner.pid" ]]; then
        owner_pid="$(cat "$lockdir/owner.pid" 2>/dev/null || echo)"
        if [[ -n "$owner_pid" ]] && ! kill -0 "$owner_pid" 2>/dev/null; then
            echo "warn: removing stale lockdir owned by dead pid ${owner_pid}" >&2
            rm -rf "$lockdir"
            mkdir "$lockdir"
        else
            echo "error: another pg_backup.sh is already running (pid ${owner_pid:-unknown})" >&2
            exit 75
        fi
    else
        echo "error: another pg_backup.sh is already running" >&2
        exit 75
    fi
fi
echo "$$" > "$lockdir/owner.pid"
cleanup_lock() { rm -rf "$lockdir"; }
trap cleanup_lock EXIT INT TERM

run_backup
