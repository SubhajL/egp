# DREP: PR-CANARY-03 F2 — Pre-Detail Candidate Ledger Write

> Revised after the Codex (gpt-5.6-sol, xhigh) adversarial pass — see **§11** for the
> disposition of every finding. Codex returned BLOCK on the first draft; the material
> defects (test vacuity via un-forwarded callback, a factually wrong T2 RED-proof, a
> candidate_key product-state leak, and an unsafe `setdefault`) are fixed below.

## §0 Repo Profile

- **Language:** Python 3.12+ (3.13.1). No TS/Go in this slice.
- **Test:** worktree has no own `.venv`; run with the main-repo venv + a PYTHONPATH override:
  `PYTHONPATH="$(printf '%s:' apps/worker/src apps/api/src packages/*/src)" \
   /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest <files> -v` (F1-slice convention).
- **Lint:** `/Users/subhajlimanond/dev/egp/.venv/bin/python -m ruff check <files>`  •  **Format:** `ruff format`
- **Build:** `python -m compileall apps packages`
- **Migration policy:** `docs/MIGRATION_POLICY.md`. **No migration in this slice** (table
  `discovery_candidate_attempts` from migration 038 already exists; no schema change).
- **Coding log:** `coding-logs/2026-08-06-18-00-00 Coding Log (pr-canary-03-f2-pre-detail-ledger).md`
  (pointer at `.codex/coding-log.current`).
- **Repo/runtime ownership:** ours / ours. **Disposition:** production.
- **DB:** PostgreSQL 15+ (prod); SQLite as the test/bootstrap substitute.

### MUST / MUST NOT (root `CLAUDE.md` + `apps/worker/AGENTS.md` — review checkpoints)
- MUST use Python type hints on all signatures.
- MUST scope all DB queries by `tenant_id` (record_accepted/finalize already normalize + scope).
- **MUST NOT let the worker own product-state transitions / write worker-plane accounting into
  product state** (`apps/worker/AGENTS.md:28`, root CLAUDE.md control-plane/worker-plane rule).
  → the threaded `candidate_key` MUST NOT leak into the discovery event / `raw_snapshot` / task
  payload (Codex F-C6). This is R6.
- SHOULD keep functions < 50 lines.
- T-3: candidate-accounting assertions use a REAL (SQLite) repository, not a mock (F1 lesson).

## §1 Goal / Non-Goals

**Goal:** In the live browser discovery flow, persist the durable `accepted` candidate row **before**
`open_and_extract_project` (detail navigation) for every eligible row, and thread the resulting
`candidate_key` forward so the existing `finalize_persisted` / `finalize_failed` transitions target
that same row. If the durable acceptance write fails, the crawl stops (fail-closed, un-wrapped — no
resume, no further e-GP detail traffic).

**Non-Goals (explicitly deferred — do NOT attempt here):**
- **Position-stable / content-based candidate identity.** `candidate_key` stays position-based
  `(keyword, page_number, eligible_ordinal, project_name)` exactly as today. On a browser-closed
  **resume**, the logical page resets to 1 and post-dedupe ordinals shift. Most mid-flight paths mark
  the row *seen* before resume (`browser_discovery.py:693,696,699`), **but the generic
  `except Exception → _raise_browser_closed` path (`:701-703`) does NOT** — so a Playwright
  `"has been closed"` error *during* detail extraction re-scans that row on resume and can record a
  SECOND position-keyed `accepted` row (the original orphaned). This is a **safe over-count**: the
  project is still persisted on the resume pass (no data loss), and the orphan `accepted` row is closed
  by F4 (run authority) + F5 (reconciliation). A same-process memo of the returned key by dedupe
  identity (project_number/name) WOULD close the common reconnect case without touching
  `compute_candidate_key` (Codex Tier-2 R2 correctly refuted the earlier "impossible" claim); it is
  deferred — not impossible — because it threads delicate state through the resume/seen/dedupe flow,
  the residual is safe, and the COMPLETE fix (reordered results, cross-process recovery) still needs a
  row-marker/project-number **content-based key** = the candidate-identity slice, which subsumes the
  memo. The pre-detail callback *carries* `row_marker` so that slice can consume it without re-plumbing.
- F4 (fail-open finalization / run authority from ledger — incl. `finalize` returning `None`
  silently), F5 (worker-loss reconciliation coverage + agent runtime + tenant-scoped
  `reconcile_open_candidates`), F6 (migration 038 constraints, storing `row_marker`) — separate slices.
- No migration, no schema change, no change to `compute_candidate_key`.
- The direct (`discovered_projects` / `live_discovery`) non-browser path keeps recording acceptance in
  `_persist_discovered_project` exactly as today (its payloads are fully materialized before persist —
  no detail-loss gap).

## §2 Requirements — R1..R7

| ID | Requirement (testable) |
|----|------------------------|
| R1 | In the live browser flow, the durable acceptance write for an eligible row happens **strictly before** `open_and_extract_project` for that row (proven by a shared ordered event log, not call counts). |
| R2 | If detail navigation fails **after** acceptance (timeout / `payload is None` / browser death / recovery error), the `accepted` candidate row is still durably present and queryable for that run (`get_run_candidate_summary(...).accepted >= 1`, `.total >= 1`). |
| R3 | If the durable acceptance write raises, `_collect_keyword_projects` lets the exception propagate **un-wrapped** (NOT converted to `BrowserClosedDuringKeyword`, even when the message contains `"has been closed"`) and does **not** call `open_and_extract_project` for that row. |
| R4 | On success, the payload delivered to `project_callback` carries the pre-detail `candidate_key` (authoritatively assigned, not `setdefault`); `finalize_persisted` transitions that exact row (`.persisted == 1`, `.accepted == 0`, `.total == 1` — no orphan second `accepted` row). |
| R5 | `run_discover_workflow` passes a callable `candidate_callback` to `crawl_live_discovery`, **and** `crawl_live_discovery` forwards it to `_collect_keyword_projects` (the wiring seam whose omission would make every other test vacuous — Codex F-C2). |
| R6 | The threaded `candidate_key` never reaches product state: it is consumed (popped) in `_persist_discovered_project` before `_task_safe_payload` / `DiscoveredProjectEvent`, so it is absent from the run-task payload and `raw_snapshot`. |
| R7 | Backward-compatible: the new params are optional (default `None`); when `candidate_callback` is None, `crawl_live_discovery` does not pass it (the existing resume fake keeps its signature); every existing test in the two touched test files still passes. |

## §3 Change Contract — C1..C5

| ID | Path | Action | Anchor | Purpose |
|----|------|--------|--------|---------|
| C1 | `apps/worker/src/egp_worker/browser_discovery.py` | MODIFY | `crawl_live_discovery()` sig L212-220 + the `_collect_keyword_projects(...)` call L284-291 | add optional `candidate_callback`; **conditionally** forward it (only when not None) so the existing resume fake is unaffected (Codex F-C13) |
| C2 | `apps/worker/src/egp_worker/browser_discovery.py` | MODIFY | `_collect_keyword_projects()` sig L454-462; eligible-row build L486-514; per-row loop **before** the `try:` at L528; success branch before `project_callback` L579-583 | tag each row_info with `page_number`+`eligible_ordinal`; invoke `candidate_callback` OUTSIDE the per-row try (fail-closed, un-wrapped); on success authoritatively set `payload["candidate_key"]` |
| C3 | `apps/worker/src/egp_worker/workflows/discover.py` | MODIFY | new inner fn `_record_live_candidate` near L516; `crawl_live_discovery(...)` call L729-736 | define the callback (compute key + `record_accepted`, returns key; no per-keyword auth — see §9-A); pass it as `candidate_callback` |
| C4 | `apps/worker/src/egp_worker/workflows/discover.py` | MODIFY | candidate block in `_persist_discovered_project` L551-569; finalize L636-669 | `key = discovered.pop("candidate_key", None)`; if key present → skip `record_accepted`, finalize with it; else current direct-path behavior. Popping prevents product-state leak (R6) |
| C5 | `tests/phase1/test_worker_browser_discovery.py`, `tests/phase1/test_worker_live_discovery.py` | CREATE (append) | new test fns | T1–T6 |

> Product-code change confined to `browser_discovery.py` + `workflows/discover.py`.
> `candidate_attempt_repo.py`, `candidate_key.py`, `main.py`, `agent_runtime.py` unchanged.

## §4 Function Contracts — FN1..FN4

```
FN1  (MODIFY) crawl_live_discovery(*, keyword=None, profile=None, settings=None,
              include_documents=False,
              project_callback: Callable[[dict[str,object]], None] | None = None,
              candidate_callback: Callable[[dict[str,object]], str | None] | None = None,  # NEW
              progress_callback: LiveProgressCallback | None = None) -> list[dict[str,object]]
     File:   C1
     Change: build collect_kwargs = {"candidate_callback": candidate_callback} ONLY when
             candidate_callback is not None; splat into the existing
             _collect_keyword_projects(...) call at L284-291.
     Post:   when candidate_callback is None → byte-identical to today (existing fake with the
             old signature still accepted — R7). When set → forwarded (R5).

FN2  (MODIFY) _collect_keyword_projects(*, page, keyword, settings, seen_keys,
              include_documents,
              project_callback: Callable[[dict[str,object]], None] | None = None,
              candidate_callback: Callable[[dict[str,object]], str | None] | None = None  # NEW
              ) -> list[dict[str,object]]
     File:   C2
     Does:   (a) when appending to eligible_rows (L505-514), add
                 "page_number": page_num and "eligible_ordinal": <0-based idx within this page's
                 eligible_rows> to each row_info.
             (b) in `for row_info in eligible_rows`, BEFORE the per-row `try:` (currently L528):
                     if candidate_callback is not None:
                         key = candidate_callback({
                             "keyword": keyword, "page_number": page_num,
                             "eligible_ordinal": row_info["eligible_ordinal"],
                             "row_marker": row_info["row_marker"],
                             "project_name": row_info["project_name"],
                             "project_number": row_info.get("project_number"),
                             "source_status_text": row_info["source_status_text"],
                         })
                         if key is not None:
                             row_info["candidate_key"] = key
                 The call is OUTSIDE the try, so a raise is NEVER seen by the `except Exception ->
                 _raise_browser_closed` at L665 (which converts "has been closed" messages to
                 BrowserClosedDuringKeyword) — it propagates un-wrapped (R3).
             (c) success branch (payload not None, not duplicate) before `project_callback(payload)`
                 (L582-583):
                     if row_info.get("candidate_key") is not None:
                         payload["candidate_key"] = row_info["candidate_key"]   # authoritative, NOT setdefault
     Post:   R1 (pre-detail order), R3 (un-wrapped fail-closed), R4 (authoritative key on payload).
             candidate_callback is None → byte-identical to today (R7).
     Errors: MUST NOT catch/convert candidate_callback exceptions.
     Notes:  no repo/key imports here (kept DB-agnostic); typed; small block.

FN3  (NEW) _record_live_candidate(candidate_info: dict[str, object]) -> str | None
     File:   C3 (inner fn of run_discover_workflow; closes over tenant_id, run, keyword,
             candidate_attempt_repo)
     Does:   if candidate_attempt_repo is None: return None
             kw = str(candidate_info.get("keyword") or keyword)
             page = candidate_info.get("page_number"); ordinal = candidate_info.get("eligible_ordinal")
             key = compute_candidate_key(keyword=kw,
                     page_number=int(page) if page is not None else 0,
                     row_ordinal=int(ordinal) if ordinal is not None else 0,
                     project_name=str(candidate_info.get("project_name") or ""))
             candidate_attempt_repo.record_accepted(tenant_id=tenant_id, run_id=run.id,
                     candidate_key=key, keyword=kw,
                     page_number=int(page) if page is not None else None,
                     row_ordinal=int(ordinal) if ordinal is not None else None)
             return key
     Pre:    run-level authorization already passed at workflow entry (discover.py:361-374) BEFORE
             any browser traffic (Codex F-C10) — so no per-keyword auth here.
     Post:   durable accepted row (idempotent ON CONFLICT); returns key for threading. Raises on DB
             failure → propagates through candidate_callback → un-wrapped → run fails (R3, R2-negative).
     Notes:  mirrors the existing record_accepted call; typed.

FN4  (MODIFY) _persist_discovered_project(discovered) candidate block (L551-569) + finalize (L636-669)
     File:   C4
     Change: at the top of the candidate block:
                 candidate_key_value = discovered.pop("candidate_key", None)   # consume → no product leak (R6)
                 if candidate_key_value is None and candidate_attempt_repo is not None:
                     <existing L552-569 body: compute key + record_accepted BEFORE the try, assign candidate_key_value>
             finalize blocks (L636-669) unchanged; they already guard on `candidate_key_value is not None`.
     Post:   live path: no re-record (key threaded), finalize targets the same row (R4); key popped
             before `_task_safe_payload`/event (R6). direct path: identical to today (R7).
     Notes:  pop uses default None (harmless on the direct path).
```

## §5 Test Plan — T1..T6

```
T1   test_collect_keyword_projects_records_candidate_strictly_before_detail
     File:  tests/phase1/test_worker_browser_discovery.py     Covers: R1
     Type:  unit (FakeResultsPage harness)
     Arrange: FakeResultsPage with ONE eligible row; a shared list `seq`. candidate_callback =
              lambda info: (seq.append("candidate"), "KEY-1")[1]; monkeypatch open_and_extract_project
              to `lambda **k: (seq.append("open"), _raise Timeout)` — appends "open" then raises
              TimeoutError; _return_to_results -> no-op; project_spy.
     Act:   _collect_keyword_projects(page=..., keyword="k",
              settings=BrowserDiscoverySettings(max_pages_per_keyword=1), seen_keys=set(),
              include_documents=False, project_callback=project_spy, candidate_callback=candidate_callback)
     Assert: seq == ["candidate", "open"]  (candidate STRICTLY before the detail attempt);
             candidate_callback saw page_number==1, eligible_ordinal==0, row_marker present, project_name;
             project_spy NOT called.
     RED-proof: BEFORE fix, no candidate_callback kwarg → TypeError: unexpected keyword argument
                (clean). With the param but a POST-detail invocation, open raises before "candidate"
                is appended → seq == ["open"] → AssertionError. Correct pre-`try` placement → passes.

T2   test_collect_keyword_projects_fail_closed_unwrapped_on_write_failure
     File:  tests/phase1/test_worker_browser_discovery.py     Covers: R3
     Type:  unit
     Arrange: one eligible row; candidate_callback raises RuntimeError("ledger connection has been
              closed")  # message deliberately contains the browser-closed marker; open_spy list;
              monkeypatch open_and_extract_project to append to open_spy (must never run).
     Act:   with pytest.raises(RuntimeError) as ei: _collect_keyword_projects(... candidate_callback=raiser ...)
     Assert: not isinstance(ei.value, BrowserClosedDuringKeyword);  open_spy == []
     RED-proof: BEFORE fix, TypeError (no kwarg). If the fix (wrongly) placed the call INSIDE the
                per-row try, the "has been closed" message makes `_raise_browser_closed` convert it to
                BrowserClosedDuringKeyword (verified at browser_discovery.py:740) → the isinstance
                assertion fails. Only the correct pre-`try` placement propagates it un-wrapped AND
                leaves open_spy empty. (This is the corrected RED-proof — the original was wrong: a
                plain-message RuntimeError is NOT converted, so it could not distinguish placement.)

T3   test_collect_keyword_projects_threads_authoritative_candidate_key
     File:  tests/phase1/test_worker_browser_discovery.py     Covers: R4 (browser layer)
     Type:  unit
     Arrange: one eligible row; open_and_extract_project returns a valid payload that ALSO contains
              a stale "candidate_key": "STALE"; candidate_callback returns "KEY-1"; project_spy captures.
     Act:   _collect_keyword_projects(... candidate_callback=lambda i: "KEY-1", project_callback=project_spy)
     Assert: project_spy payload["candidate_key"] == "KEY-1"  (authoritative overwrite of "STALE").
     RED-proof: BEFORE fix, TypeError. With `setdefault` instead of assignment, "STALE" survives →
                AssertionError. Correct authoritative assignment → passes.

T4   test_run_discover_workflow_durable_candidate_survives_post_acceptance_loss
     File:  tests/phase1/test_worker_live_discovery.py     Covers: R2, R5(workflow half)
     Type:  integration (REAL SQLite candidate repo — T-3)
     Arrange: repo = SqlCandidateAttemptRepository(sqlite tmp, bootstrap_schema=True); run_id = fixed
              UUID; FakeRunRepository, FakeProjectEventSink; fake crawl_live_discovery(**kwargs):
                cb = kwargs.get("candidate_callback"); assert callable(cb), "workflow must pass candidate_callback"
                cb({"keyword":"k","page_number":1,"eligible_ordinal":0,"row_marker":{"project_name":"P"},
                    "project_name":"P","project_number":"EGP-1","source_status_text":"หนังสือเชิญชวน/ประกาศเชิญชวน"})
                # simulate timeout AFTER acceptance: never call project_callback; return []
     Act:   run_discover_workflow(tenant_id=TENANT_ID, run_id=run_id, keyword="k",
              discovered_projects=[], run_repository=..., project_event_sink=...,
              candidate_attempt_repo=repo, live=True)
     Assert: s = repo.get_run_candidate_summary(tenant_id=TENANT_ID, run_id=run_id);
             s.total == 1; s.accepted == 1; s.persisted == 0.
     RED-proof: BEFORE fix, run_discover_workflow does NOT pass candidate_callback → cb is None →
                `assert callable(cb)` fails ("workflow must pass candidate_callback"). AFTER fix →
                durable accepted row present.

T5   test_run_discover_workflow_finalizes_threaded_key_and_hides_it_from_product_state
     File:  tests/phase1/test_worker_live_discovery.py     Covers: R4 (e2e), R6, R7
     Type:  integration (REAL SQLite candidate repo)
     Arrange: repo (sqlite, bootstrap); run_id UUID; FakeRunRepository; a sink whose record_discovery
              returns SimpleNamespace(id=<UUID>, project_state=...) so finalize_persisted's project_id
              normalizes; fake crawl_live_discovery that:
                key = kwargs["candidate_callback"]({"keyword":"k","page_number":1,"eligible_ordinal":0,
                       "project_name":"SEARCH-NAME","project_number":"EGP-1",
                       "source_status_text":"หนังสือเชิญชวน/ประกาศเชิญชวน","row_marker":{...}})
                kwargs["project_callback"]({"project_name":"DETAIL-NAME","organization_name":"O",   # DIFFERENT name
                       "source_status_text":"หนังสือเชิญชวน/ประกาศเชิญชวน","candidate_key":key,
                       "project_state":"discovered"})
                return []
              Call with live_include_documents=False (exercises _mark_live_document_collection_deferred's dict copy).
     Act:   run_discover_workflow(... candidate_attempt_repo=repo, live=True, live_include_documents=False)
     Assert: s = repo.get_run_candidate_summary(...); s.total == 1; s.persisted == 1; s.accepted == 0
             (proves the THREADED key finalized the SAME row — a broken impl that ignores it and
             recomputes from "DETAIL-NAME" would create a 2nd accepted row → total==2/accepted==1);
             AND "candidate_key" not in run_repository.tasks[0]["payload"]  (R6: no product-state leak);
             AND the recorded DiscoveredProjectEvent.raw_snapshot has no "candidate_key".
     RED-proof: BEFORE fix, cb not passed → KeyError/assert in the fake. With threading but WITHOUT the
                pop, the leak assertion fails. With the SAME name in both events, total==1 would pass
                even when broken — the DIFFERENT search/detail names make the orphan visible. Correct
                fix → total==1, persisted==1, no leak.

T6   test_crawl_live_discovery_forwards_candidate_callback_to_collector
     File:  tests/phase1/test_worker_browser_discovery.py     Covers: R5 (the anti-vacuity seam)
     Type:  unit (browser-setup monkeypatched exactly like the resume test at :3510-3558)
     Arrange: monkeypatch launch_real_chrome / sync_playwright / connect_playwright_to_chrome /
              wait_for_cloudflare / search_keyword / clear_search / is_no_results_page /
              restore_results_page / safe_shutdown / _logged_sleep (copy from the resume test);
              sentinel = object(); captured = {}; monkeypatch _collect_keyword_projects to
              `def spy(**kwargs): captured.update(kwargs); return []`.
     Act:   crawl_live_discovery(keyword="k", settings=BrowserDiscoverySettings(), include_documents=False,
              candidate_callback=sentinel)
     Assert: captured.get("candidate_callback") is sentinel.
     RED-proof: BEFORE fix, crawl_live_discovery has no candidate_callback param → TypeError. With the
                param but no forwarding → captured has no candidate_callback → AssertionError. Correct
                conditional forward → passes. THIS is the test that makes T1–T5 non-vacuous (Codex F-C2):
                without it, a crawl_live_discovery that accepts but never forwards the callback would
                pass every other test while shipping F2 broken.
```

**Edge/negative coverage:** T1 (timeout after acceptance), T2 (write failure → un-wrapped abort, no
traffic, pathological "has been closed" message), T4 (post-acceptance loss → durable evidence), T5
(no-orphan / key consistency with divergent names + no leak). **Oracles:** `get_run_candidate_summary`
counts; the shared `seq` log (T1); `isinstance(...)` + empty open_spy (T2); forwarded-sentinel identity (T6).

## §6 Traceability Matrix

| Req | Fulfilled at — fn → realizing call/statement | Tests | Files | Slice |
|-----|----------------------------------------------|-------|-------|-------|
| R1 | `_collect_keyword_projects` → `candidate_callback({...})` in the `for row_info` loop, placed BEFORE the per-row `try:` (before `open_and_extract_project` at L548) | T1 | C2 | S1 |
| R2 | that pre-`try` call → `_record_live_candidate` → `candidate_attempt_repo.record_accepted(...)` (durable row before detail) | T4 | C2,C3 | S1 |
| R3 | `_collect_keyword_projects` invokes `candidate_callback` OUTSIDE the per-row try; its exception bypasses `_raise_browser_closed`(L665/740) & the `except BrowserClosedDuringKeyword`(L305) → out via `run_discover_workflow` L749 | T2 | C2 | S1 |
| R4 | `_collect_keyword_projects` → `payload["candidate_key"] = row_info["candidate_key"]` (authoritative) before `project_callback` (L582-583); `_persist_discovered_project` → `finalize_persisted(candidate_key=<popped key>)` (L638-643) | T3,T5 | C2,C4 | S1 |
| R5 | `run_discover_workflow` → `crawl_live_discovery(..., candidate_callback=_record_live_candidate)` (L729-736) **and** `crawl_live_discovery` → `_collect_keyword_projects(..., candidate_callback=candidate_callback)` (L284-291, conditional) | T4,T6 | C1,C3 | S1 |
| R6 | `_persist_discovered_project` → `discovered.pop("candidate_key", None)` before `_task_safe_payload`(L539/571) & `DiscoveredProjectEvent`(L579) | T5 | C4 | S1 |
| R7 | new params default `None`; `crawl_live_discovery` forwards only when not None; `_persist` branch guards on presence | T5 + full existing suites of both test files | C1,C2,C4 | S1 |

Every R has ≥1 T; every T maps to ≥1 R; every R names its realizing call site (line anchors verified in Phase 1).

## §7 Wiring Verification

| Component | Runtime caller | Registration / plumbing site | Schema/table |
|---|---|---|---|
| `candidate_callback` on `crawl_live_discovery` | `run_discover_workflow` (discover.py:729-736) | passed by keyword in the existing call | — |
| `candidate_callback` on `_collect_keyword_projects` | `crawl_live_discovery` (browser_discovery.py:284-291) | **conditional** forward (only when not None) — the seam T6 proves | — |
| `_record_live_candidate` (inner fn) | `_collect_keyword_projects` via the passed `candidate_callback` | defined in `run_discover_workflow`, passed at L729-736 | `discovery_candidate_attempts` (record_accepted writes it; migration 038 applied) |
| threaded `payload["candidate_key"]` | `_persist_discovered_project` reads then **pops** it → `finalize_persisted/failed` | `_mark_live_document_collection_deferred` `dict(discovered)` preserves it (discover.py:196); popped before product event | `discovery_candidate_attempts` |

No CREATE product files → no orphans. Both worker entrypoints (`main.py:152`, `agent_runtime.py:221`)
call `run_discover_workflow` → both covered.

## §8 Slice Plan — S1

| ID | Scope | Owner | Stop line | Oracle | Done when |
|----|-------|-------|-----------|--------|-----------|
| S1 | C1,C2,C3,C4,C5 (T1–T6) | **Claude** | — (Q0: correctness-critical crawler/ledger path + the exact defect class under active PR-CANARY review + fail-closed control flow that must not be mis-wrapped; not delegated) | T1–T6 green + full `test_worker_browser_discovery.py` + `test_worker_live_discovery.py` + `test_candidate_accounting.py` + `test_candidate_postgres_dialect.py` green + ruff + compileall | all pass |

Single slice — the browser change and the workflow change share one callback contract and must land together. One PR.

## §9 Risks, Rollout, Rollback

| Risk | Trigger | Blast radius | Gate | Rollback |
|------|---------|--------------|------|----------|
| A. Pre-detail acceptance without per-keyword auth | unentitled profile keyword crawled live | ledger gets `accepted` rows on a run that then fails at persist-time auth | **Accepted**: run-level auth already gates browser traffic at workflow entry (discover.py:361-374, Codex F-C10); `_persist_discovered_project` still authorizes product creation; accepted rows are run-scoped accounting, not product state; reconciliation collapses them. | revert |
| B. candidate-write exception wrapped as `BrowserClosedDuringKeyword` → resume loop | callback placed INSIDE the per-row try; message contains "has been closed" | crawl reconnects/retries instead of stopping (violates R3) | T2 (pathological message + isinstance + empty open_spy) | revert |
| C. finalize misses the row on success | key recomputed from detail name instead of threaded | false `accepted` leftover; `finalize` returns None **silently** (that swallow is the F4 fail-open defect, out of scope) | Key is THREADED + authoritative; T5 asserts total==1/persisted==1/accepted==0 with divergent names | revert |
| D. resume duplicates / mis-pages | browser-closed resume re-scans a page | over-count of `accepted` rows and page mislabel | **Accepted/deferred** (Codex Tier-2 R2 HIGH → deferred): the generic row handler `browser_discovery.py:701-703` raises `BrowserClosedDuringKeyword` WITHOUT `_mark_row_seen` (unlike siblings :690-700), so a `"has been closed"` error DURING detail extraction re-scans the row on resume with the logical page reset to 1 → a 2nd position-keyed `accepted` row, original orphaned. SAFE: over-count only, project still persisted on resume (no data loss); orphan closed by F4 (run authority) + F5 (reconciliation); collision-free content-based key = candidate-identity slice. Naive in-scope fix (mark seen at :701) would drop the project entirely — worse. `compute_candidate_key` is do-not-touch. | reconcile / identity slice |
| E. candidate_key leaks into product state / API | key left on payload | worker-plane data in `raw_snapshot`/task payload (AGENTS.md:28 violation) | R6 pop; T5 leak assertions | revert |
| F. existing tests break | new params | live/browser suites | R7: optional + conditional forward; full suites green | revert |

**Rollout:** pure code change; behavior is inert unless `candidate_attempt_repo` is provided (prod
provides it). No flag, no migration. **Rollback:** single-commit revert restores post-F1 state.

## §10 Do-Not-Touch List (verbatim)

- `packages/db/src/egp_db/repositories/candidate_attempt_repo.py` — unchanged.
- `packages/crawler-core/src/egp_crawler_core/candidate_key.py` — `compute_candidate_key` unchanged.
- `packages/db/src/migrations/038_discovery_candidate_attempts.sql` + `manifest.sha256` — no migration.
- `apps/worker/src/egp_worker/main.py`, `apps/worker/src/egp_worker/agent_runtime.py` — unchanged.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` — reconciliation is the F5 slice.
- Existing test BODIES in `test_candidate_accounting.py` / `test_candidate_postgres_dialect.py` — not modified.
- The existing resume test `test_crawl_live_discovery_resumes_same_keyword_after_browser_close`
  (`test_worker_browser_discovery.py:3499`) and its `fake_collect_keyword_projects` — NOT modified
  (conditional forwarding keeps it green).
- The direct (`discovered_projects` / `live_discovery`) branch of `_persist_discovered_project` — behavior preserved.

## §11 Codex Adversarial Pass — Dispositions (gpt-5.6-sol, xhigh; verdict BLOCK on draft 1)

| # | Codex finding | Disposition | Action |
|---|---------------|-------------|--------|
| C-1 | Resume resets logical page to 1 / ordinals shift post-dedupe / repo stores no row_marker → obligation (b) "normalized page/ordinal/marker" not fully realized | **Accept (partial) + defer** | Key stays position-based; document as Non-Goal (identity slice). Verified the core invariant holds: mid-flight row marked *seen* before resume → not re-opened; its accepted row is the intended evidence. Callback CARRIES row_marker for the future slice. §1, §9-D. |
| C-2 | T1–T5 all pass even if `crawl_live_discovery` never forwards the callback (T1–T3 call the collector directly; T4–T5 fake crawl_live_discovery) — correlated blind spot | **Accept (critical)** | Added **T6** — real `crawl_live_discovery` forwards `candidate_callback` to `_collect_keyword_projects` (sentinel identity). R5 split to name both seams. |
| C-3 | T2 RED-proof factually wrong: `_raise_browser_closed` converts ONLY "has been closed" messages (browser_discovery.py:740); a plain RuntimeError inside the try is bare-raised, so T2 couldn't distinguish placement | **Accept** | Rewrote T2: callback raises `RuntimeError("...has been closed")`; assert `not isinstance(BrowserClosedDuringKeyword)` + `open_spy == []`. Now genuinely distinguishes inside-vs-outside `try`. |
| C-4 | T5 vacuous: same name/page/ordinal in pre-event and detail → recompute yields same SHA → total==1 even if the threaded key is ignored | **Accept** | T5 now uses divergent search ("SEARCH-NAME") vs detail ("DETAIL-NAME") names; a broken recompute path creates a 2nd row → total==2/accepted==1; correct → total==1. |
| C-5 | `setdefault("candidate_key", ...)` trusts a stale detail key; FN4 trusts arbitrary key | **Accept** | Authoritative `payload["candidate_key"] = ...` (T3 asserts overwrite of a stale key). The silent finalize-None swallow is the F4 fail-open defect — noted out of scope (§9-C). |
| C-6 | Threaded key leaks via `_task_safe_payload` → task payload + `DiscoveredProjectEvent.raw_snapshot` → persisted product evidence + API (violates worker/product boundary, AGENTS.md:28) | **Accept (critical)** | R6 + FN4: `discovered.pop("candidate_key", None)` before building the product payload/event; T5 asserts absence in task payload and raw_snapshot. |
| C-7 | FN3 returns None when repo absent → detail continues without durable acceptance | **Reject (by design)** | No repo ⇒ accounting disabled ⇒ nothing to record / no fail-closed; production always supplies the repo. Documented. |
| C-8 | Optional public callback lets direct callers crawl without the ledger | **Reject (by design)** | Only production caller is `run_discover_workflow`, which passes it when the repo is present. Documented. |
| C-9 | T1 uses call counts; a callback fired from timeout handling after detail could satisfy them | **Accept** | T1 now asserts a shared ordered `seq == ["candidate", "open"]` — strict pre-detail ordering, not counts. |
| C-10 | Risk A false: authorization already precedes browser traffic (discover.py:361) | **Accept** | Rewrote §9-A; FN3 does NOT re-authorize per keyword. |
| C-11 | T5 doesn't exercise `_mark_live_document_collection_deferred` (default `live_include_documents=True` skips it) | **Accept** | T5 calls with `live_include_documents=False`. |
| C-12 | "Only root CLAUDE.md applies" false — `apps/worker/AGENTS.md:21` has nearer rules | **Accept** | Read it; folded its "don't own product state" MUST NOT into §0 → R6. |
| C-13 | Existing resume fake (`_collect_keyword_projects` fake, no `candidate_callback` param) breaks under unconditional forwarding | **Accept** | C1 forwards **conditionally** (only when not None); resume fake untouched (R7, §10). |
| — | Confirmed-true (no action): `_persist` records before its try (fail-closed); direct path has no detail-loss gap; `dict(discovered)` preserves keys; anchors 504/527-560/579-583/551-569 accurate at HEAD | noted | — |
