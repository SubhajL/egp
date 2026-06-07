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
#   scripts/install_launchd.sh install [--with-warm]
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

cmd_install() {
  local with_warm=false
  if [[ "${1:-}" == "--with-warm" ]]; then
    with_warm=true
    shift
  fi
  if [[ $# -gt 0 ]]; then
    echo "usage: $0 install [--with-warm]" >&2
    exit 2
  fi
  if [[ "$with_warm" == true ]]; then
    LABELS+=("$OPTIONAL_WARM_LABEL")
  else
    local uid
    uid="$(id -u)"
    launchctl bootout "gui/$uid/$OPTIONAL_WARM_LABEL" 2>/dev/null || true
    rm -f "$AGENT_DIR/$OPTIONAL_WARM_LABEL.plist"
  fi
  assert_safe_path REPO_ROOT "$ROOT"
  assert_safe_path HOME "$HOME"
  mkdir -p "$AGENT_DIR" "$LOG_DIR"
  local uid; uid="$(id -u)"
  for label in "${LABELS[@]}"; do
    render "$label"
    launchctl bootout "gui/$uid/$label" 2>/dev/null || true
    # bootout is asynchronous; bootstrapping before the old instance is fully
    # torn down makes launchctl return "Bootstrap failed: 5: Input/output
    # error". Wait until the label is gone (up to ~10s) before bootstrapping.
    for _ in $(seq 1 50); do
      launchctl print "gui/$uid/$label" >/dev/null 2>&1 || break
      sleep 0.2
    done
    launchctl bootstrap "gui/$uid" "$AGENT_DIR/$label.plist"
    echo "loaded $label"
  done
  if [[ "$with_warm" == true ]]; then
    echo "Installed with warm-profile timer. Logs: $LOG_DIR/{tunnel,crawl,warm}.log"
  else
    echo "Installed without warm-profile timer. Logs: $LOG_DIR/{tunnel,crawl}.log"
    echo "Use '$0 install --with-warm' to opt in to the 15-minute Chrome keep-warm timer."
  fi
}

cmd_uninstall() {
  local uid; uid="$(id -u)"
  for label in "${ALL_LABELS[@]}"; do
    launchctl bootout "gui/$uid/$label" 2>/dev/null || true
    rm -f "$AGENT_DIR/$label.plist"
    echo "removed $label"
  done
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
  *) echo "usage: $0 {install [--with-warm]|uninstall|status}" >&2; exit 2 ;;
esac
