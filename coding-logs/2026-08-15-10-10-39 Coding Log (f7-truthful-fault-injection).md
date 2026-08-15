# Coding Log: F7 Truthful Fault Injection

## Status

- State: LOCAL GATES GREEN; FORMAL REVIEW IN PROGRESS
- DREP: `EGP-F7-TRUTHFUL-FAULT-INJECTION-20260815`
- Branch: `fix/f7-truthful-fault-injection`
- Baseline: `d2bc0d807a6806ba54ec802c6b02f2cc2b5bf82e`
- Scope: canonical F7 only; no deployment or activation

## Preflight evidence (2026-08-15T10:10:39+07:00)

- Prompt visibility: the user attached both current `g2-planning` and `g2-coding` skill blocks to
  this prompt. Complete on-disk instructions were independently read. SHA-256:
  `g2-planning/SKILL.md=9fc18c72a2c9050aaf2b9ed2cae706d97af7ce62075cc0170dbdf163fa57cb32`,
  `g2-coding/SKILL.md=7dad7b21756f1bf408f3ad64e1bc06ff48fa718a985e7c7958ed4baf5daa2a57`.
- v2 proof: current proposal runner and reference declare `g2-drep-proposal-v2`; v1 is rejected.
- Standalone `g2-check`: unavailable. Formal review route is QCHECK plus existing `g-check`.
- DeepSeek use: `0`. No proposal compile, proposal request, or direct-write delegation occurred.
- Local-only `g2-doctor`: 0 failures; two expected warnings because external/tool-round probes were
  not authorized and were skipped.
- Repository main proof: local `main`, local `origin/main`, and `git ls-remote origin
  refs/heads/main` all returned `d2bc0d807a6806ba54ec802c6b02f2cc2b5bf82e`.
- GitHub: `gh pr list --state open` returned an empty list. No F7 PR exists.
- No F7 branch/worktree existed before this session.
- PR #202 was not recreated. F6/PR #208 was not modified.

## Protected primary checkout baseline

Primary root: `/Users/subhajlimanond/dev/egp`, branch `main`, HEAD
`d2bc0d807a6806ba54ec802c6b02f2cc2b5bf82e`.

Protected status:

```text
 M coding-logs/2026-07-22-13-39-00 Coding Log (crawl-result-retry-and-recrawl-batches).md
 M coding-logs/2026-08-06-10-00-00 Coding Log (pr-canary-01-remediation).md
?? coding-logs/2026-07-27-07-14-32 Coding Log (soft-launch-architecture-hardening).md
?? coding-logs/2026-08-13-09-35-59 Coding Log (senior-review-reconciled-drep).md
?? coding-logs/2026-08-13-09-35-59 DREP (senior-review-reconciled-hardening).md
?? docs/TOR KEYWORDS.md
?? test.sqlite3
```

The primary `.codex/coding-log.current` pointed at the senior reconciliation log and was not
changed. This worktree has its own explicitly authorized ignored pointer to this F7 log.

## Worktree ledger

Pre-existing, user-owned, preserve:

- `/Users/subhajlimanond/dev/egp` — `main` at baseline; dirty primary.
- `/Users/subhajlimanond/dev/egp-ops-main` — detached at `722b1e0e`.
- `/Users/subhajlimanond/dev/egp-phase1-u1` — `plan/phase2-next-session-handoff` at `622d2957`.
- `/Users/subhajlimanond/dev/egp-phase2-u5` — `build/reproducible-release-gates` at `d10949b7`.
- `/Users/subhajlimanond/dev/egp-phase2-u6` — `build/harden-runtime-images` at `2081ac7a`.
- `/Users/subhajlimanond/dev/egp-u8` — `fix/discovery-poll-loop-unbound-result` at `dba22cf8`.

Session-created:

- `/Users/subhajlimanond/dev/egp-f7-truthful-fault-injection` — branch
  `fix/f7-truthful-fault-injection`, baseline `d2bc0d80`, purpose implementation/review/delivery,
  creator primary, expected disposition remove after exact-SHA merge landing and artifact audit.

## Repository exploration

- RepoPrompt bound root: `/Users/subhajlimanond/dev/egp` for planning discovery, then exact isolated
  candidate root `/Users/subhajlimanond/dev/egp-f7-truthful-fault-injection`.
- Context Builder inspected the canonical F7/reconciliation logs, dispatcher service/executor,
  worker entrypoint/workflow, run and candidate repositories, shared failure vocabulary, existing
  synthetic and process-lifecycle tests, Compose, and CI.
- Material finding: PR #202 `_simulate_fault()` runs after `create_run()` but before `Popen`; its
  tests explicitly require no subprocess. `DiscoverySpawnError`, non-retriable, and generic outer
  handlers log/rethrow without failing the reserved run. Real cleanup is presently reached only by
  lease cancellation, timeout, and negative signal paths.
- Canonical contract: real timeout/nonzero/missing/signal outcomes, operator/test default-denial
  gate, bounded audit evidence, and terminal reserved runs. F5's generic all-path candidate/run
  reconciliation remains downstream and out of scope.

## Adversarial planning challenge

Read-only `terra_support` challenge completed. Accepted findings:

- Nonzero and missing-result current branches can leave runs queued/running.
- The acceptance oracle must use a real child process/process group, not exception mapping alone.
- Do not claim F5 by broadening best-effort candidate reconciliation.
- Persistent-profile failure state is asymmetric; preserve current semantics and prove cleanup,
  but do not redesign profile health in F7.
- Repository `fail_run_if_active()` capability alone is insufficient without dispatcher wiring.

Rejected/limited finding: mandatory real-PostgreSQL inside the smallest RED test is not necessary
to prove process cleanup. The named RED uses a real child plus a run-repository state spy; existing
repository/PostgreSQL suites and full gates independently verify persistence semantics. If the
affected integration evidence reveals a DB mismatch, implementation stops for DREP revision.

## DREP classification

- `deepseek_budget: 0`
- `selected_deepseek_slice: NONE`
- `S1 PRIMARY`, `S2 PRIMARY`
- Q0: explicit g2 invocation, protected worktree, healthy local route, and strong oracle exist.
- Q1 decisive: persistent process-group cleanup and durable run terminalization are
  lifecycle/judgment-bound. This prohibits a proposal slice despite route health.
- Stop line: `PRIMARY`.

## RED / GREEN evidence

### Locked acceptance tests and expected RED (2026-08-15T10:17:06+07:00)

- `tests/phase1/test_truthful_fault_injection.py` SHA-256
  `fdb9d8fd460b55590314a6de0795629a8baf0c983f8b07f95df50f9e79260a1a`.
- `tests/phase2/test_discovery_executor.py` SHA-256
  `63f86e279592417437f0a6c6e370854971e156a54e7a4205ab943431a120d7ef`.
- Named RED command:
  `python -m pytest tests/phase1/test_truthful_fault_injection.py::test_every_injected_fault_terminalizes_run -q`.
  Result: `5 failed`. Each accepted mode reserved one run and left it `queued`; the failure reached
  the locked terminal-state assertion before the later Popen assertion. This is the predicted
  synthetic pre-spawn/non-terminal behavior.
- Unknown-mode RED: `1 failed`; current code raised raw `ValueError` after reservation rather than
  the locked non-retriable `dispatch_exception` terminalization.
- Operator-gate RED: `5 failed`; argparse rejected the absent `--fault-mode` CLI contract before
  any runtime construction. This is the predicted missing entrypoint, not unrelated setup drift.
- Acceptance assertions are now locked. Production implementation may not weaken or rewrite them.

## Wiring and gates

### Full-suite wiring RED and DREP revision

- First full suite: `1727 passed, 3 skipped, 3 failed`.
- Accepted F7 wiring RED: two `tests/operations/test_env_template.py` tests proved the new runtime
  and Compose variable was missing from `deploy/.env.production.example`. The DREP was revised to
  add `F13/T7`; the template value is locked to `false` and adds no mode or activation.
- Environment-only failure: `test_pg_backup_sh_succeeds_with_local_fs_target_against_temp_postgres`
  could not find the clean worktree's `.venv/bin/python`. This is not product behavior; rerun uses
  a temporary ignored worktree-local symlink to the already verified primary `.venv`.
- Full-tree Ruff check: PASS.
- Touched-file Ruff format check: PASS. Full-tree format check reports 38 pre-existing files
  outside F7 that would be reformatted; they remain untouched and the baseline drift is recorded.
- Python compileall: PASS.
- `uv lock --check`: unavailable because no `uv` executable exists in the primary environment or
  standard machine paths; no ad hoc dependency installation was performed.

## QCHECK and formal review

### Independent QCHECK disposition

The permitted second and final `terra_support` task completed read-only QCHECK. RepoPrompt's
independent review reached the same material conclusions. No product code, lifecycle artifact,
Git state, or acceptance decision was delegated.

- Accepted and fixed: `fault_injection_terminalized` previously followed best-effort repository
  calls. Run transition and candidate reconciliation now return explicit outcomes; the success
  event requires a confirmed active-to-failed transition, while repository failure emits
  `fault_injection_terminalization_failed`. A negative test proves no false success claim.
- Accepted and fixed: the internal request seam could bypass the CLI gate. Every injected request
  now requires an explicit dispatcher authorization capability; normal API/background dispatchers
  default false, while the standalone executor sets it only after the full gate passes.
- Accepted and fixed: denial occurred after aggregate-log rotation. Authorization now precedes any
  rotation/runtime/job-claim side effect, and the denial matrix proves rotation is untouched.
- Accepted and fixed: an arbitrary invalid mode could be echoed to stderr. Invalid input is now
  represented only as `fault_mode=invalid`; the secret-like test input is absent from captured
  output.
- Accepted and fixed: a one-job limit could still fault an unintended queued tenant job. Operator
  injection now requires an exact pre-created canary job UUID; processor/repository claim queries
  constrain selection to that UUID. A two-job integration test proves the unrelated job remains
  pending.
- Accepted and fixed: CLI exit zero did not prove the requested fault was observed. The one-shot
  result must contain exactly one disposition with the mode's exact failure code; mismatch or an
  empty queue returns 4 and emits `fault_injection_mismatch`.
- Accepted and fixed: API/worker mode vocabulary drift now has an executable parity test.
- Procedural finding resolved: the harness and canonical acceptance test are included in the
  intended staged source set before formal review/commit.
- Limited residual risk: the smallest lifecycle oracle uses real children and repository spies;
  exact targeted claiming uses SQLite. Full repository tests and the complete 1,737-test suite are
  green, but no live external PostgreSQL fault campaign was run. No deployment/activation is
  authorized, so this is recorded without claiming runtime acceptance.

Formal-review follow-up found five further risks; all were remediated before the final gates:

- Invalid-mode redaction is now based on membership in the fixed vocabulary, independent of which
  earlier denial gate wins. Both default-disabled and enabled secret-like cases are tested.
- The target must match both an expected tenant UUID and an exact non-live job UUID. Repository
  probe and claim predicates enforce all three properties; variable naming alone is not treated as
  a canary designation.
- Injected processors force the target queue row to a terminal failed disposition even for timeout,
  nonzero, and missing-result codes that normal jobs would retry. The operator cannot leave a
  fault-enabled row scheduled for a later ordinary crawl.
- Setup failures after run reservation now execute injected terminalization, and the final cleanup
  explicitly drains a child after a last-resort process-group kill. New negative tests cover both.
- Authorized fault preflight bypasses the host-shared e-GP circuit and persistent-profile warm path;
  the fixed harness cannot contact e-GP or mutate the live browser profile before launch.

The final formal-review pass then found one remaining success-oracle defect and two isolation
considerations. All were closed before delivery:

- Exit zero now requires a `fault_verified` disposition. That disposition exists only when the
  dispatcher confirms durable run transition, successful candidate reconciliation, the exact
  fixed harness command, and the mode-specific child return code plus failure code. A missing module,
  wrong positive exit, or terminalization failure cannot masquerade as a successful campaign.
- An authorized production dispatcher is bound to its pinned mode; a direct request cannot override
  it. Unknown direct-test input is represented only by the fixed `invalid` sentinel in events and
  durable errors.
- Canary rows carry the reserved `fault_injection` trigger in addition to tenant/job/non-live
  predicates. Normal built runtimes exclude that trigger, preventing an ordinary executor from
  racing the fault executor. SQLite integration proves both the targeted and ordinary sides.
- The last exceptional-path review found worker-log resolution and timeout diagnostic drain outside
  the terminalization-safe region. Log resolution is now best-effort like log creation, while the
  timeout handler kills first, treats diagnostics as best-effort, and terminalizes before returning
  the verified typed failure. Dedicated negative tests prove neither path orphans the reserved run.

The exact staged-snapshot review after the queue-snapshot remediation found one further P1 and
three test-strength considerations. The P1 received a new acceptance test before production change:

- Confirmed RED: a disposition for a different job but with `fault_verified` and the expected
  failure code returned executor exit `0`. The new exact test failed `assert 0 == 4` for that
  reason, then passed after remediation.
- Accepted and fixed: the CLI success oracle now requires the disposition job ID to equal the
  authorized `--fault-job-id`. Bounded mismatch evidence records expected and observed IDs; the
  prior happy-path fixture now uses the actual authorized ID.
- Test-strength consideration closed: independent wrong-tenant, live-target, and wrong-trigger
  cases prove that each canary predicate is necessary even when the exact job UUID matches.
- Test-strength consideration closed: a SQLite-backed reserved canary now traverses the production
  processor/request/trigger-mapping seam, launches the real fixed child, verifies the run failure,
  and terminalizes the queue row.
- Test-strength consideration closed: a timeout integration helper launches a real descendant;
  the dispatcher kills the new-session process group and the test verifies the descendant no
  longer exists after cleanup.

Formal primary-owned `g-check`: completed below with no findings.

### Current locked test hashes

- `tests/phase1/test_truthful_fault_injection.py`:
  `9aa58091bfe68039e5918fc5d7bb67e9164ad1510d4582d53b64a5b8686f7a71`.
- `tests/phase2/test_discovery_dispatch.py`:
  `c5315b8c1b691911983956f74299bf308bb6b5b09c999bd6ca35ee6c83c6ae2d`.
- `tests/phase2/test_discovery_executor.py`:
  `5a8e915da04fe7eeb1c8eb705bf74fdb9dadd5dc361b4d4f406cc5f5c519b367`.

### Final GREEN and quality evidence

- The last formal-review remediation made the normal processor's returned queue snapshot apply the
  same reserved-trigger exclusion as its claim query. A canary-only normal one-shot now drains
  instead of falsely reporting `work_remains`; its focused dispatch suite passed `17` tests.
- Canonical affected scope after the exact-job and test-strength remediations: `110 passed` three
  consecutive sequential runs (`3.92s`, `4.80s`, `3.85s`). One earlier run hit the existing 120 ms
  lease-renewal timing assertion; the isolated test and all three sequential reruns passed.
- Complete Python suite after all production and test changes: `1750 passed, 3 skipped, 114
  warnings in 226.91s`.
- Environment/Compose wiring: `24 passed`; local-development and production Compose `config -q`
  both pass using explicit `EGP_CRAWLER_AGENT_PROTOCOL=off`. The production render used only the
  committed example env values and performed no launch.
- Ruff full-tree check: PASS. Touched Python format-check: PASS. Python compileall: PASS.
- `git diff --check`: PASS.
- Full-tree Ruff format remains the recorded pre-existing 38-file baseline outside F7; none was
  changed for that drift.
- `uv lock --check` remains unavailable because the required `uv` executable is absent; the lock
  was not modified and no dependency was added or installed into the checkout.
- The earlier transient pre-remediation failure of the same existing 120 ms lease-renewal timing
  assertion occurred while two identical suites ran concurrently during a large Docker download.
  Both timing failures are recorded rather than hidden; the isolated checks, sequential affected
  scopes, and complete suite passed.
- One post-remediation full-suite attempt was intentionally run after removing the temporary
  worktree `.venv` symlink and failed only because `scripts/pg_backup.sh` resolves that exact local
  path. Recreating the verified symlink produced the final 1,750-test pass; the symlink and its
  zero-byte generated `test.sqlite3` are removed before source audit and worktree closeout.
- DeepSeek budget/use remains exactly `0`; no external proposal or direct-write runner was called.
- Local artifact proof: API and worker Dockerfiles built successfully. The discovery-executor worker
  image imports both `egp_api.executors.discovery_dispatch` and `egp_worker.fault_injection`, and
  its API/worker mode sets match. The API image imports the standalone executor. These are local
  packaging smokes only; no container was deployed or activated.

## Delivery and closeout

- Source commit: `398c7e0932b71a69de2828473f25287a717bf951`.
- PR: `#218`, `fix(crawler): make fault injection truthful`, targeting `main` from
  `fix/f7-truthful-fault-injection`.
- GitHub reported the PR mergeable but blocked by hosted checks. All seven CI jobs and the Claude
  review completed with zero executable steps; their check annotations state: `The job was not
  started because your account is locked due to a billing issue.` These jobs are unavailable
  hosted evidence, not passing or product-test failures. Vercel preview remained pending and is not
  counted as deployment, activation, or runtime acceptance.
- The user's standing lifecycle explicitly authorizes merge after honest required-check handling.
  Merge, exact-SHA local-main landing, and session-worktree cleanup remain to be recorded outside
  this source commit.
- No deployment, activation, crawler restart, canary claim, or protocol flip was performed.

## Review (2026-08-15 12:27:41 +0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-f7-truthful-fault-injection`
- Branch: `fix/f7-truthful-fault-injection`
- Scope: staged working tree against baseline
  `d2bc0d807a6806ba54ec802c6b02f2cc2b5bf82e`
- Commands Run: staged diff status/stat/check; RepoPrompt deep staged snapshots and iterative formal
  review; targeted RED/GREEN; affected scope three consecutive times; full pytest; Ruff check and
  touched-file format check; compileall; environment-template tests; local/production Compose
  config with `EGP_CRAWLER_AGENT_PROTOCOL=off`; local API/worker Docker build/import smokes.

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings.

LOW
- No findings.

### Open Questions / Assumptions
- Repository semantics are qualified with SQLite and process lifecycle with local POSIX children.
  No live external PostgreSQL fault campaign or deployed-container canary was executed because
  deployment and activation are explicitly outside this lifecycle.
- Hosted GitHub checks remain delivery evidence to inspect after PR creation; they are distinct
  from the completed local qualification.

### Recommended Tests / Validation
- The final local gates are complete: affected scope `110 passed` three consecutive times and full
  suite `1750 passed, 3 skipped`. No additional source gate is required before commit.
- At PR time, inspect every required GitHub check and classify unavailable or zero-step checks
  honestly rather than treating them as passing.

### Rollout Notes
- `EGP_DISCOVERY_FAULT_INJECTION_ENABLED` remains disabled by default and requires explicit
  one-shot operator arguments targeting an exact non-live reserved canary.
- `EGP_CRAWLER_AGENT_PROTOCOL` remains `off`. This lifecycle performs no deployment, activation,
  crawler restart, canary claim, or protocol flip.
