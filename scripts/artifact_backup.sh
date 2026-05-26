#!/usr/bin/env bash
#
# artifact_backup.sh — mirror the document-artifact bucket to a Cloudflare R2
# backup remote using rclone copy (NEVER sync, so source deletes don't
# propagate to the backup).
#
# Required env vars:
#   EGP_ARTIFACT_BACKUP_SRC_REMOTE     — rclone remote (e.g. supabase-prod:egp-documents)
#   EGP_ARTIFACT_BACKUP_DEST_REMOTE    — rclone remote (e.g. r2-backups:egp-artifacts-mirror)
#
# Optional args:
#   --dry-run   — show what would be copied without writing
#   --verbose   — pass -v through to rclone

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: artifact_backup.sh [--help] [--dry-run] [--verbose]

Mirrors a document-artifact bucket to a backup remote using `rclone copy`.
Never uses `rclone sync`, so accidental source deletions are not propagated.

Required environment variables:
    EGP_ARTIFACT_BACKUP_SRC_REMOTE     rclone remote (source)
    EGP_ARTIFACT_BACKUP_DEST_REMOTE    rclone remote (destination)

Prerequisites:
    * rclone must be installed and configured for both remotes.
      See docs/BACKUP_AND_RESTORE.md for rclone install + R2 remote setup.

This script intentionally hard-fails if rclone is not installed.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

# Parse args first so --dry-run etc. work even before env-var validation.
extra_flags=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            extra_flags+=("--dry-run"); shift;;
        --verbose|-v)
            extra_flags+=("-v"); shift;;
        *)
            echo "error: unknown argument $1" >&2
            usage >&2
            exit 2;;
    esac
done

# Env-var validation before rclone check (so users get clear errors even
# without rclone installed).
: "${EGP_ARTIFACT_BACKUP_SRC_REMOTE:?EGP_ARTIFACT_BACKUP_SRC_REMOTE is required}"
: "${EGP_ARTIFACT_BACKUP_DEST_REMOTE:?EGP_ARTIFACT_BACKUP_DEST_REMOTE is required}"

if ! command -v rclone >/dev/null 2>&1; then
    echo "error: rclone is required but not found on PATH" >&2
    echo "       install with: brew install rclone   (macOS)" >&2
    echo "                     apt install rclone     (debian/ubuntu)" >&2
    echo "       see docs/BACKUP_AND_RESTORE.md for remote configuration" >&2
    exit 127
fi

echo "==> rclone copy ${EGP_ARTIFACT_BACKUP_SRC_REMOTE} -> ${EGP_ARTIFACT_BACKUP_DEST_REMOTE}" >&2
rclone copy \
    "${EGP_ARTIFACT_BACKUP_SRC_REMOTE}" \
    "${EGP_ARTIFACT_BACKUP_DEST_REMOTE}" \
    ${extra_flags[@]+"${extra_flags[@]}"}
echo "==> done" >&2
