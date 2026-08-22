#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# Install/uninstall the Track C always-on launchd agents (macOS):
#   • com.egp.pg-tunnel    — SSH tunnel to PRODUCTION Postgres
#   • com.egp.remote-crawl — native crawler watching the PRODUCTION queue
#   • com.egp.pg-warm      — optional keep-warm of the persistent Chrome profile
#
# Templates live in deploy/launchd/*.plist with __REPO_ROOT__ / __HOME__
# placeholders; this script substitutes them into ~/Library/LaunchAgents and
# (un)loads them via launchctl. See docs/REMOTE_LOCAL_CRAWLER.md.
#
# Usage:
#   scripts/install_launchd.sh install --acceptance-evidence <bundle.json> [--with-warm]
#   scripts/install_launchd.sh uninstall
#   scripts/install_launchd.sh status
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
TEMPLATE_DIR="$ROOT/deploy/launchd"
AGENT_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/egp"
DEFAULT_LABELS=(com.egp.pg-tunnel com.egp.remote-crawl)
OPTIONAL_WARM_LABEL=com.egp.pg-warm
ALL_LABELS=("${DEFAULT_LABELS[@]}" "$OPTIONAL_WARM_LABEL")
LABELS=("${DEFAULT_LABELS[@]}")
LOADED_LABELS=()
RENDERED_LABELS=()

assert_safe_path() {  # $1=name $2=path — reject chars unsafe for sed/XML plist rendering
  case "$2" in
    *['&|\<>"']*)
      echo "ERROR: $1 ($2) contains a character unsafe for plist rendering (& | \\ < > \")." >&2
      echo "Move the repo to a path without those characters and retry." >&2
      exit 1
      ;;
  esac
}

render() {  # $1 = label → write substituted plist into AGENT_DIR
  local label="$1"
  sed -e "s|__REPO_ROOT__|$ROOT|g" -e "s|__HOME__|$HOME|g" \
    "$TEMPLATE_DIR/$label.plist" > "$AGENT_DIR/$label.plist"
}

validate_acceptance_evidence() {
  local evidence_path="${1:-}"
  if [[ -z "$evidence_path" || ! -f "$evidence_path" || -L "$evidence_path" ]]; then
    echo "acceptance evidence must be a regular non-symlink file" >&2
    exit 1
  fi

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
  if ! "$ROOT/.venv/bin/python" "$ROOT/scripts/track_bc_verify.py" bundle \
    --evidence "$evidence_path" \
    --expected-release-sha "$release_sha" >/dev/null 2>&1; then
    echo "acceptance evidence was not accepted for the current release" >&2
    exit 1
  fi
}

wait_for_launchd_absent() {
  local label="$1"
  local uid
  uid="$(id -u)"
  for _ in $(seq 1 50); do
    if ! launchctl print "gui/$uid/$label" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  echo "ERROR: launchd label $label remained loaded after teardown." >&2
  echo "Expected gui/$uid/$label to be absent within 10 seconds." >&2
  return 1
}

wait_for_launchd_running() {
  local label="$1"
  local uid
  uid="$(id -u)"
  for _ in $(seq 1 50); do
    if launchctl print "gui/$uid/$label" 2>/dev/null \
      | grep -Eq '^[[:space:]]*state = running[[:space:]]*$'; then
      return 0
    fi
    sleep 0.2
  done
  echo "ERROR: launchd label $label did not reach state = running within 10 seconds." >&2
  echo "Expected gui/$uid/$label to report state = running." >&2
  return 1
}

assert_launchd_running() {
  local label="$1"
  local uid
  uid="$(id -u)"
  if launchctl print "gui/$uid/$label" 2>/dev/null \
    | grep -Eq '^[[:space:]]*state = running[[:space:]]*$'; then
    return 0
  fi
  echo "ERROR: managed launchd label $label is not state = running." >&2
  echo "Expected gui/$uid/$label to report state = running." >&2
  return 1
}

rollback_install() {
  local reason="$1"
  local uid
  local rollback_failed=false
  uid="$(id -u)"
  echo "ERROR: launchd install failed during $reason; rolling back." >&2

  for ((index=${#LOADED_LABELS[@]}-1; index>=0; index--)); do
    label="${LOADED_LABELS[$index]}"
    launchctl bootout "gui/$uid/$label" >/dev/null 2>&1 || true
    if ! wait_for_launchd_absent "$label"; then
      rollback_failed=true
    fi
  done
  for label in "${RENDERED_LABELS[@]}"; do
    if ! rm -f "$AGENT_DIR/$label.plist"; then
      rollback_failed=true
      echo "ERROR: rollback could not remove rendered plist for $label." >&2
    fi
  done
  if [[ "$rollback_failed" == true ]]; then
    echo "ERROR: launchd install rollback did not fully confirm cleanup." >&2
  fi
}

cmd_install() {
  local with_warm=false
  local acceptance_evidence=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --with-warm)
        with_warm=true
        shift
        ;;
      --acceptance-evidence)
        if [[ $# -lt 2 || "$2" == --* ]]; then
          echo "usage: $0 install --acceptance-evidence <bundle.json> [--with-warm]" >&2
          exit 2
        fi
        acceptance_evidence="$2"
        shift 2
        ;;
      *)
        echo "usage: $0 install --acceptance-evidence <bundle.json> [--with-warm]" >&2
        exit 2
        ;;
    esac
  done
  if [[ -z "$acceptance_evidence" ]]; then
    echo "usage: $0 install --acceptance-evidence <bundle.json> [--with-warm]" >&2
    exit 2
  fi
  validate_acceptance_evidence "$acceptance_evidence"
  assert_safe_path REPO_ROOT "$ROOT"
  assert_safe_path HOME "$HOME"
  if [[ "$with_warm" == true ]]; then
    LABELS+=("$OPTIONAL_WARM_LABEL")
  else
    local uid
    uid="$(id -u)"
    launchctl bootout "gui/$uid/$OPTIONAL_WARM_LABEL" >/dev/null 2>&1 || true
    if ! wait_for_launchd_absent "$OPTIONAL_WARM_LABEL"; then
      echo "ERROR: optional warm-profile label could not be removed." >&2
      return 1
    fi
    if ! rm -f "$AGENT_DIR/$OPTIONAL_WARM_LABEL.plist"; then
      echo "ERROR: optional warm-profile plist could not be removed." >&2
      return 1
    fi
  fi
  if ! mkdir -p "$AGENT_DIR" "$LOG_DIR"; then
    rollback_install "LaunchAgents directory setup"
    return 1
  fi
  local uid; uid="$(id -u)"
  for label in "${LABELS[@]}"; do
    RENDERED_LABELS+=("$label")
    if ! render "$label"; then
      rollback_install "render for $label"
      return 1
    fi
    launchctl bootout "gui/$uid/$label" >/dev/null 2>&1 || true
    # bootout is asynchronous; bootstrapping before the old instance is fully
    # torn down makes launchctl return "Bootstrap failed: 5: Input/output
    # error". Wait until the label is gone (up to ~10s) before bootstrapping.
    if ! wait_for_launchd_absent "$label"; then
      rollback_install "old-instance teardown for $label"
      return 1
    fi
    # Track the attempted bootstrap so a partially completed launchctl call is
    # also unloaded by the rollback path.
    LOADED_LABELS+=("$label")
    if ! launchctl bootstrap "gui/$uid" "$AGENT_DIR/$label.plist" >/dev/null 2>&1; then
      rollback_install "bootstrap for $label"
      return 1
    fi
    if [[ "$label" == "com.egp.pg-tunnel" ]]; then
      if ! wait_for_launchd_running "$label"; then
        rollback_install "running check for $label"
        return 1
      fi
      if ! "$ROOT/scripts/run_remote_crawl.sh" wait-database >/dev/null 2>&1; then
        rollback_install "database check"
        return 1
      fi
      if ! assert_launchd_running "$label"; then
        rollback_install "running recheck for $label"
        return 1
      fi
    elif [[ "$label" == "com.egp.remote-crawl" ]]; then
      if ! wait_for_launchd_running "$label"; then
        rollback_install "running check for $label"
        return 1
      fi
      if ! "$ROOT/scripts/run_remote_crawl.sh" doctor >/dev/null 2>&1; then
        rollback_install "watcher doctor check"
        return 1
      fi
      if ! assert_launchd_running "$label"; then
        rollback_install "running recheck for com.egp.remote-crawl"
        return 1
      fi
    fi
    echo "loaded $label"
  done
  if [[ "$with_warm" == true ]]; then
    echo "Installed with warm-profile timer. Logs: $LOG_DIR/{tunnel,crawl,warm}.log"
  else
    echo "Installed without warm-profile timer. Logs: $LOG_DIR/{tunnel,crawl}.log"
    echo "Use: $0 install --acceptance-evidence '$acceptance_evidence' --with-warm to opt in to the 15-minute Chrome keep-warm timer."
  fi
}

cmd_uninstall() {
  local uid; uid="$(id -u)"
  local failed=false
  for label in "$OPTIONAL_WARM_LABEL" "${DEFAULT_LABELS[1]}" "${DEFAULT_LABELS[0]}"; do
    launchctl bootout "gui/$uid/$label" >/dev/null 2>&1 || true
    if ! wait_for_launchd_absent "$label"; then
      failed=true
      continue
    fi
    if ! rm -f "$AGENT_DIR/$label.plist"; then
      echo "ERROR: could not remove plist for $label." >&2
      failed=true
      continue
    fi
    echo "removed $label"
  done
  if [[ "$failed" == true ]]; then
    return 1
  fi
}

cmd_status() {
  local uid; uid="$(id -u)"
  for label in "${ALL_LABELS[@]}"; do
    echo "== $label =="
    launchctl print "gui/$uid/$label" 2>/dev/null | grep -E "state|pid|program =" || echo "  not loaded"
  done
}

case "${1:-status}" in
  install)   shift || true; cmd_install "$@" ;;
  uninstall) cmd_uninstall ;;
  status)    cmd_status ;;
  *) echo "usage: $0 {install --acceptance-evidence <bundle.json> [--with-warm]|uninstall|status}" >&2; exit 2 ;;
esac
