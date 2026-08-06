# DREP: PR-CANARY-03 F3 — Typed Browser Outcomes & Private Diagnostics

> Delegation-Ready Execution Plan. F3 = the **frozen PR-CANARY-02 contract** (source coding log
> `egp-ops-main/.../2026-08-05-17-58-04 …canary-hardening.md` lines **463-484**), reassigned as F3
> in the PR-CANARY-03 remediation numbering (07:48:44 review HIGH: "the frozen PR-02 browser contract
> was not implemented; PR #202 was only a dispatcher fault-injection supplement").
>
> **REVISED after the Codex (gpt-5.6-sol, xhigh) adversarial pass — it returned BLOCK and caught five
> real defects now fixed below (classifier ordering, cross-keyword no-results, anomaly poisoning,
> fail-open absence flag, wrong `main.py` function/env path). Full disposition in §11.**

## §0 Repo Profile

- **Language:** Python 3.12+ (`requires-python = ">=3.12"`). No TS/Go/SQL/migration in this slice.
- **Test:** worktree has no own `.venv`; run with the main-repo venv + PYTHONPATH override (F1/F2 convention):
  ```
  PYTHONPATH="$(printf '%s:' apps/worker/src apps/api/src packages/*/src)" \
    /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest <files> -q
  ```
- **Lint:** `/Users/subhajlimanond/dev/egp/.venv/bin/python -m ruff check <files>` • **Format:** `ruff format` (line-length 100).
- **Build:** `/Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall apps packages`.
- **Migration policy:** `docs/MIGRATION_POLICY.md`. **No migration, no schema, no `terminal_reason` constraint** (that is F6).
- **Coding log:** `coding-logs/2026-08-06-12-53-19 Coding Log (pr-canary-03-f3-typed-browser).md` (pointer at `.codex/coding-log.current`).
- **Repo/runtime ownership:** ours / ours. **Disposition:** production. Ships **dark** (diagnostics default-off; the happy path is behaviour-preserving).
- **DB:** PostgreSQL 15+ (prod); SQLite substitute in tests. (Not touched by F3.)

### MUST / MUST NOT (root `CLAUDE.md` + `apps/worker/AGENTS.md` — review checkpoints)
- MUST use Python type hints on all signatures.
- MUST NOT let the worker own product-state transitions; the worker is an event producer / artifact
  collector (`apps/worker/AGENTS.md:28`). → F3 emits typed **evidence** only; it MUST NOT finalize
  candidates, change run status directly, or write worker accounting into product/`raw_snapshot` state.
- MUST NOT store browser state / temp files in repo or OneDrive-synced folders (`AGENTS.md:30`). →
  diagnostics go to an **operator-provided** `diagnostics_dir`, never a repo path; default off.
- SHOULD keep functions < 50 lines; prefer explicit lifecycle over boolean flags.
- Security: the diagnostic manifest MUST NOT contain raw HTML, cookies, auth headers, proxy
  credentials, full exception text, or a page URL (frozen contract line 480). Safe **by construction**
  (only structured e-GP fields), with `egp_observability.redact_preview` as defense-in-depth. Files are
  written `0o600` inside a `0o700` dir.
- T-3: new browser-layer assertions use fakes / the real functions, not mocks of the module under test.

## §1 Goal / Non-Goals

**Goal:** Replace the boolean `_detail_page_is_invalid` with a typed classification of every terminal
browser-detail outcome; add **exactly one** bounded retry for transient classifications after restoring
the search row; make `keyword_no_results` terminal **only after** the recovery budget is applied
uniformly (including the cross-keyword case); and capture **at most one** private, redacted, SHA-256'd,
`0o600` diagnostic per terminal candidate/keyword anomaly (fail-open, with a bounded absence flag).
Preserve document-collection evidence as evidence-only. `open_and_extract_project`'s **per-call**
`dict | None` return is unchanged; the anomaly progress-stage now fires **once, from the caller, only
when the outcome is terminal** (so a retry-recovered candidate no longer poisons the run).

**Non-Goals (explicitly deferred — do NOT attempt here):**
- **No candidate finalization / run authority.** F3 must NOT call `finalize_persisted/failed/dropped`,
  must NOT change keyword `ok/partial/failed` derivation, must NOT forbid `succeeded` with open
  candidates. That is **F4**. `finalize_dropped` stays unwired.
- **No migration / no `terminal_reason` CHECK / no tenant-FK work.** That is **F6**. F3 does not write `terminal_reason`.
- **No worker-loss reconciliation / agent-runtime change.** That is **F5**.
- **No `compute_candidate_key` change** (identity slice).
- **No agent document-envelope application.** Document collection stays evidence-only; the unsupported
  document-envelope rejection is unchanged and is a regression check in the gate (§5 T20).
- **No new metrics/alerts/health routes** (PR-CANARY-07). **No API dispatcher/config diagnostics
  plumbing** (`discovery_worker_dispatcher.py`, `apps/api/.../config.py`) — F3 activates diagnostics via
  a worker-host `EGP_BROWSER_DIAGNOSTICS_DIR` env var (realistic on the residential Mac worker) plus a
  `browser_settings.browser_diagnostics_dir` payload key; the full dispatcher payload propagation is a
  documented PR-07 follow-up.
- **No restructuring of the frozen exception ladder** (`_collect_keyword_projects` L627-703) beyond
  adding a single fail-open diagnostic call in the timeout branch (C5b).

### Design decisions (flagged for the reviewer)
1. **`placeholder_detail` is terminal / no-retry** (with `rejection_page`). The frozen contract retries
   *"only … navigation/results-page/missing-field."* Codex agreed this literal reading is defensible.
2. **Classifier ordering (Codex CRITICAL fix):** classify in the order **rejection → results-page →
   non-empty header-placeholder → valid**, and **do NOT put `""` in the placeholder set**. Empty
   name/org/number fall through to the post-classify `MISSING_REQUIRED_FIELDS` branch (which keeps
   checking all three, preserving today's "empty → dropped" outcome while making *missing* a distinct,
   retry-eligible reason). Without this, blanks and blank-on-results-page both collapse to
   `placeholder_detail` and two required reasons are unreachable.
3. **Cross-keyword `keyword_no_results` (Codex CRITICAL fix):** `search_keyword`'s internal no-results
   retry is gated by `(not had_previous_results or same_keyword_retry)` (`browser_discovery.py:2454`),
   so a *new* keyword after a keyword that had rows is terminal on the first empty hit **despite budget**.
   F3 adds a bounded caller-level recovery loop in `crawl_live_discovery` (≤ `search_page_recovery_retries`
   re-searches) before the terminal `keyword_no_results`. This is additive (does not touch the complex
   `search_keyword` conditions). Trade-off: ≤1 extra search per genuinely-empty keyword — acceptable for
   a completeness-first product; documented in §9.
4. **Anomaly emission moves to the terminal branch (Codex HIGH fix):** discover.py treats any
   `project_detail_invalid` / `project_detail_missing_required_fields` progress stage as an immediate
   run anomaly (`discover.py:68-73`, counted at ~L455). If `open_and_extract_project` emits it per
   attempt, a transient-first/valid-second candidate poisons the run. F3 emits that stage **from
   `_collect_keyword_projects`, once, only when the row is terminal (post-retry).** discover.py is
   untouched; the `stage → DiscoveryFailureCode` mapping is preserved.

## §2 Requirements — R1..R11

| ID | Requirement (testable) |
|----|------------------------|
| R1 | `classify_detail_page(page, detail) -> ProjectDetailReason` replaces `_detail_page_is_invalid`, classifying in order **rejection_page → results_page_returned → placeholder_detail (non-empty header values only) → valid**. A results page whose detail extraction yields blanks classifies `RESULTS_PAGE_RETURNED`, **not** `placeholder_detail`. |
| R2 | `open_and_extract_project(..., outcome_sink=None)` writes the precise `ProjectDetailReason` at every exit: nav-false→`NAVIGATION_FAILURE`; preliminary-pricing→`OUT_OF_SCOPE_STAGE`; classify non-valid→that reason; empty name **or** org **or** number→`MISSING_REQUIRED_FIELDS`; else→`VALID`. Its **per-call `dict | None` return is byte-identical to today** for every input (blanks still return `None`, now via the missing branch). |
| R3 | `open_and_extract_project` **no longer emits** the `project_detail_invalid` / `project_detail_missing_required_fields` progress stages itself (it keeps the non-anomaly `project_detail_skipped_preliminary_pricing` event). |
| R4 | In `_collect_keyword_projects`, a **transient** reason (`navigation_failure`/`results_page_returned`/`missing_required_fields`) triggers **exactly one** re-open after `_return_to_results` + `_resolve_results_row_index`; `rejection_page`/`placeholder_detail`/`out_of_scope_stage`/`unknown` are **never** retried; total detail-open attempts per row ≤ 2. |
| R5 | The **terminal** anomaly progress stage is emitted **once, from `_collect_keyword_projects`**, only when the row's final outcome is `None` with an anomaly reason: `MISSING_REQUIRED_FIELDS`→`project_detail_missing_required_fields`; `{REJECTION_PAGE, PLACEHOLDER_DETAIL, RESULTS_PAGE_RETURNED, NAVIGATION_FAILURE}`→`project_detail_invalid`; `OUT_OF_SCOPE_STAGE`/`UNKNOWN`→no anomaly stage. A retry that recovers (payload≠None) emits **no** anomaly stage → run stays `succeeded`. |
| R6 | A terminal candidate anomaly captures **at most one** diagnostic; capture is **fail-open at two layers** (helper never raises; caller wraps in try/except) and returns/records a bounded status `captured`/`disabled`/`failed`, logged via a `browser_diagnostic` progress event (the "absence is a bounded flag" requirement). `diagnostics_dir is None` → status `disabled`, nothing written, `page.screenshot` not called. |
| R7 | The diagnostic manifest JSON contains `reason`, `screenshot_sha256`, `screenshot_bytes`, UTC `ts`, and a **redacted+truncated** keyword/marker preview built only from structured e-GP fields, and NEVER raw HTML, cookies, auth headers, proxy credentials, full exception text, or a page URL. The screenshot is `full_page=True`; both files are `0o600` inside a `0o700` dir; the file-name stem is an **opaque per-anomaly key** (so distinct anomalies with byte-identical screenshots do not overwrite each other), with the screenshot content SHA-256 stored inside the manifest; every written path is contained within `diagnostics_dir`. |
| R8 | `keyword_no_results` is emitted as terminal **only after** ≤ `search_page_recovery_retries` caller-level re-searches (fix for the cross-keyword gap), and its terminal emission captures **at most one** fail-open keyword-level diagnostic. |
| R9 | The detail-**timeout** branch of the existing ladder captures **at most one** fail-open diagnostic (reason `project_timeout`) without altering the ladder's control flow; timeouts are not routed into the typed retry (they keep their existing recovery). |
| R10 | `diagnostics_dir` is parsed in `_build_browser_settings` from either `payload["browser_settings"]["browser_diagnostics_dir"]` or the `EGP_BROWSER_DIAGNOSTICS_DIR` env var (payload wins); default → `None` (dark). |
| R11 | Backward-compat: all existing tests in `tests/phase1/test_worker_browser_discovery.py`, `tests/phase1/test_worker_live_discovery.py`, `tests/phase1/test_worker_build_browser_settings.py`, `tests/phase2/test_rules_api.py`, and the doc-envelope regression `tests/phase3/test_crawler_agent_inbox_processor.py` stay green; a narrow fake returning `dict | None` (no `outcome_sink`) behaves exactly as today (no retry, no capture). |

## §3 Change Contract — C1..C13

| ID | Path | Action | Anchor | Purpose |
|----|------|--------|--------|---------|
| C1 | `packages/shared-types/src/egp_shared_types/enums.py` | MODIFY | append after `CrawlerBlockerCode` L157-166 | `class ProjectDetailReason(StrEnum)` — 8 typed reasons; `MISSING_REQUIRED_FIELDS` value reuses the existing `project_detail_missing_required_fields` string. |
| C2 | `apps/worker/src/egp_worker/browser_discovery.py` | MODIFY | `BrowserDiscoverySettings` L90-103 | add `diagnostics_dir: Path | None = None` (last field). |
| C3 | `apps/worker/src/egp_worker/browser_discovery.py` | MODIFY | replace `_detail_page_is_invalid` L1440-1471 → `classify_detail_page`; add `DetailOutcomeSink` + `_TRANSIENT_RETRY_REASONS`/`_ANOMALY_STAGE_REASONS`/`_DIAGNOSTIC_REASONS` near L143-170 | typed DOM classifier (corrected ordering, no `""`) + sink + reason-sets. |
| C4 | `apps/worker/src/egp_worker/browser_discovery.py` | MODIFY | `open_and_extract_project` L1089-1270 (exits L1103/1116/1129/1144/success) | add optional `outcome_sink`; write reason at each exit; call `classify_detail_page`; **remove** the two anomaly-stage `_log_live_progress` calls (keep prelim-skip). Missing-check covers name/org/number. |
| C5a | `apps/worker/src/egp_worker/browser_discovery.py` | MODIFY | `_collect_keyword_projects` per-row loop L559-626 | sink; conditional `outcome_sink` pass; one transient retry (restore+resolve+reopen), no double-restore; terminal anomaly-stage emission (R5); fail-open `capture_detail_diagnostic` (R6). |
| C5b | `apps/worker/src/egp_worker/browser_discovery.py` | MODIFY | timeout `except` branch L630-645 | add one fail-open `_safe_capture_detail_diagnostic(reason="project_timeout")` beside the existing `log_results_debug_snapshot`; no control-flow change (R9). |
| C6 | `apps/worker/src/egp_worker/browser_discovery.py` | MODIFY | `crawl_live_discovery` keyword-no-results branch L267-284 | bounded caller no-results recovery loop (R8) + fail-open `capture_keyword_diagnostic`. |
| C7 | `apps/worker/src/egp_worker/browser_diagnostics.py` | CREATE | — | `capture_detail_diagnostic`, `capture_keyword_diagnostic`, `_build_manifest`, `_write_private_contained`, `_opaque_stem`. Reuses `egp_observability.redact_preview`/`tail_bounded_preview` + `hashlib.sha256`. |
| C8 | `apps/worker/src/egp_worker/main.py` | MODIFY | `_build_browser_settings` L37-90 | parse `diagnostics_dir` from payload key `browser_diagnostics_dir` **or** `EGP_BROWSER_DIAGNOSTICS_DIR` env (Path). |
| C9 | `tests/phase1/test_worker_browser_discovery.py` | MODIFY (append) | new test fns | T1-T13. |
| C10 | `tests/phase1/test_worker_browser_diagnostics.py` | CREATE | new file | T14-T19 (diagnostics module). |
| C11 | `tests/phase1/test_worker_live_discovery.py` | MODIFY (append) | new test fns | T21 (cross-keyword no-results), T22 (transient-recovered run succeeded). |
| C12 | `tests/phase1/test_worker_build_browser_settings.py` | MODIFY (append) | new test fn | T23 (settings parse: payload + env). |
| C13 | `tests/phase3/test_crawler_agent_inbox_processor.py` | GATE-ONLY (run, do NOT edit) | `:235` | doc-envelope rejection regression (T20). |

> Product code confined to `browser_discovery.py`, new `browser_diagnostics.py`, `main.py`, the enum.
> `workflows/discover.py`, `candidate_attempt_repo.py`, `candidate_key.py`, `agent_runtime.py`,
> `discovery_worker_dispatcher.py`, the API config — **untouched** (§10).

## §4 Function Contracts — FN1..FN10

```
FN1 (NEW, C1) class ProjectDetailReason(StrEnum)
    VALID="valid"; NAVIGATION_FAILURE="navigation_failure"; RESULTS_PAGE_RETURNED="results_page_returned";
    MISSING_REQUIRED_FIELDS="project_detail_missing_required_fields"; REJECTION_PAGE="rejection_page";
    PLACEHOLDER_DETAIL="placeholder_detail"; OUT_OF_SCOPE_STAGE="out_of_scope_stage"; UNKNOWN="unknown"

FN2 (NEW, C3) @dataclass(slots=True) class DetailOutcomeSink: reason: ProjectDetailReason = UNKNOWN
    The only out-parameter; carries no product data. Reset per attempt by the caller.

FN3 (NEW, C3) classify_detail_page(page, detail: dict[str, str]) -> ProjectDetailReason
    body = try page.inner_text("body") except Exception: ""
    if "ข้อความปฎิเสธ" in body or "E1530" in body: return REJECTION_PAGE
    if "จำนวนโครงการที่พบ" in body and "/procurement/" not in page.url: return RESULTS_PAGE_RETURNED
    placeholders = {"ชื่อโครงการ","ชื่อหน่วยงาน","เลขที่โครงการ","วิธีการจัดชื้อจัดจ้าง"}   # NOTE: no ""
    name=strip(detail.project_name); org=strip(detail.organization); num=strip(detail.project_number)
    if name in placeholders or org in placeholders or num in placeholders: return PLACEHOLDER_DETAIL
    if name and _compact_visible_text(name) in {<the two header-concat strings from L1465-1467>}: return PLACEHOLDER_DETAIL
    return VALID
    Post: pure; every DOM state that returned True in _detail_page_is_invalid EXCEPT pure-blank fields
          maps to a non-VALID reason (blanks now handled by FN4's missing branch). <50 lines.

FN4 (MODIFY, C4) open_and_extract_project(*, page, row_index, keyword, search_name=None,
        include_documents=False, source_status_text=TARGET_STATUS,
        outcome_sink: DetailOutcomeSink | None = None) -> dict[str, object] | None
    helper _set(r): if outcome_sink is not None: outcome_sink.reason = r
    - L1103 nav False -> _set(NAVIGATION_FAILURE); return None            (keep the existing click-failed log)
    - L1116 preliminary pricing -> _set(OUT_OF_SCOPE_STAGE); return None  (keep prelim-skip log)
    - L1128 reason = classify_detail_page(page, detail)
            if reason is not VALID: _set(reason); return None             (DO NOT emit project_detail_invalid here)
    - L1142 name/org/number check: if not name or not org or not number:
            _set(MISSING_REQUIRED_FIELDS); return None                    (DO NOT emit the stage here)
    - success: _set(VALID) before building payload; return payload
    Post: per-call return unchanged for all inputs (R2). No anomaly stage emitted (R3). Blanks (any of
          the three) -> None via missing branch (preserves today's drop).
    Notes: `number` added to the required check to preserve today's "empty project_number -> None".

FN5 (MODIFY, C5a) _collect_keyword_projects per-row body (L559-626) — replaces the single-open block:
    sink = DetailOutcomeSink()
    pass_sink = _callable_accepts_argument(open_project, "outcome_sink")
    def _open(idx):
        kw = {..existing open_project_kwargs.., "row_index": idx}
        if _callable_accepts_argument(open_project, "search_name"): kw["search_name"]=...
        if pass_sink: kw["outcome_sink"]=sink
        return _run_project_extraction_with_timeout(lambda: open_project(**kw), timeout_s=.., keyword=.., row_marker=row_info)
    payload = _open(resolved_row_index)
    restored = False
    if payload is None and sink.reason in _TRANSIENT_RETRY_REASONS:            # R4
        _return_to_results(page, settings, keyword=keyword, target_page_num=page_num, row_marker=row_info)
        retry_idx = _resolve_results_row_index(page, row_info)
        if retry_idx is not None: payload = _open(retry_idx)
        else: restored = True                                                 # stayed on results; skip 2nd restore
    if payload is not None and include_documents:
        payload = _collect_documents_for_payload(...)                         # unchanged
    if payload is None:
        _emit_terminal_detail_anomaly(sink.reason, keyword, row_info)         # R5 (once, terminal only)
        _safe_capture_detail_diagnostic(page, reason=sink.reason.value, marker=row_info,
                                        keyword=keyword, diagnostics_dir=settings.diagnostics_dir)  # R6
        seen_keys.add(str(row_info.get("project_number") or row_info["project_name"]).casefold())
        if not restored:
            _return_to_results(page, settings, keyword=keyword, target_page_num=page_num, row_marker=row_info)
        continue
    <valid path L607-626 UNCHANGED>
    Notes: _emit_terminal_detail_anomaly maps reason->stage per R5 (OUT_OF_SCOPE/UNKNOWN -> no emit).
           _safe_capture_detail_diagnostic wraps FN6 in try/except (2nd fail-open layer) and logs the
           browser_diagnostic status event. Narrow fake (no outcome_sink): pass_sink False -> sink stays
           UNKNOWN -> no retry, UNKNOWN ∉ anomaly/diagnostic sets -> byte-identical to today (R11).

FN6 (NEW, C7) capture_detail_diagnostic(page, *, reason: str, marker: dict, keyword: str,
        diagnostics_dir: Path | None) -> dict            # {"status": "captured"|"disabled"|"failed", ...}
    if diagnostics_dir is None: return {"status":"disabled"}
    try:
        png = page.screenshot(full_page=True)
        content_sha = hashlib.sha256(png).hexdigest()
        stem = _opaque_stem(keyword, marker, reason)     # sha256(keyword|number|name|reason)[:16]
        manifest = _build_manifest(reason, content_sha, len(png), keyword, marker)
        _write_private_contained(diagnostics_dir, f"{stem}.png", png)
        _write_private_contained(diagnostics_dir, f"{stem}.json", json.dumps(manifest, sort_keys=True).encode())
        return {"status":"captured", "artifact_stem":stem, "screenshot_sha256":content_sha}
    except Exception: return {"status":"failed"}          # never raises (R6)

FN7 (NEW, C7) capture_keyword_diagnostic(page, *, keyword, diagnostics_dir) -> dict
    same shape as FN6 with reason="keyword_no_results", marker={"keyword":keyword}.

FN8 (NEW, C7) _build_manifest(reason, content_sha, size, keyword, marker) -> dict
    {"schema":"egp.browser_diagnostic.v1","ts":<utc isoformat>,"reason":reason,
     "screenshot_sha256":content_sha,"screenshot_bytes":size,
     "keyword": tail_bounded_preview(keyword, limit=120),
     "marker": tail_bounded_preview(_marker_preview(marker), limit=240)}
    _marker_preview joins ONLY project_number|project_name|source_status_text (structured e-GP fields),
    passed through redact_preview via tail_bounded_preview. No url/html/cookies/headers/exception text.

FN9 (NEW, C7) _write_private_contained(dir: Path, name: str, data: bytes) -> None
    dir.mkdir(parents=True, exist_ok=True); os.chmod(dir, 0o700)
    p = (dir / name); assert p.resolve().is_relative_to(dir.resolve())      # containment
    with open(p, "wb", opener=lambda pth,fl: os.open(pth, fl, 0o600)) as f: f.write(data)

FN10 (MODIFY, C8) _build_browser_settings(payload) — add to the parse block:
    raw = settings_payload.get("browser_diagnostics_dir") or os.getenv("EGP_BROWSER_DIAGNOSTICS_DIR")
    if raw: updates["diagnostics_dir"] = Path(str(raw)).expanduser()
    (also add "browser_diagnostics_dir":"diagnostics_dir" to flat_key_map so a top-level payload key works)
    Post: default None when neither set (R10).
```

## §5 Test Plan — T1..T23 (RED-proof mandatory)

```
T1  test_classify_detail_page_rejection_for_e1530            Covers R1
    FakeDetailPage(body="ข้อความปฎิเสธ : E1530", url="/x"); classify(page,{}) == REJECTION_PAGE.
    RED: before C3 ImportError; naive VALID impl fails on enum equality.
T2  test_classify_detail_page_results_page_beats_placeholder_on_blanks   Covers R1 (Codex T3 fix)
    body contains "จำนวนโครงการที่พบ"; url has no "/procurement/"; detail has BLANK name/org.
    Assert == RESULTS_PAGE_RETURNED (NOT placeholder). Negative: url with "/procurement/" AND blanks -> VALID
    (falls through; missing handled by FN4). RED: a "placeholder-first / '' in set" impl returns PLACEHOLDER -> fails.
T3  test_classify_detail_page_placeholder_for_header_values  Covers R1
    detail={project_name:"ชื่อโครงการ",...}; == PLACEHOLDER_DETAIL. RED: as T1.
T4  test_classify_detail_page_valid_for_good_detail          Covers R1
    real name/org/number, benign body/url; == VALID. RED: as T1.
T5  test_open_and_extract_missing_required_when_blank        Covers R2 (missing reachable)
    monkeypatch extract_project_info -> {"project_name":"", "organization":"Org", "project_number":"1"} ;
    classify would be VALID (blank not placeholder); sink=DetailOutcomeSink();
    payload=open_and_extract_project(page=..,row_index=0,keyword="k",outcome_sink=sink)
    Assert payload is None AND sink.reason == MISSING_REQUIRED_FIELDS.
    RED: before C4, "" in placeholder set -> classify PLACEHOLDER -> sink != MISSING -> fails; also the
    number-in-check preserves empty-number drop.
T6  test_open_and_extract_writes_navigation_failure_to_sink  Covers R2
    monkeypatch navigate_to_project_by_row->False; assert None + sink NAVIGATION_FAILURE. RED: no _set at nav branch.
T7  test_open_and_extract_does_not_emit_invalid_stage        Covers R3
    capture _LIVE_PROGRESS_CALLBACK; drive a rejection detail; assert payload None AND no event stage in
    {"project_detail_invalid","project_detail_missing_required_fields"} was emitted by open_and_extract.
    RED: before C4 the stage IS emitted -> assertion fails (this is the anti-poisoning guard at the source).
T8  test_open_and_extract_return_unchanged_without_sink      Covers R2,R11
    existing rejection/prelim harness called WITHOUT outcome_sink -> payload None (optional-param guard).
T9  test_collect_retries_once_on_transient_then_succeeds     Covers R4
    fake open(outcome_sink): call#1 sink=NAVIGATION_FAILURE ret None; call#2 sink=VALID ret payload; count calls,
    record row_index each call. monkeypatch _return_to_results (spy) + _resolve_results_row_index -> 5 (distinct).
    Assert: 2 opens; 2nd open got row_index==5; _return_to_results called once; project_callback got payload.
    RED: before C5 -> 1 open, no callback -> fails; also asserts retry re-resolves the row (wrong-row guard).
T10 test_collect_does_not_retry_definitive_rejection         Covers R4
    fake reason=REJECTION_PAGE ret None always. Assert opens==1, _return_to_results called once (terminal), no retry.
    Guard against over-retry (any-None retry would make opens==2).
T11 test_collect_emits_terminal_anomaly_stage_once           Covers R5
    capture progress; fake reason=REJECTION_PAGE None. Assert exactly one "project_detail_invalid" stage
    emitted by the CALLER; for a MISSING fake -> exactly one "project_detail_missing_required_fields".
    RED: before C5 no caller emission (moved) -> 0 -> fails.
T12 test_collect_no_anomaly_stage_when_transient_recovers    Covers R5 (poisoning fix, unit level)
    fake: call#1 NAVIGATION_FAILURE None, call#2 VALID payload. Assert NO anomaly stage emitted at all.
    RED: an impl emitting on first attempt -> 1 stage -> fails.
T13 test_collect_captures_one_diagnostic_on_terminal_anomaly Covers R6
    settings.diagnostics_dir=tmp_path; fake reason=REJECTION_PAGE None; monkeypatch page.screenshot->b"PNG".
    Assert exactly one *.png + one *.json in tmp_path; a "browser_diagnostic" progress event status=="captured";
    crawl returns []. RED: before C5/C7 -> 0 files -> fails.
T14 test_capture_detail_diagnostic_writes_stem_png_and_manifest  Covers R7
    FakePage.screenshot(full_page=True)->b"PNGDATA"; m=capture_detail_diagnostic(..reason="rejection_page",
    marker={"project_name":"P","project_number":"123"},keyword="k",diagnostics_dir=tmp).
    Assert m["status"]=="captured"; manifest json on disk has screenshot_sha256==sha256(b"PNGDATA"),
    screenshot_bytes==7, reason=="rejection_page"; png bytes match. RED: ImportError before C7.
T15 test_capture_manifest_has_no_url_html_or_redactable_secret   Covers R7 (Codex T12 fix)
    marker={"project_name":"proj http://u:p@egp.go.th x","project_number":"Bearer abc.def.ghi"}.
    Assert serialized manifest contains NO "http", NO "://", NO "<html", NO "cookie"; and the url-cred /
    Bearer substrings are redacted to "[REDACTED]" (patterns redact_preview handles). No page.url anywhere.
    RED: including page.url or skipping redact_preview -> substring present -> fails.
T16 test_capture_disabled_when_dir_none                      Covers R6
    capture_detail_diagnostic(page,..,diagnostics_dir=None) -> {"status":"disabled"}; page.screenshot NOT called; nothing written.
T17 test_capture_fail_open_on_screenshot_error              Covers R6
    page.screenshot raises; -> {"status":"failed"}; no exception; no file. RED: unguarded impl raises.
T18 test_capture_files_are_private_and_contained            Covers R7
    after capture: both files stat().st_mode & 0o777 == 0o600; dir 0o700; each path is_relative_to(dir).
    RED: default-perm write -> 0o644 -> fails.
T19 test_capture_distinct_anomalies_do_not_overwrite        Covers R7 (Codex collision fix)
    two captures, SAME screenshot bytes, DIFFERENT marker/keyword -> two distinct *.json stems present.
    RED: sha-only naming collapses to one file -> count 1 -> fails.
T20 (GATE) tests/phase3/test_crawler_agent_inbox_processor.py::<the :235 doc-envelope rejection test>  Covers R? (doc-envelope preserved)
    Run unmodified; must stay green (evidence-only preserved).
T21 test_keyword_no_results_terminal_only_after_recovery_budget   Covers R8 (Codex CRITICAL fix)
    File: test_worker_live_discovery.py. Harness: a fake page where is_no_results_page is True on the
    first search of a NEW keyword (had_previous_results True) and becomes False after one caller re-search
    that then yields one eligible row; settings.search_page_recovery_retries=1.
    Assert: the keyword's project IS discovered (not a terminal keyword_no_results). Order: a
    "keyword_no_results_recovery" progress event precedes any terminal decision.
    RED: on current code the cross-keyword branch is terminal on first hit -> project missing -> fails.
T22 test_transient_recovered_candidate_leaves_run_succeeded  Covers R5 (integration, Codex-requested)
    File: test_worker_live_discovery.py (run_discover_workflow). One eligible row; open transient-first/
    valid-second (via a fake). Assert run status succeeded, error_count==0, no live_crawl_anomaly_count.
    RED: emitting the invalid stage on attempt#1 -> anomaly count>=1 -> run partial/failed -> fails.
T23 test_build_browser_settings_parses_diagnostics_dir      Covers R10
    File: test_worker_build_browser_settings.py. (a) payload browser_settings.browser_diagnostics_dir="/d/x"
    -> settings.diagnostics_dir==Path("/d/x"); (b) env EGP_BROWSER_DIAGNOSTICS_DIR set, no payload key ->
    parsed; (c) neither -> None. RED: before C8, field absent -> AttributeError / None.
```
Edge/negative: T2 (url branch + blanks), T5 (blank→missing not placeholder), T10 (over-retry), T12
(poisoning), T15/T18/T19 (leak/perms/collision), T16/T17 (dir-off/fail-open). Golden oracle: T14 real sha256.

## §6 Traceability Matrix

| Req | Fulfilled at — fn → realizing statement | Tests | Files | Slice |
|-----|------------------------------------------|-------|-------|-------|
| R1 | `classify_detail_page()` ordered returns (FN3); call site `open_and_extract` L1128 | T1-T4 | C3,C4 | S2 |
| R2 | `open_and_extract` `_set(...)` at each exit + `not name or not org or not number` (FN4) | T5,T6,T8 | C3,C4 | S2 |
| R3 | `open_and_extract` — the two anomaly `_log_live_progress` calls DELETED (FN4) | T7 | C4 | S2 |
| R4 | `_collect_keyword_projects` → `if payload is None and sink.reason in _TRANSIENT_RETRY_REASONS: … _open(retry_idx)` (FN5) | T9,T10 | C3,C5a | S3 |
| R5 | `_collect_keyword_projects` → `_emit_terminal_detail_anomaly(sink.reason,…)` in the terminal block (FN5) | T11,T12,T22 | C5a | S3 |
| R6 | `_collect_keyword_projects` → `_safe_capture_detail_diagnostic(...)` (FN5) + FN6 status/never-raise | T13,T16,T17 | C5a,C7 | S3,S4 |
| R7 | `_build_manifest` (FN8) + `_write_private_contained` (FN9) + `_opaque_stem` | T14,T15,T18,T19 | C7 | S4 |
| R8 | `crawl_live_discovery` L267-284 → bounded `while is_no_results_page … search_keyword` + `capture_keyword_diagnostic` (C6) | T21 | C6,C7 | S5 |
| R9 | timeout branch → `_safe_capture_detail_diagnostic(reason="project_timeout")` (C5b) | (T17 covers fail-open); manual | C5b,C7 | S3 |
| R10 | `_build_browser_settings` → `updates["diagnostics_dir"]=Path(...)` (FN10) | T23 | C8 | S4 |
| R11 | narrow-fake path `pass_sink=False` → UNKNOWN → no retry/anomaly/capture (FN5) | T8 + all existing suites + T20 | C4,C5a | S2,S3 |

Every R has ≥1 T; every T maps to ≥1 R; every R names its realizing call site (line anchors §3). Call
sites re-verified against current line numbers during Codex pass.

## §7 Wiring Verification

| New component | Entry point (runtime caller) | Registration site | Store / resource |
|---|---|---|---|
| `ProjectDetailReason` (C1) | `classify_detail_page`, `open_and_extract`, `_collect_keyword_projects` | import in `browser_discovery.py` top | in-memory enum |
| `classify_detail_page` (C3) | `open_and_extract_project` L1128 (sole former `_detail_page_is_invalid` site) | same module | detail DOM (`page`) |
| `DetailOutcomeSink` (C3) | `_collect_keyword_projects` creates; `open_and_extract` writes | same module | — |
| `capture_detail_diagnostic`/`capture_keyword_diagnostic` (C7) | `_collect_keyword_projects` FN5 + timeout branch C5b / `crawl_live_discovery` C6 | `from egp_worker.browser_diagnostics import …` in `browser_discovery.py` | files under `settings.diagnostics_dir` |
| `browser_diagnostic` progress event (FN5) | consumed by the live-progress callback / run log | existing `_log_live_progress` | run log (evidence) |
| `diagnostics_dir` setting (C2) | FN5 / C5b / C6 | `_build_browser_settings` C8 (payload key `browser_diagnostics_dir` **or** `EGP_BROWSER_DIAGNOSTICS_DIR`) | filesystem |

No orphans: both CREATE rows (enum, module) have runtime callers. `diagnostics_dir` default None → inert
until an operator sets the env var / payload key (dark).

## §8 Slice Plan — S1..S5 (compose into ONE F3 PR)

| ID | Scope (C/T ids) | Owner | Stop line | Oracle | Done when |
|----|-----------------|-------|-----------|--------|-----------|
| S1 | C1 (enum) | **Claude** | SL-1 | T1-T4 import; ruff | enum imports; values per FN1 |
| S2 | C3,C4 (classifier + typed exits + stage removal) | **Claude** | SL-3 | T1-T8; **all existing browser tests green** | per-call return unchanged; no anomaly stage from source |
| S3 | C5a,C5b (retry + terminal anomaly + diagnostic dispatch + timeout capture) | **Claude** | SL-3 | T9-T13,T22; existing collect_* green | ≤2 opens; anomaly once/terminal; fail-open capture |
| S4 | C2,C7,C8,C12 (settings + diagnostics module + env wiring) | **Claude** | SL-2 | T14-T19,T23 | manifest/no-leak/perms/containment/collision proven |
| S5 | C6,C11 (keyword recovery + diagnostic + regression) | **Claude** | SL-3 | T21 | keyword terminal-after-budget; project recovered |

**Owner rationale (oracle-driven):** every slice is **Claude-owned**. C7 is a **security boundary**
(no-secret-leak / private files) — never delegated. C4/C5/C6 are judgment-heavy, production,
fail-closed-adjacent browser wiring tightly coupled to F2's ledger and the crawler recovery ladder —
SL-3. C3 is pure with a strong oracle but defines the core contract and is small — Claude. Matches the
goal's request to implement via the g-coding lifecycle directly. g2-coding re-confirms stop lines at
build time; a user override wins.

Build order S1→S2→S3→S4→S5 (S3's diagnostic dispatch needs S4's module — co-develop S3/S4 or land S4's
module first). One branch, one PR.

## §9 Risks, Rollout, Rollback

| Risk | Trigger | Blast radius | Gate | Rollback |
|---|---|---|---|---|
| Retry doubles e-GP traffic | classifier mislabels definitive as transient | ≤1 extra detail nav/row | small explicit `_TRANSIENT_RETRY_REASONS`; `placeholder_detail` excluded; T10 | revert C5a hunk |
| Keyword recovery adds traffic | genuinely-empty keyword | ≤ budget (1) extra searches/keyword | bounded loop; completeness-first product | revert C6 |
| **Wrong-row retry (pre-existing, accepted)** | duplicate marker scores unique ≥70 on a wrong page after `_return_to_results` shortcuts | 1 candidate misattributed | `_resolve_results_row_index` requires unique ≥70; F3 adds only 1 bounded extra restore; NOT a new class of bug | revert C5a retry |
| Diagnostic leaks secrets/PII | manifest includes url/html/token | privacy | T15/T18 (no-leak, 0o600); structured-fields-only + redact; no url/html | `diagnostics_dir` None |
| Diagnostic fills disk | many anomalies | worker disk | ≤1 per terminal row/keyword; operator dir; **retention = PR-07 follow-up (noted)** | unset env |
| Behaviour drift breaks happy path | sink/return refactor changes a value | all crawls | R2/R11: return byte-identical; full existing suite | revert C4 |

**Rollout:** dark — `diagnostics_dir` default None; classifier/retry behaviour-preserving on the happy
path; keyword recovery only fires on empty results. Activation = operator sets `EGP_BROWSER_DIAGNOSTICS_DIR`.
**Rollback:** unset the env var and/or revert the C5a/C6 hunks; the enum + classifier are side-effect-free.

## §10 Do-Not-Touch List (verbatim — consumed by the diff audit)

- `apps/worker/src/egp_worker/workflows/discover.py` (F4/F5 territory: finalize_*, run authority, anomaly counting)
- `packages/db/src/egp_db/repositories/candidate_attempt_repo.py` (F4/F6)
- `packages/crawler-core/src/egp_crawler_core/candidate_key.py` (identity slice)
- `apps/worker/src/egp_worker/agent_runtime.py` (F5)
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`, `apps/api/src/egp_api/config.py` (PR-07 dispatcher plumbing)
- `packages/db/src/migrations/**`, `manifest.sha256` (no migration); metrics/alerts/health/docs (PR-07)
- The frozen exception-handler ladder logic in `_collect_keyword_projects` L627-703 — the ONLY permitted
  change is adding one fail-open `capture` call in the timeout branch (C5b); no control-flow edits.
- `tests/phase3/test_crawler_agent_inbox_processor.py` (run as a gate, never edit)
- Every existing test ASSERTION in `tests/phase1/test_worker_browser_discovery.py`,
  `tests/phase1/test_worker_live_discovery.py`, `tests/phase1/test_worker_build_browser_settings.py`,
  `tests/phase2/test_rules_api.py` — F3 only APPENDS new test functions.
- The acceptance tests T1-T23 once authored (diff audit checks they are not weakened).

## §11 Codex Adversarial Disposition (gpt-5.6-sol, xhigh — verdict: BLOCK on the first draft)

Every finding recorded accepted/rejected + reason. Verified against source before accepting.

**ACCEPTED & fixed:**
- **A1 (CRITICAL) classifier ordering / `""` in placeholder set.** Verified: `_detail_page_is_invalid`
  L1448 includes `""`; blanks would hit `placeholder_detail` before `missing`/`results-page`. Fix:
  Decision §1.2 — removed `""`, reordered rejection→results→placeholder→valid; missing handled in FN4
  covering name/org/number. New tests T2, T5.
- **A2 (CRITICAL) cross-keyword `keyword_no_results`.** Verified at `browser_discovery.py:2451-2454`:
  the retry is gated `(not had_previous_results or same_keyword_retry)`; a new keyword after prior rows
  is terminal on first empty hit. Fix: C6 bounded caller recovery loop (Decision §1.3). New test T21.
  (My original "already satisfied" claim was false.)
- **A3 (HIGH) anomaly poisoning.** Verified `discover.py:68-73` + anomaly count at ~L455: emitting the
  stage per-attempt poisons a retry-recovered run. Fix: R3+R5 — remove the emission from
  `open_and_extract` (C4), emit once from the terminal branch (C5a). discover.py untouched. Tests T7,T12,T22.
- **A4 (HIGH) fail-open bounded-absence flag missing + T10 contradiction.** Fix: FN6 returns a status
  and never raises; FN5 also wraps it (2-layer fail-open) and logs a `browser_diagnostic` event
  (captured/disabled/failed). Tests T13,T16,T17.
- **A5 (HIGH) wrong `main.py` function + non-existent env path.** Verified real fn `_build_browser_settings`
  (main.py:37) reads `payload["browser_settings"]`. Fix: C8/FN10 parse payload key OR
  `EGP_BROWSER_DIAGNOSTICS_DIR` env; test T23 in the correct settings test file.
- **A6 (HIGH) SIGALRM timeout bypass.** Fix: C5b adds a fail-open diagnostic in the timeout branch (R9)
  without restructuring the ladder. (Timeouts keep their existing recovery; not routed into typed retry —
  consistent with "retry only nav/results/missing".)
- **A7 (HIGH) double-restoration.** Fix: FN5 `restored` flag — the terminal block skips the 2nd
  `_return_to_results` when the retry could not resolve a row (already on results).
- **A8 (MEDIUM) redactor won't strip query secrets.** Fix: manifest carries only structured e-GP fields
  (never URLs/free text); redact_preview is defense-in-depth. T15 rewritten (drops the impossible
  `?t=SECRET` case; asserts no url/html + url-cred/Bearer redaction).
- **A9 (MEDIUM) sha-only filename collision.** Fix: FN6 opaque per-anomaly stem; content-sha in manifest. T19.
- **A10 (MEDIUM) file privacy.** Fix: FN9 writes 0o600 in a 0o700 dir. T18.
- **A11 (LOW) `page.screenshot` viewport default.** Fix: `full_page=True`.
- **A12 (LOW) test bookkeeping / vacuity.** Fixed: existing files labeled MODIFY(append); T2/T9/T10/T15/
  T19/T21 strengthened; added T20 (doc-envelope gate), T22 (integration), T23 (settings).
- **A13 (coverage) doc-envelope regression not in gate.** Fix: T20 runs `test_crawler_agent_inbox_processor.py:235` unmodified.

**REJECTED / SCOPED-OUT (with reason):**
- **R-a Full dispatcher/API diagnostics propagation** (`discovery_worker_dispatcher.py:420`, `config.py`):
  OUT of F3. The `EGP_BROWSER_DIAGNOSTICS_DIR` env fallback gives a real activation path on the
  residential-Mac worker without API plumbing; full payload propagation is a PR-07 operational follow-up.
  Recorded in §1 non-goals + §9.
- **R-b Wrong-row misattribution as a NEW bug:** it is a pre-existing property of
  `_return_to_results`/`_resolve_results_row_index` (unique ≥70 match required). F3 adds only one bounded
  extra restore and does not touch the frozen ladder page-validation. Accepted residual risk in §9; not
  fixed here (fixing it would touch frozen recovery logic outside F3's scope).
- **R-c `placeholder_detail` terminal:** Codex agreed the literal reading is defensible. Kept (Decision §1.1).
