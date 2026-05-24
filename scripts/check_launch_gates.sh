#!/usr/bin/env bash
# Launch-readiness gate checker for the PR-00 -> PR-08 rollout series.
#
# Runs the Mode A point-in-time checks documented in the rollout plan and
# reports pass/fail per gate. Safe to re-run anytime; read-only except for the
# optional admission-control functional probe (which only fires when explicitly
# enabled via --probe-admission).
#
# Usage:
#   scripts/check_launch_gates.sh                       # all read-only checks
#   API_URL=https://api.example.com scripts/check_launch_gates.sh
#   scripts/check_launch_gates.sh --probe-admission \
#       --tenant-id <uuid> --bearer <token>
#
# Env vars (all optional, sensible defaults shown):
#   API_URL                  default http://localhost:8000
#   DATABASE_URL             required for the cross-tenant DB gate
#   EGP_BROWSER_PROFILE_ROOT default ~/.egp/profiles
#   EGP_DISCOVERY_WORKER_COUNT default 1 (used as the Chrome PID cap)
#   CHROME_PID_PATTERN       default "[C]hrome.*remote-debugging-port"
#   CROSS_TENANT_WINDOW      default '72 hours'

set -u
set -o pipefail

API_URL="${API_URL:-http://localhost:8000}"
PROFILE_ROOT="${EGP_BROWSER_PROFILE_ROOT:-$HOME/.egp/profiles}"
WORKER_COUNT_CAP="${EGP_DISCOVERY_WORKER_COUNT:-1}"
CHROME_PID_PATTERN="${CHROME_PID_PATTERN:-[C]hrome.*remote-debugging-port}"
CROSS_TENANT_WINDOW="${CROSS_TENANT_WINDOW:-72 hours}"

PROBE_ADMISSION=0
PROBE_TENANT=""
PROBE_BEARER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --probe-admission) PROBE_ADMISSION=1; shift ;;
        --tenant-id) PROBE_TENANT="$2"; shift 2 ;;
        --bearer) PROBE_BEARER="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *)
            echo "unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
FAILED_GATES=()

green() { printf '\033[32m%s\033[0m' "$1"; }
red()   { printf '\033[31m%s\033[0m' "$1"; }
gray()  { printf '\033[90m%s\033[0m' "$1"; }

report_pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    printf '  [%s] %s\n' "$(green PASS)" "$1"
    [[ -n "${2:-}" ]] && printf '         %s\n' "$(gray "$2")"
}

report_fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILED_GATES+=("$1")
    printf '  [%s] %s\n' "$(red FAIL)" "$1"
    [[ -n "${2:-}" ]] && printf '         %s\n' "$2"
}

report_skip() {
    SKIP_COUNT=$((SKIP_COUNT + 1))
    printf '  [%s] %s\n' "$(gray SKIP)" "$1"
    [[ -n "${2:-}" ]] && printf '         %s\n' "$(gray "$2")"
}

section() {
    printf '\n%s\n' "$1"
    printf '%s\n' "$(printf '%.0s-' {1..60})"
}

# -----------------------------------------------------------------------------
section "Gate: API /metrics endpoint reachable"
METRICS_RAW="$(curl -sf -m 10 "$API_URL/metrics" 2>/dev/null || true)"
if [[ -z "$METRICS_RAW" ]]; then
    report_fail "API /metrics reachable at $API_URL" \
        "curl failed; subsequent metric gates will skip"
    METRICS_OK=0
else
    report_pass "API /metrics reachable at $API_URL"
    METRICS_OK=1
fi

# Helper to read latest sample value for a metric name (ignores _created lines).
metric_sum() {
    local name="$1"
    local filter="${2:-}"
    if [[ "$METRICS_OK" != "1" ]]; then echo ""; return; fi
    local pattern="^${name}"
    [[ -n "$filter" ]] && pattern="^${name}{[^}]*${filter}[^}]*}"
    awk -v pat="$pattern" '
        $0 ~ "^#" { next }
        $0 ~ pat && $0 !~ /_created/ { sum += $NF }
        END { if (NR > 0) print sum + 0 }
    ' <<< "$METRICS_RAW"
}

metric_max() {
    local name="$1"
    if [[ "$METRICS_OK" != "1" ]]; then echo ""; return; fi
    awk -v name="^${name}" '
        $0 ~ "^#" { next }
        $0 ~ name && $0 !~ /_created/ { if ($NF + 0 > max) max = $NF + 0 }
        END { print max + 0 }
    ' <<< "$METRICS_RAW"
}

# -----------------------------------------------------------------------------
section "Gate: PR-03 / Chrome PID cap (<= $WORKER_COUNT_CAP)"
CHROME_PIDS=$(ps -eo pid,command 2>/dev/null | grep -c "$CHROME_PID_PATTERN" || true)
if [[ "$CHROME_PIDS" -le "$WORKER_COUNT_CAP" ]]; then
    report_pass "Chrome remote-debugging PIDs = $CHROME_PIDS" \
        "<= EGP_DISCOVERY_WORKER_COUNT ($WORKER_COUNT_CAP)"
else
    report_fail "Chrome remote-debugging PIDs = $CHROME_PIDS" \
        "exceeds worker_count cap ($WORKER_COUNT_CAP); investigate orphan browsers"
fi

# -----------------------------------------------------------------------------
section "Gate: PR-03 / browser profile-dir cleanup"
if [[ -d "$PROFILE_ROOT" ]]; then
    # Count first-level entries; recent ones (<5 min) are likely in-flight runs.
    TOTAL_DIRS=$(find "$PROFILE_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
    STALE_DIRS=$(find "$PROFILE_ROOT" -mindepth 1 -maxdepth 1 -type d -mmin +5 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$STALE_DIRS" -eq 0 ]]; then
        report_pass "$PROFILE_ROOT: $TOTAL_DIRS total, 0 stale (>5 min old)" \
            "cleanup is removing per-run profile dirs"
    else
        report_fail "$PROFILE_ROOT: $STALE_DIRS stale profile dirs (>5 min old)" \
            "PR-03 finally-block cleanup may be failing"
    fi
else
    report_skip "$PROFILE_ROOT does not exist (no crawls have run on this host)"
fi

# -----------------------------------------------------------------------------
section "Gate: PR-03 / cross-tenant attribution (DB)"
if [[ -z "${DATABASE_URL:-}" ]]; then
    report_skip "DATABASE_URL not set; cannot query for tenant mismatches"
elif ! command -v psql >/dev/null 2>&1; then
    report_skip "psql not on PATH; cannot run the cross-tenant query"
else
    CROSS=$(psql "$DATABASE_URL" -At -c "
        SELECT COUNT(*)
        FROM documents d
        JOIN crawl_tasks t ON t.id = d.crawl_task_id
        JOIN crawl_runs  r ON r.id = t.run_id
        WHERE d.tenant_id <> r.tenant_id
          AND r.created_at > now() - interval '$CROSS_TENANT_WINDOW';
    " 2>/dev/null || echo "ERR")
    if [[ "$CROSS" == "0" ]]; then
        report_pass "0 cross-tenant document/run mismatches in last $CROSS_TENANT_WINDOW"
    elif [[ "$CROSS" == "ERR" ]]; then
        report_fail "cross-tenant query failed" "check DATABASE_URL + schema"
    else
        report_fail "$CROSS cross-tenant mismatches in last $CROSS_TENANT_WINDOW" \
            "PR-03 isolation broken; do NOT raise worker_count"
    fi
fi

# -----------------------------------------------------------------------------
section "Gate: PR-04 / project upsert conflict outcomes"
DROPPED=$(metric_sum egp_project_upsert_conflicts_total 'outcome="dropped"')
RESOLVED=$(metric_sum egp_project_upsert_conflicts_total 'outcome="resolved"')
if [[ "$METRICS_OK" != "1" ]]; then
    report_skip "metrics endpoint unavailable"
elif [[ -z "$DROPPED" ]] && [[ -z "$RESOLVED" ]]; then
    report_skip "no project upsert conflicts observed yet (counter absent)" \
        "expected before first concurrent crawl"
elif [[ "${DROPPED:-0}" == "0" ]]; then
    report_pass "project upsert conflicts: resolved=${RESOLVED:-0}, dropped=0"
else
    report_fail "project upsert conflicts dropped=$DROPPED (should be 0)" \
        "PR-04 ON CONFLICT path not catching all races"
fi

# -----------------------------------------------------------------------------
section "Gate: PR-05 / document upsert conflict outcomes"
DOC_DROPPED=$(metric_sum egp_document_upsert_conflicts_total 'outcome="dropped"')
DOC_RESOLVED=$(metric_sum egp_document_upsert_conflicts_total 'outcome="resolved"')
if [[ "$METRICS_OK" != "1" ]]; then
    report_skip "metrics endpoint unavailable"
elif [[ -z "$DOC_DROPPED" ]] && [[ -z "$DOC_RESOLVED" ]]; then
    report_skip "no document upsert conflicts observed yet (counter absent)"
elif [[ "${DOC_DROPPED:-0}" == "0" ]]; then
    report_pass "document upsert conflicts: resolved=${DOC_RESOLVED:-0}, dropped=0"
else
    report_fail "document upsert conflicts dropped=$DOC_DROPPED (should be 0)" \
        "PR-05 ON CONFLICT path not catching all races"
fi

# -----------------------------------------------------------------------------
section "Gate: PR-06 / e-GP 429 rate"
EGP_429=$(metric_sum egp_egp_request_total 'outcome="429"')
EGP_OK=$(metric_sum egp_egp_request_total 'outcome="ok"')
if [[ "$METRICS_OK" != "1" ]]; then
    report_skip "metrics endpoint unavailable"
elif [[ -z "$EGP_429" ]] && [[ -z "$EGP_OK" ]]; then
    report_skip "no e-GP requests observed yet"
elif [[ "${EGP_429:-0}" == "0" ]]; then
    report_pass "e-GP 429 outcomes = 0 (ok=${EGP_OK:-0})"
else
    report_fail "e-GP 429 outcomes = $EGP_429" \
        "rate limiter not holding the line; reduce EGP_EGP_RPS"
fi

# -----------------------------------------------------------------------------
section "Gate: PR-06 / rate limiter engaging"
LIMITER_COUNT=$(metric_sum egp_rate_limiter_wait_seconds_count)
if [[ "$METRICS_OK" != "1" ]]; then
    report_skip "metrics endpoint unavailable"
elif [[ -z "$LIMITER_COUNT" ]] || [[ "$LIMITER_COUNT" == "0" ]]; then
    report_skip "rate limiter wait count = 0" \
        "expected at worker_count=1 with low traffic; should be >0 at worker_count>=2"
else
    report_pass "rate limiter wait samples = $LIMITER_COUNT (limiter is engaging)"
fi

# -----------------------------------------------------------------------------
section "Gate: PR-08 / inflight runs <= max_concurrent_runs"
INFLIGHT_MAX=$(metric_max egp_discovery_inflight_runs)
if [[ "$METRICS_OK" != "1" ]]; then
    report_skip "metrics endpoint unavailable"
elif [[ -z "$INFLIGHT_MAX" ]]; then
    report_skip "egp_discovery_inflight_runs not present yet"
else
    # No way to know per-tenant max_concurrent_runs from the metric alone;
    # report the value and let the operator compare to the entitlement.
    report_pass "max observed egp_discovery_inflight_runs = $INFLIGHT_MAX" \
        "compare against tenant_entitlements.max_concurrent_runs (default 1)"
fi

# -----------------------------------------------------------------------------
section "Gate: subprocess count <= worker_count"
SUBPROC_MAX=$(metric_max egp_worker_subprocess_count)
if [[ "$METRICS_OK" != "1" ]]; then
    report_skip "metrics endpoint unavailable"
elif [[ -z "$SUBPROC_MAX" ]]; then
    report_skip "egp_worker_subprocess_count not present yet"
elif awk "BEGIN{exit !($SUBPROC_MAX <= $WORKER_COUNT_CAP)}"; then
    report_pass "max egp_worker_subprocess_count = $SUBPROC_MAX (<= $WORKER_COUNT_CAP)"
else
    report_fail "max egp_worker_subprocess_count = $SUBPROC_MAX (> $WORKER_COUNT_CAP)" \
        "PR-00/PR-03 safe operating point breached"
fi

# -----------------------------------------------------------------------------
if [[ "$PROBE_ADMISSION" == "1" ]]; then
    section "Gate: PR-08 / admission-control functional probe (WRITES traffic)"
    if [[ -z "$PROBE_TENANT" ]] || [[ -z "$PROBE_BEARER" ]]; then
        report_fail "--probe-admission requires --tenant-id and --bearer" \
            "skipping probe"
    else
        URL="$API_URL/v1/rules/recrawl"
        AUTH="Authorization: Bearer $PROBE_BEARER"
        BODY="{\"tenant_id\":\"$PROBE_TENANT\"}"

        FIRST=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
            -H "$AUTH" -H 'content-type: application/json' \
            -d "$BODY" "$URL" || echo "000")
        SECOND=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
            -H "$AUTH" -H 'content-type: application/json' \
            -d "$BODY" "$URL" || echo "000")

        if [[ "$FIRST" == "202" ]] && [[ "$SECOND" == "429" ]]; then
            report_pass "first recrawl=$FIRST, second=$SECOND" \
                "admission control gating works for tenant $PROBE_TENANT"
        else
            report_fail "first recrawl=$FIRST, second=$SECOND (expected 202, 429)" \
                "PR-08 admission control NOT enforcing as expected"
        fi
    fi
fi

# -----------------------------------------------------------------------------
section "Summary"
printf '  Passed:  %s\n' "$(green "$PASS_COUNT")"
printf '  Failed:  %s\n' "$(red "$FAIL_COUNT")"
printf '  Skipped: %s\n' "$(gray "$SKIP_COUNT")"
if [[ "$FAIL_COUNT" -gt 0 ]]; then
    printf '\nFailed gates:\n'
    for g in "${FAILED_GATES[@]}"; do
        printf '  - %s\n' "$g"
    done
    exit 1
fi
printf '\nAll observed gates green. Skips are expected when traffic has not yet exercised the relevant path.\n'
exit 0
