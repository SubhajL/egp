# Public MVP Track B + Track C Acceptance

This runbook qualifies the public control plane on Track B and one native Mac crawler on Track C.
It does not activate the crawler-agent backend. The accepted topology is:

- Track B: API, web delivery, PostgreSQL, artifacts, webhook executor, and crawler-agent inbox
  executor;
- Track B `discovery-executor`: built for provenance and rollback, but scaled to zero;
- Track C: one native Mac legacy discovery dispatcher using real Chrome and the production queue;
- crawler-agent protocol: `off`;
- selected crawl profile and all target pending jobs: `legacy`.

The campaign is fail-closed. A source test, an available `/ready` response, or a clean checkout is
not deployment evidence. Stop at the first mismatch and retain every receipt. Never put database
URLs, tokens, tenant IDs, job IDs, run IDs, browser-profile paths, or object keys in committed
files, terminal transcripts, or shared acceptance receipts.

## Private evidence workspace

Create a mode-0700 directory outside the repository. The examples call it
`<private-evidence-dir>`. Files containing identifiers, paths, authority records, or unredacted
command output remain there and are never committed. Sanitized verifier receipts may be copied
into the operations record after inspection.

Record the following before any production write:

- operator and timestamp;
- the exact authorized scope: database backup, artifact backup, migrations 038-040, Track B
  deployment, Mac Track C cutover, one bounded canary, bounded supervision, rollback rehearsal,
  and launchd installation;
- the frozen merge SHA;
- the approved migration-039 orphan-run deletion count, including zero;
- the approved maximum bundle age as a positive integer below 86,400 seconds;
- stop/backout authority and the person responsible for the Mac browser interaction.

## Stop conditions

Stop without retrying or mutating further when any of these occurs:

- source, image, container, Mac, or receipt SHA differs;
- another discovery writer or active crawl run exists during migration;
- preflight repair counts are not reviewed and explicitly acknowledged;
- postflight has a nonzero repair count or a survivor-count mismatch;
- Track B discovery executor is nonzero, protocol is not `off`, or agent jobs are pending;
- doctor is blocked, heartbeat is stale/offline, profile is locked, or oldest claimable age exceeds
  12 hours;
- the canary job/run/candidate/artifact/evidence/process/profile chain is incomplete;
- supervised execution exits early, leaks a process group, or fails its fresh doctor postflight;
- rollback rehearsal is incomplete;
- an expected credential, host, environment, or authority record is unavailable.

Do not rewrite an applied migration. After migration 040, backout is pause-and-fix-forward unless a
separately approved database restore is required.

## 1. Freeze one exact release SHA

After the PR is merged and local `main` is fast-forwarded to `origin/main`, record:

```bash
TRACK_BC_SHA="$(git rev-parse --verify HEAD)"
TRACK_BC_BASE_SHA="846f82869945fb742eeba3c78ec5c52ece16b6b6"
test "$(git rev-parse --verify origin/main)" = "$TRACK_BC_SHA"
test "${#TRACK_BC_SHA}" -eq 40
git merge-base --is-ancestor "$TRACK_BC_BASE_SHA" "$TRACK_BC_SHA"
```

The value must be the merge result, not the feature-branch head or the earlier `846f8286`
baseline. Store it in the private authority record and use it for every later comparison.

## 2. Use separate clean release and gate worktrees

Create or select two distinct clean, detached worktrees at `TRACK_BC_SHA`. The release worktree is
the immutable Docker Compose source and must never be bootstrapped, compiled, tested, or used for
web dependency installation. The gate worktree runs local source/web checks and may therefore
contain ignored generated caches after its initial cleanliness check. Do not use the dirty primary
checkout or the historical `egp-ops-main` checkout for either role.

Confirm both worktrees start with the exact SHA, no staged/unstaged changes, and no untracked or
ignored executable Python inputs under `apps/`, `packages/`, `pyproject.toml`, or `uv.lock`. Keep the
release worktree pristine for every later `release_compose.sh` command. The release wrapper and Mac
runner repeat their own source checks. Release Compose uses only the tracked base file and tracked
release overlay: it ignores an implicit `docker-compose.override.yml` and rejects every caller
`-f`/`--file` or `--project-directory` override.

## 3. Run source and release gates

From the two clean worktrees, save bounded outputs under the private evidence directory. Resolve
and inspect the images from the pristine release worktree before local Python gates create ignored
executable Python cache files in the gate worktree. Those files must never enter the Docker build
context, and the release wrapper must continue to reject them.

```bash
TRACK_BC_RELEASE_ROOT="<clean-release-worktree>"
TRACK_BC_GATE_ROOT="<clean-gate-worktree>"
test "$TRACK_BC_RELEASE_ROOT" != "$TRACK_BC_GATE_ROOT"
test "$(git -C "$TRACK_BC_RELEASE_ROOT" rev-parse --verify HEAD)" = "$TRACK_BC_SHA"
test "$(git -C "$TRACK_BC_GATE_ROOT" rev-parse --verify HEAD)" = "$TRACK_BC_SHA"
test -z "$(git -C "$TRACK_BC_RELEASE_ROOT" symbolic-ref --quiet HEAD 2>/dev/null || true)"
test -z "$(git -C "$TRACK_BC_GATE_ROOT" symbolic-ref --quiet HEAD 2>/dev/null || true)"
test -z "$(git -C "$TRACK_BC_RELEASE_ROOT" status --porcelain=v1 --untracked-files=all)"
test -z "$(git -C "$TRACK_BC_GATE_ROOT" status --porcelain=v1 --untracked-files=all)"

find_ignored_runtime_executable() {
  local root="$1"
  local ignored_path
  while IFS= read -r ignored_path; do
    case "$ignored_path" in
      pyproject.toml|uv.lock|*.py|*.pyc|*.pth|*.so|*.pyd)
        printf '%s\n' "$ignored_path"
        return 0
        ;;
    esac
  done < <(
    git -C "$root" ls-files --others --ignored --exclude-standard -- \
      pyproject.toml uv.lock apps/api apps/worker packages
  )
}
test -z "$(find_ignored_runtime_executable "$TRACK_BC_RELEASE_ROOT")"
test -z "$(find_ignored_runtime_executable "$TRACK_BC_GATE_ROOT")"

(cd "$TRACK_BC_RELEASE_ROOT" && ./scripts/release_compose.sh build migrate api webhook-executor \
  crawler-agent-inbox-executor discovery-executor)
API_IMAGE="$(cd "$TRACK_BC_RELEASE_ROOT" && ./scripts/release_compose.sh images -q api)"
WORKER_IMAGE="$(cd "$TRACK_BC_RELEASE_ROOT" && ./scripts/release_compose.sh images -q discovery-executor)"
test -n "$API_IMAGE"
test -n "$WORKER_IMAGE"

(cd "$TRACK_BC_GATE_ROOT" && ./scripts/bootstrap_python_env.sh)
(cd "$TRACK_BC_GATE_ROOT" && .venv/bin/python -m compileall apps packages scripts)
(
  cd "$TRACK_BC_GATE_ROOT"
  .venv/bin/python scripts/check_migration_manifest.py --check
)
(cd "$TRACK_BC_GATE_ROOT" && .venv/bin/python -m ruff check apps packages tests scripts)
(
  cd "$TRACK_BC_GATE_ROOT"
  git diff --name-only -z --diff-filter=ACMR \
    "$TRACK_BC_BASE_SHA..$TRACK_BC_SHA" -- '*.py' \
    | xargs -0 .venv/bin/python -m ruff format --check
)
(cd "$TRACK_BC_GATE_ROOT" && .venv/bin/python -m pytest tests apps packages -q)
(cd "$TRACK_BC_GATE_ROOT/apps/web" && npm ci && npm run typecheck && npm run build)
(cd "$TRACK_BC_GATE_ROOT" && EGP_EXPECTED_RELEASE_SHA="$TRACK_BC_SHA" \
  ./scripts/smoke_runtime_images.sh "$API_IMAGE" "$WORKER_IMAGE")
```

Hosted jobs that fail before their first step solely because of the standing GitHub billing lock
are unavailable, not passing. The accepted local gates and exact candidate SHA remain mandatory.
The formatter gate is intentionally limited to Python files changed by this campaign from the
frozen pre-campaign main SHA; the baseline has known unrelated formatter drift. The full-tree Ruff
lint and both full Python suites remain mandatory.

Unless a later section explicitly names the native Mac worktree, run local Python/verifier commands
from `TRACK_BC_GATE_ROOT` and every `release_compose.sh` command from the still-pristine
`TRACK_BC_RELEASE_ROOT`.

## 4. Confirm mutation authority

Re-read the private authority record. Confirm the exact target environment, database, artifact
bucket, Lightsail project, Mac, canary profile, and maintenance window. This step authorizes only
the listed campaign. It does not authorize agent activation, fault injection, unrelated data
repair, or broad cleanup.

## 5. Quiesce writers and back up state

Before migration, stop the old Mac watcher and every Track B discovery writer. Quiesce application
paths that can enqueue, claim, or otherwise mutate crawl/candidate state for the complete interval
from the final preflight recheck through migration postflight. The migration advisory lock
serializes migrators; it does not fence application writers. Keep the public API available only if
the approved maintenance controls can enforce that write boundary. Prove zero queued/running crawl
runs and zero live discovery leases with a read-only query saved privately.

With the production backup environment already loaded by the operator-controlled secret manager:

```bash
scripts/pg_backup.sh
scripts/artifact_backup.sh
```

Record the database dump name, SHA-256 sidecar, artifact mirror result, source/destination bucket
identity, timestamps, and restore owner. A successful command without a checksum and retrievable
off-host object is not accepted backup evidence.

## 6. Run migration-039 count-only preflight

With `DATABASE_URL` present only in the process environment:

```bash
(
  cd "$TRACK_BC_GATE_ROOT"
  .venv/bin/python scripts/candidate_integrity_preflight.py \
    --migrations-dir packages/db/src/migrations \
    --phase pre
) > <private-evidence-dir>/candidate-preflight.json
```

Require `active_run_count=0`. Record `candidate_count`, both manifest digests, and all seven repair
counts. Every count is collected from one PostgreSQL `REPEATABLE READ READ ONLY` snapshot. The
command recomputes the SHA-256 of migrations 038 and 039 and rejects missing, duplicate, or
byte-mismatched manifest entries. `ready_with_repairs` is reviewable, not automatic approval.
Migration 039 deletes only the reported orphan/cross-tenant-run category; explicitly acknowledge
that exact count before continuing. Stop on any unexplained category or count.

## 7. Apply migrations 038-040 with one migrator

Immediately before migration, while writers remain quiesced, rerun the phase-`pre` command and
require the active-run count and all candidate/repair counts to match the approved receipt. This
closes the procedural interval between count approval and the advisory-locked migrator. Then run
exactly one release-wrapper migration container:

```bash
(cd "$TRACK_BC_RELEASE_ROOT" && ./scripts/release_compose.sh run --rm migrate)
```

The runner loads the tracked migration bytes and verifies them against `manifest.sha256` before
opening the database connection. It then obtains the nonblocking PostgreSQL advisory lock before
reading or creating its ledger. Under the acquired lock, ledger creation and reads, stored-digest
validation or backfill, and pending migration application use the already verified bytes. A legacy
ledger row with a null digest is backfilled only after the current file matches the manifest; any
later byte mismatch fails closed. Lock contention or digest mismatch is a stop condition, not a
retry loop. Then run postflight using the exact preflight candidate count and approved orphan-run
deletion count:

```bash
(
  cd "$TRACK_BC_GATE_ROOT"
  .venv/bin/python scripts/candidate_integrity_preflight.py \
    --migrations-dir packages/db/src/migrations \
    --phase post \
    --expected-pre-candidate-count <pre-candidate-count> \
    --expected-deleted-orphan-run-count <approved-delete-count>
) > <private-evidence-dir>/candidate-postflight.json
```

Require `status=ready`, `migration_038_applied=true`, `migration_039_applied=true`, every repair
count zero, and `survivor_delta_matches=true`. This candidate preflight does not attest migration
040. Capture the separate 040 ledger/digest and constraint proof with the frozen Python environment;
the database URL remains in the process environment rather than a command argument, and the
bounded output stays private:

```bash
(
  cd "$TRACK_BC_GATE_ROOT"
  .venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

from psycopg import connect

migration_name = "040_exact_canary_failure_codes.sql"
manifest_lines = (
    Path("packages/db/src/migrations/manifest.sha256")
    .read_text(encoding="utf-8")
    .splitlines()
)
manifest_matches = []
for line in manifest_lines:
    parts = line.split(maxsplit=1)
    if len(parts) == 2 and parts[1] == migration_name:
        manifest_matches.append(parts[0])
if len(manifest_matches) != 1:
    raise SystemExit("expected exactly one migration-040 manifest entry")

database_url = os.environ["DATABASE_URL"]
if database_url.startswith("postgresql+psycopg://"):
    database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
with connect(database_url) as connection:
    with connection.cursor() as cursor:
        cursor.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute(
            "SELECT version, sha256 FROM schema_migrations "
            "ORDER BY version DESC LIMIT 1"
        )
        ledger_row = cursor.fetchone()
        cursor.execute(
            "SELECT conname, pg_get_constraintdef(oid, true) "
            "FROM pg_constraint "
            "WHERE conrelid = 'public.discovery_jobs'::regclass AND conname = %s",
            ("discovery_jobs_last_error_code_check",),
        )
        constraint_rows = cursor.fetchall()
        connection.rollback()

expected_ledger = (migration_name, manifest_matches[0])
if ledger_row != expected_ledger:
    raise SystemExit("migration-040 ledger tail or digest mismatch")
if len(constraint_rows) != 1:
    raise SystemExit("expected exactly one migration-040 constraint")
required_codes = {
    "browser_start_failed",
    "pagination_control_hidden",
    "pagination_next_click_failed",
    "pagination_page_change_timeout",
    "pagination_unexpected_no_results",
    "pagination_site_error",
    "canary_target_mismatch",
    "canary_proof_invalid",
}
constraint_definition = constraint_rows[0][1]
missing_codes = sorted(code for code in required_codes if code not in constraint_definition)
if missing_codes:
    raise SystemExit("migration-040 constraint vocabulary mismatch")
print(
    json.dumps(
        {
            "constraint_definition": constraint_definition,
            "constraint_name": constraint_rows[0][0],
            "required_codes_present": True,
            "sha256": ledger_row[1],
            "version": ledger_row[0],
        },
        sort_keys=True,
    )
)
PY
) > <private-evidence-dir>/migration-040-attestation.json
```

Require exactly one ledger row whose version is `040_exact_canary_failure_codes.sql` and whose
SHA-256 equals its tracked `manifest.sha256` entry. Require exactly one constraint row containing
the browser, pagination, target, and proof failure codes used by the exact canary. Also confirm the
migration ledger ends at 040 and require `/ready` to report `pending_count=0` and
`unexpected_count=0`.

## 8. Deploy Track B Python roles

Use the trusted release wrapper for every Compose invocation so `EGP_RELEASE_SHA` remains derived
from the clean source instead of caller input. The wrapper rejects caller `--project-directory`
and Compose-file overrides and does not load an implicit override; do not bypass it with plain
Compose:

```bash
(cd "$TRACK_BC_RELEASE_ROOT" && ./scripts/release_compose.sh up -d \
  --scale discovery-executor=0 api webhook-executor crawler-agent-inbox-executor)
```

Deploy the public web/Caddy/Vercel surface through its existing governed path. Do not start the
Linux discovery executor; e-GP/Cloudflare blocks that browser topology and Track C is the selected
MVP execution plane.

## 9. Prove immutable Track B identity

For `migrate`, `api`, `webhook-executor`, `crawler-agent-inbox-executor`, and
`discovery-executor`, capture:

- image digest;
- the inspected immutable image ID (`sha256:<64 hex>`);
- the matching container image ID from the container created for that role;
- OCI `org.opencontainers.image.revision`;
- baked `EGP_RELEASE_SHA`;
- comparison to `TRACK_BC_SHA`.

Use `scripts/smoke_runtime_images.sh` and bounded `docker inspect` allowlists. Do not save full
container environments. Every role must match even though discovery executor is scaled to zero.
For that zero-runtime role, create a stopped container from the release service solely for bounded
identity inspection, verify its image ID matches the inspected image, then remove it before the
executor-zero proof. Do not run its command.

## 10. Prove Track B discovery executor is zero

Use the release wrapper's Compose `ps` output and the platform/container inventory. Require zero
running replicas and zero externally started discovery-dispatch processes on Lightsail. Save only
role/count/identity evidence.

## 11. Prove crawler-agent protocol is off

Inspect only the API's `EGP_CRAWLER_AGENT_PROTOCOL` value and require `off`. Do not infer it from a
source default. Do not send an agent claim or enable shadow/primary during this campaign.

## 12. Prove legacy routing

Run a tenant-scoped read-only query privately. Require the intended profile's
`execution_backend=legacy` and zero target pending jobs with `execution_backend=agent`. Do not
rewrite existing agent jobs as part of this campaign; a nonzero count is a stop condition.

## 13. Cut the Mac to the same exact SHA

Stop the historical watcher and tunnel without deleting its checkout or evidence. Use a clean Mac
worktree at `TRACK_BC_SHA`, bootstrap its frozen environment, and keep `.env.remotecrawl` mode 0600
outside Git. Confirm:

```bash
scripts/run_remote_crawl.sh check
scripts/run_remote_crawl.sh wait-database
```

The runner derives and exports `EGP_RELEASE_SHA` from the clean checkout. The Mac SHA must equal the
Track B image label/env SHA. Keep one browser worker and one watcher.

## 14. Warm and repair the persistent Chrome profile

Use the configured non-synced persistent profile and real Mac Chrome:

```bash
scripts/run_remote_crawl.sh warm-profile
scripts/run_remote_crawl.sh doctor
```

If Cloudflare requests interaction, the designated operator completes it in the foreground and
reruns warm/doctor. Require doctor `ready`, an empty typed blocker list, and a free profile lock.
Do not bypass `profile_operator_action_required` or replace the profile during the canary.

## 15. Record heartbeat and backlog evidence

From the doctor JSON, record only:

- heartbeat online and age no more than 90 seconds;
- queue counts and oldest claimable age;
- profile ready/unlocked;
- empty blockers.

An empty claimable queue legitimately has `oldest_claimable_age_seconds=null`; otherwise the age
must be present. Warn at six hours and stop at twelve hours.

Build a private runtime-evidence JSON containing a UTC `collected_at`, the exact source/Mac SHA,
OCI+baked revisions plus matching `image_id`/`container_image_id` for the five Python roles,
executor replica count, protocol value, profile and pending-job backend counts, and the doctor
object. The doctor heartbeat must include an absolute UTC `reported_at`; an age-only heartbeat is
not sufficient. Collect the inputs as one bounded evidence operation and verify them immediately:

```bash
(
  cd "$TRACK_BC_GATE_ROOT"
  .venv/bin/python scripts/track_bc_verify.py runtime \
    --evidence <private-evidence-dir>/runtime-input.json \
    --expected-release-sha "$TRACK_BC_SHA" \
    --output <private-evidence-dir>/runtime-receipt.json
)
```

Require `status=accepted`.

## 16. Run the observation and ingestion canaries

First run a read-only observation canary with the exact approved keyword. This launches real Mac
Chrome, uses the same page parser and pagination state machine as production discovery, fixes the
configured ceiling at 15 pages, and disables all database persistence. It must prove that pages
1 through 5 were visited in order, that an eligible invitation was recognized on page 2 or later,
and that the scan ended with a typed successful terminal outcome. `next_control_absent` or
`next_control_disabled` may end the scan after page 5; `max_pages_reached` is valid only after page
15.

```bash
scripts/run_remote_crawl.sh observe-canary \
  <private-evidence-dir>/canary-target.json \
  --receipt <private-evidence-dir>/observation-receipt.json
```

The observation command reads the same mode-0600 exact target used by ingestion, acquires the
shared persistent-profile lock before Chrome, and derives the keyword and target fingerprint from
that file. Require the sanitized observation receipt to have schema 1, stage `observation`, status
`accepted`, the exact release SHA, the same target fingerprint as the later schema-2 canary
receipt, `browser_started=true`, `page_sequence` beginning
`[1,2,3,4,5]`, `eligible_invitation_page>=2`, `max_pages_per_keyword=15`,
`persistence_disabled=true`, and `shared_parser=true`.

Then select one separately authorized, low-volume live legacy job for ingestion. Record the exact
contract in a mode-0600 private target file. The file must contain exactly the following fields;
all IDs are canonical UUIDs and `keyword` is the single normalized keyword assigned to the job:

```json
{
  "contract_version": 1,
  "kind": "exact_ingestion_canary",
  "tenant_id": "<tenant-uuid>",
  "job_id": "<job-uuid>",
  "profile_id": "<profile-uuid>",
  "keyword": "<exact-approved-keyword>",
  "live": true,
  "execution_backend": "legacy",
  "browser_required": true,
  "max_pages_per_keyword": 15
}
```

Run exactly that job:

```bash
chmod 600 <private-evidence-dir>/canary-target.json
scripts/run_remote_crawl.sh crawl-canary \
  <private-evidence-dir>/canary-target.json \
  > <private-evidence-dir>/crawl-one-summary.json
```

Require `processed_count=1` and a successful disposition. A browser blocker, semantic failure,
unexpected target, target/profile/keyword/backend/page-cap mismatch, lease loss, missing ordered
browser proof, or missing terminal result stops the campaign. The dispatcher requires agent
protocol `off`, one-shot limit one, and a private non-symlink target file owned by the operator. It
atomically claims only the exact live legacy job whose profile, keyword membership, browser mode,
and 15-page cap match the contract; it cannot claim an older unrelated job.

## 17. Verify the full canary chain

Create a mode-0600 schema-2 private request containing exactly `schema_version`, the unchanged
`target` object from the ingestion target file, and the correlated canonical `run_id`:

```json
{
  "schema_version": 2,
  "target": {
    "contract_version": 1,
    "kind": "exact_ingestion_canary",
    "tenant_id": "<tenant-uuid>",
    "job_id": "<job-uuid>",
    "profile_id": "<profile-uuid>",
    "keyword": "<exact-approved-keyword>",
    "live": true,
    "execution_backend": "legacy",
    "browser_required": true,
    "max_pages_per_keyword": 15
  },
  "run_id": "<run-uuid>"
}
```

A caller cannot select `profile_dir`; the verifier resolves the persistent profile from the same
production configuration used by the browser. The verifier reads the job, profile, keyword, run,
later-page candidate, project, document, and capture chain in one PostgreSQL read-only
transaction, checks the correlated artifact through the configured store, validates the
bounded/redacted JSONL evidence, probes the recorded child PID, and checks the configured profile
lock:

```bash
(
  cd "$TRACK_BC_GATE_ROOT"
  .venv/bin/python scripts/track_bc_verify.py canary \
    --request <private-evidence-dir>/canary-request.json \
    --expected-release-sha "$TRACK_BC_SHA" \
    --output <private-evidence-dir>/canary-receipt.json
)
```

Require an exact target match, dispatched job, succeeded correlated run finished no more than one
hour before collection, zero accepted candidates, and at least one persisted candidate from page 2
or later for the exact keyword. Artifact acceptance additionally requires a successful positive
`document_capture_attempts` row plus a document for the same tenant, project, and run; an older
document on the same project is insufficient. Require successful artifact lookup, browser start,
contiguous page proof beginning with pages 1 through 5 under the configured maximum of 15, a typed
successful terminal scan, later-page persistence, and exactly one matching
`canary_proof_validated` event before the final `dispatch_finished`. Also require ordered,
redacted, correlated exact-SHA evidence, dead child PID, and a free profile lock. The accepted
canary receipt has schema 2 and contains no target IDs or digest.

## 18. Run a bounded supervised interval

Use two minutes initially. The runtime verifier deliberately rejects evidence older than five
minutes, so collect a separate fresh `supervision-preflight-input.json` immediately before this
step; do not replace the earlier runtime-stage receipt used by the chronological final bundle. The
command validates all supplied runtime evidence before spawning, uses fixed watcher/doctor argv,
terminates the entire watcher process group at the deadline, and performs a fresh doctor postflight
against the still-fresh immutable inputs. It prints a sanitized receipt:

```bash
scripts/run_remote_crawl.sh supervise 120 \
  --evidence <private-evidence-dir>/supervision-preflight-input.json \
  > <private-evidence-dir>/supervised-receipt.json
```

Require `deadline_reached`, `process_group_reaped`, and `postflight_runtime_accepted` all true.
Inspect queue age, heartbeat continuity, failure rate, process count, and profile lock during the
window. Do not install launchd after an early exit or cleanup escalation failure.
SIGTERM or SIGHUP is a controlled rejection: the supervisor writes a sanitized
`supervision_interrupted` receipt and reaps the complete watcher/browser process group.

## 19. Rehearse rollback, bundle evidence, then install launchd

Before unattended activation, rehearse the recovery sequence:

1. `scripts/install_launchd.sh uninstall`;
2. prove watcher stopped and no browser child/process group remains;
3. close the test tunnel and prove it is absent;
4. prove Track B discovery executor remains zero;
5. restore the tunnel manually and rerun database readiness without installing the watcher;
6. close that manual tunnel again and prove the database port is no longer satisfied by it.

Create a fresh rollback JSON with schema 1, stage `rollback`, status `rehearsed`, exact release SHA,
UTC `observed_at`, and exactly these true checks: `launchd_uninstalled`, `watcher_stopped`,
`tunnel_closed`, `discovery_executor_zero`.

Create the private bundle input containing exactly one runtime-stage receipt, one observation
receipt, one schema-2 canary receipt, one supervised receipt, and the rollback object. Their UTC
timestamps and array order must satisfy
`runtime <= observation <= canary <= supervised <= rollback`; a missing observation, downgraded
schema-1 canary, observation/canary target-fingerprint mismatch, reordered stage, future-dated
receipt, or newly re-stamped old input is rejected. Verify and save the sanitized schema-2 final
receipt. Load `TRACK_BC_MAX_BUNDLE_AGE_SECONDS` from the private authority record before running
the command:

```bash
test "$TRACK_BC_MAX_BUNDLE_AGE_SECONDS" -gt 0 &&
test "$TRACK_BC_MAX_BUNDLE_AGE_SECONDS" -lt 86400 &&
(
  cd "$TRACK_BC_GATE_ROOT"
  .venv/bin/python scripts/track_bc_verify.py bundle \
    --evidence <private-evidence-dir>/bundle-input.json \
    --expected-release-sha "$TRACK_BC_SHA" \
    --max-age-seconds "$TRACK_BC_MAX_BUNDLE_AGE_SECONDS" \
    --output <private-evidence-dir>/acceptance-bundle.json
)
```

This explicit verification is a procedural campaign control, not a hard installer-enforced limit:
the unchanged installer independently re-verifies with its existing 86,400-second default. The
operations record and immediate sequencing must therefore enforce the tighter campaign window
rather than treating the installer default as equivalent. If a hard activation-boundary limit is
required, stop and first land a separately tested installer contract that accepts the approved
maximum age.
Finally, and only while the bundle remains within the approved tighter window:

```bash
scripts/install_launchd.sh install \
  --acceptance-evidence <private-evidence-dir>/bundle-input.json
scripts/install_launchd.sh status
```

Add `--with-warm` only when the operator has approved the periodic Chrome warm task. The installer
re-verifies the bundle against its own clean current HEAD before any launchctl or filesystem
mutation. It bootstraps `com.egp.pg-tunnel`, requires that exact launchd label to reach
`state = running`, runs database readiness, and immediately rechecks the managed label before it
can bootstrap `com.egp.remote-crawl`; a leftover manual tunnel cannot satisfy activation. It then
requires the watcher label to reach `state = running` and requires the guarded crawler doctor to
succeed. Any render, teardown, bootstrap, state, database, or doctor failure unloads labels loaded
by that invocation, waits for their absence, removes the rendered plists, and returns nonzero.
`uninstall` also waits for every known label to disappear before removing its plist. `status` and
`uninstall` intentionally remain available without evidence.

## Completion record

The public MVP is accepted only when the operations record contains:

- merged SHA and local/origin equality;
- source, web, release, and image gate results;
- authority record and maintenance window;
- database/artifact backup checksums and restore owner;
- migration pre/post receipts and approved deletion count;
- five-role OCI/baked SHA evidence;
- executor-zero, protocol-off, and legacy-routing proof;
- Mac exact-SHA, doctor, heartbeat, backlog, and profile evidence;
- accepted read-only observation receipt proving ordered pages 1 through 5;
- one-crawl summary and accepted schema-2 ingestion canary receipt;
- accepted supervised receipt;
- rollback rehearsal and accepted final bundle;
- post-install launchd status and a rollback owner.

Keep activation reversible. Do not claim the HTTP crawler-agent architecture, multi-browser
concurrency, fault injection, RLS, or broader production readiness from this Track B + C campaign.
Merging this source change does not execute either live canary, deploy a release, or activate the
Mac watcher; those remain separately authorized runtime operations requiring the evidence above.
