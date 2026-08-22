#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DRIVER_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
TARGET_ROOT="$DRIVER_ROOT"

if [[ "${1:-}" == "--source-root" ]]; then
  if [[ "$#" -lt 2 ]]; then
    echo "--source-root requires a path" >&2
    exit 2
  fi
  source_root_arg="$2"
  shift 2
  if ! TARGET_ROOT="$(cd -- "$source_root_arg" 2>/dev/null && pwd -P)"; then
    echo "source root is not an absolute, resolved checkout directory" >&2
    exit 1
  fi
fi

if [[ "$TARGET_ROOT" != /* ]]; then
  echo "source root is not an absolute, resolved checkout directory" >&2
  exit 1
fi

release_sha="$(git -C "$TARGET_ROOT" rev-parse --verify HEAD 2>/dev/null || true)"
if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "unable to derive exact release revision from tracked source" >&2
  exit 1
fi

if ! git -C "$TARGET_ROOT" diff --quiet --; then
  echo "tracked source is dirty (unstaged changes)" >&2
  exit 1
fi
if ! git -C "$TARGET_ROOT" diff --cached --quiet --; then
  echo "tracked source is dirty (staged changes)" >&2
  exit 1
fi

untracked_runtime_source="$(
  git -C "$TARGET_ROOT" ls-files --others --exclude-standard -- \
    pyproject.toml uv.lock apps/api apps/worker packages
)"
untracked_runtime_executable=""
while IFS= read -r untracked_path; do
  case "$untracked_path" in
    pyproject.toml|uv.lock|*.py|*.pyc|*.pth|*.so|*.pyd)
      untracked_runtime_executable="$untracked_path"
      break
      ;;
  esac
done <<< "$untracked_runtime_source"
if [[ -n "$untracked_runtime_executable" ]]; then
  echo "untracked runtime source detected; refusing release Compose" >&2
  exit 1
fi

ignored_runtime_source="$(
  git -C "$TARGET_ROOT" ls-files --others --ignored --exclude-standard -- \
    pyproject.toml uv.lock apps/api apps/worker packages
)"
ignored_runtime_executable=""
while IFS= read -r ignored_path; do
  case "$ignored_path" in
    pyproject.toml|uv.lock|*.py|*.pyc|*.pth|*.so|*.pyd)
      ignored_runtime_executable="$ignored_path"
      break
      ;;
  esac
done <<< "$ignored_runtime_source"
if [[ -n "$ignored_runtime_executable" ]]; then
  echo "ignored runtime source detected; refusing release Compose" >&2
  exit 1
fi

remaining_args=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --project-directory|--project-directory=*)
      echo "project directory override is not permitted" >&2
      exit 2
      ;;
    -f|--file)
      echo "compose file override is not permitted" >&2
      exit 2
      ;;
    --file=*)
      echo "compose file override is not permitted" >&2
      exit 2
      ;;
    *)
      remaining_args+=("$1")
      shift
      ;;
  esac
done

compose_service_defined() {
  local service_name="$1"
  awk -v service_name="$service_name" '
    /^services:[[:space:]]*(#.*)?$/ { in_services=1; next }
    in_services && /^[^[:space:]]/ { in_services=0 }
    in_services && index($0, "  " service_name ":") == 1 { found=1 }
    END { exit(found ? 0 : 1) }
  ' "$TARGET_ROOT/docker-compose.yml"
}

required_release_services=(
  migrate
  api
  webhook-executor
  crawler-agent-inbox-executor
  discovery-executor
)
if [[ ! -f "$TARGET_ROOT/docker-compose.yml" ]]; then
  echo "incompatible release topology" >&2
  exit 1
fi
for required_service in "${required_release_services[@]}"; do
  if ! compose_service_defined "$required_service"; then
    echo "incompatible release topology" >&2
    exit 1
  fi
done

export EGP_RELEASE_SHA="$release_sha"
cd "$TARGET_ROOT"
compose_args=(
  --project-directory "$TARGET_ROOT"
  -f "$TARGET_ROOT/docker-compose.yml"
)
compose_args+=(-f "$DRIVER_ROOT/docker-compose.release.yml")
if [[ "${#remaining_args[@]}" -gt 0 ]]; then
  compose_args+=("${remaining_args[@]}")
fi
exec docker compose "${compose_args[@]}"
