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

caller_overlays=()
remaining_args=()
resolve_overlay_path() {
  local overlay_path="$1"
  if [[ "$overlay_path" == /* ]]; then
    printf '%s\n' "$overlay_path"
  else
    printf '%s/%s\n' "$TARGET_ROOT" "$overlay_path"
  fi
}
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    -f|--file)
      if [[ "$#" -lt 2 ]]; then
        echo "$1 requires a path" >&2
        exit 2
      fi
      caller_overlays+=("$(resolve_overlay_path "$2")")
      shift 2
      ;;
    --file=*)
      caller_overlays+=("$(resolve_overlay_path "${1#--file=}")")
      shift
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

overlay_has_runtime_source_mount() {
  local overlay_path="$1"
  local short_mount_pattern
  local long_mount_pattern
  short_mount_pattern=":[[:space:]]*[\"']?/app([/,:[:space:]]|[\"']|\$)"
  long_mount_pattern="target[[:space:]]*[:=][[:space:]]*[\"']?/app([/,:[:space:]]|[\"']|\$)"
  [[ -f "$overlay_path" ]] || return 1
  LC_ALL=C grep -Eq "$short_mount_pattern|$long_mount_pattern" "$overlay_path"
}

if [[ -f "$TARGET_ROOT/docker-compose.override.yml" ]] &&
  overlay_has_runtime_source_mount "$TARGET_ROOT/docker-compose.override.yml"; then
  echo "runtime source mount detected; refusing release Compose" >&2
  exit 1
fi
if [[ "${#caller_overlays[@]}" -gt 0 ]]; then
  for caller_overlay in "${caller_overlays[@]}"; do
    if overlay_has_runtime_source_mount "$caller_overlay"; then
      echo "runtime source mount detected; refusing release Compose" >&2
      exit 1
    fi
  done
fi

export EGP_RELEASE_SHA="$release_sha"
cd "$TARGET_ROOT"
compose_args=(
  --project-directory "$TARGET_ROOT"
  -f "$TARGET_ROOT/docker-compose.yml"
)
if [[ -f "$TARGET_ROOT/docker-compose.override.yml" ]]; then
  compose_args+=(-f "$TARGET_ROOT/docker-compose.override.yml")
fi
if [[ "${#caller_overlays[@]}" -gt 0 ]]; then
  for caller_overlay in "${caller_overlays[@]}"; do
    compose_args+=(-f "$caller_overlay")
  done
fi
compose_args+=(-f "$DRIVER_ROOT/docker-compose.release.yml")
if [[ "${#remaining_args[@]}" -gt 0 ]]; then
  compose_args+=("${remaining_args[@]}")
fi
exec docker compose "${compose_args[@]}"
