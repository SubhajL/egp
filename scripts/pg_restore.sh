#!/usr/bin/env bash
#
# pg_restore.sh — fetch a backup, verify sha256, restore to a target DB.
#
# Source resolution:
#   --source local|r2|local-fs|--source-path <path>
#   --object-key <key>      (when --source is r2 / local-fs)
#   --source-path <path>    (direct file; --sidecar-path <path> optional)
#
# Safety:
#   --target-url is required and must start with postgresql://
#   System databases (postgres, template0, template1) are refused.
#   Non-empty target databases require --force.
#   --yes acknowledges the destructive action.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${EGP_PYTHON_BIN:-${REPO_ROOT}/.venv/bin/python}"

usage() {
    cat <<'EOF'
Usage: pg_restore.sh [--help] \
    (--source <r2|local-fs> --object-key <key> | --source-path <archive> [--sidecar-path <sidecar>]) \
    --target-url <postgresql://...> \
    [--allow-non-empty] [--yes]

Fetches a backup archive (R2 / local-fs target, or a direct local path),
sha256-verifies it against its sidecar, then runs pg_restore --no-owner --no-acl
against the target URL.

Safety:
    * Refuses if --target-url does not start with postgresql://
    * Refuses system databases (postgres, template0, template1)
    * Refuses non-empty target databases unless --allow-non-empty
    * Aborts if sha256 does not match the sidecar
    * Requires --yes to skip interactive confirmation

See docs/BACKUP_AND_RESTORE.md.
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
        exit 127
    fi
}

require_binary pg_restore
require_binary psql

source_kind=""
object_key=""
source_path=""
sidecar_path=""
target_url=""
allow_non_empty="false"
assume_yes="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)
            source_kind="$2"; shift 2;;
        --object-key)
            object_key="$2"; shift 2;;
        --source-path)
            source_path="$2"; shift 2;;
        --sidecar-path)
            sidecar_path="$2"; shift 2;;
        --target-url)
            target_url="$2"; shift 2;;
        --allow-non-empty|--force)
            allow_non_empty="true"; shift;;
        --yes|-y)
            assume_yes="true"; shift;;
        *)
            echo "error: unknown argument $1" >&2
            usage >&2
            exit 2;;
    esac
done

if [[ -z "$target_url" ]]; then
    echo "error: --target-url is required" >&2
    exit 2
fi
if [[ "$target_url" != postgresql://* && "$target_url" != postgres://* ]]; then
    echo "error: --target-url must start with postgresql:// (got: ${target_url%%:*}:...)" >&2
    exit 2
fi

# Refuse system databases. Use current_database() against the actual
# connection so percent-encoded names or omitted DB paths (libpq defaults)
# cannot bypass the guard.
target_db="$(psql "$target_url" -At -c 'SELECT current_database()' 2>/dev/null || true)"
if [[ -z "$target_db" ]]; then
    echo "error: could not connect to ${target_url} to resolve target database name" >&2
    exit 2
fi
case "$target_db" in
    postgres|template0|template1)
        echo "error: refusing to restore over system database '${target_db}'" >&2
        exit 2;;
esac

# Non-empty target guard runs BEFORE archive fetch / sidecar verify so we
# don't waste time downloading + hashing a large dump only to refuse later.
# Counts any user-visible relation in non-system schemas, not just public.
if [[ "$allow_non_empty" != "true" ]]; then
    object_count="$(
        psql "$target_url" -At -c \
            "SELECT COUNT(*) FROM pg_catalog.pg_class c
             JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
               AND n.nspname NOT LIKE 'pg_toast%'
               AND n.nspname NOT LIKE 'pg_temp%'
               AND c.relkind IN ('r','p','v','m','S','f')"
    )"
    if [[ -n "$object_count" && "$object_count" -gt 0 ]]; then
        echo "error: target database has ${object_count} user object(s) across non-system schemas; pass --allow-non-empty to override" >&2
        exit 1
    fi
fi

# Resolve archive + sidecar
TMP_FETCH_DIR=""
cleanup_fetch() {
    if [[ -n "$TMP_FETCH_DIR" && -d "$TMP_FETCH_DIR" ]]; then
        rm -rf "$TMP_FETCH_DIR"
    fi
}
trap cleanup_fetch EXIT INT TERM

if [[ -n "$source_path" ]]; then
    if [[ ! -f "$source_path" ]]; then
        echo "error: --source-path not found: $source_path" >&2
        exit 2
    fi
    if [[ -z "$sidecar_path" ]]; then
        sidecar_path="${source_path}.sha256"
    fi
    if [[ ! -f "$sidecar_path" ]]; then
        echo "error: sidecar not found: $sidecar_path" >&2
        exit 2
    fi
elif [[ -n "$source_kind" && -n "$object_key" ]]; then
    TMP_FETCH_DIR="$(mktemp -d -t egp-pg-restore-XXXXXX)"
    EGP_BACKUP_TARGET="$source_kind" \
        "$PYTHON_BIN" -m egp_db.backup_targets download \
            --object-key "$object_key" \
            --dest-dir "$TMP_FETCH_DIR" >/dev/null
    archive_name="$(basename "$object_key")"
    source_path="${TMP_FETCH_DIR}/${archive_name}"
    sidecar_path="${source_path}.sha256"
else
    echo "error: provide either --source-path or --source <kind> --object-key <key>" >&2
    exit 2
fi

# sha256 verify
echo "==> verifying sha256 sidecar" >&2
"$PYTHON_BIN" -c "
import sys
from pathlib import Path
from egp_db.backup_files import verify_sha256_sidecar

verify_sha256_sidecar(Path(sys.argv[1]), Path(sys.argv[2]))
print('sha256 OK')
" "$source_path" "$sidecar_path"

# Confirmation
parsed_host="$(
    "$PYTHON_BIN" - "$target_url" <<'EOF'
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
print(f"{parsed.hostname or '?'}:{parsed.port or 5432}")
EOF
)"
echo "==> restore target: host=${parsed_host} dbname=${target_db}" >&2

if [[ "$assume_yes" != "true" ]]; then
    echo -n "type 'yes' to continue: " >&2
    read -r reply
    if [[ "$reply" != "yes" ]]; then
        echo "aborted" >&2
        exit 1
    fi
fi

# Atomic restore: always exit-on-error, wrap in single-transaction when
# the target is empty (the common case). For --allow-non-empty restores
# the operator has explicitly opted into a riskier scenario; use
# exit-on-error only so the operator sees the first failure.
restore_flags=("--no-owner" "--no-acl" "--exit-on-error")
if [[ "$allow_non_empty" != "true" ]]; then
    restore_flags+=("--single-transaction")
fi

echo "==> pg_restore ${restore_flags[*]} -d ${target_db}" >&2
gunzip -c "$source_path" | pg_restore "${restore_flags[@]}" -d "$target_url"
echo "==> done" >&2
