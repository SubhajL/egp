#!/usr/bin/env python3
"""WS0 read-only discovery diagnostic.

Dumps the e-GP search-results rows for a keyword EXACTLY as the crawler sees them,
WITHOUT applying persistence, opening detail pages, or touching the database. It
reuses the production browser path (launch_real_chrome -> connect -> search) so the
dump faithfully reproduces what discovery scans, then reports, per row:

  - the raw cell texts and the detected results-table header row (to expose any
    column-index drift behind a stale status-column assumption);
  - whether the row passes the strict ``status_matches_target()`` row filter;
  - whether the more permissive ``is_invitation_stage_status()`` persistence rule
    would have accepted it (divergence = a project the row filter wrongly drops);
  - any ``SKIP_KEYWORDS_IN_PROJECT`` hit;
  - the final eligibility decision.

It also highlights any --expect project numbers (the known-missed ones) so we can
see precisely why each was dropped. See the unified plan:
``coding-logs/2026-06-14-11-33-19 Coding Log (discovery-completeness-unified-plan).md`` (WS0).

This is a DIAGNOSTIC, not product code. Read-only against e-GP.

CAVEAT: it launches a real Chrome on the persistent profile. Stop the keep-warm
Chrome/timer first, or pass --profile-dir pointing at a *copy* of the profile, to
avoid a singleton-profile conflict.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright

from egp_worker import browser_discovery as bd
from egp_worker.browser_discovery import (
    BrowserDiscoverySettings,
    PaginationAdvanceResult,
    ParsedResultsPage,
)
from egp_crawler_core.invitation_rules import is_invitation_stage_status
from egp_shared_types.enums import DiscoveryPaginationOutcome


KNOWN_MISSED_DEFAULT = [
    "69059071027",
    "69049396882",
    "69029301629",
    "69039582244",
    "68119364483",
]


def _safe_text(element) -> str:
    try:
        return re.sub(r"\s+", " ", (element.inner_text() or "")).strip()
    except Exception:
        return ""


def _build_settings(args: argparse.Namespace) -> BrowserDiscoverySettings:
    profile_dir = (
        args.profile_dir
        or os.environ.get("EGP_BROWSER_PERSISTENT_PROFILE_DIR")
        or os.environ.get("EGP_BROWSER_PROFILE_DIR")
    )
    if not profile_dir:
        raise SystemExit(
            "No browser profile dir. Pass --profile-dir or set "
            "EGP_BROWSER_PERSISTENT_PROFILE_DIR (run via scripts/run_remote_crawl.sh diagnose)."
        )
    # NOTE: BrowserDiscoverySettings is slots=True, so reading the class attribute
    # returns a slot descriptor, not the default. Use the literal default instead.
    chrome_path = (
        args.chrome_path
        or os.environ.get("EGP_CHROME_PATH")
        or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    cdp_port = int(
        args.cdp_port
        or os.environ.get("EGP_BROWSER_WARMUP_CDP_PORT")
        or os.environ.get("EGP_CDP_PORT")
        or 9320
    )
    return BrowserDiscoverySettings(
        chrome_path=chrome_path,
        cdp_port=cdp_port,
        browser_profile_dir=Path(profile_dir).expanduser(),
        max_pages_per_keyword=int(args.max_pages),
        proxy_server=(os.environ.get("EGP_BROWSER_PROXY_SERVER", "").strip() or None),
        use_xvfb=str(os.environ.get("EGP_BROWSER_USE_XVFB", "")).strip().lower()
        in {"1", "true", "yes", "on"},
    )


def _parsed_page(page_or_snapshot) -> ParsedResultsPage:
    if isinstance(page_or_snapshot, ParsedResultsPage):
        return page_or_snapshot
    return bd.parse_results_page(page_or_snapshot)


def _dump_headers(page_or_snapshot) -> list[str]:
    return list(_parsed_page(page_or_snapshot).headers)


def _dump_rows(page_or_snapshot) -> list[dict]:
    parsed = _parsed_page(page_or_snapshot)
    out: list[dict] = []
    for row in parsed.rows:
        cell_texts = list(row.cell_texts)
        status_text = row.source_status_text
        project_name = row.project_name
        organization = row.organization_name
        project_number = row.project_number or ""
        full_text = " ".join(cell_texts)
        passes_status = bd.status_matches_target(status_text) if status_text else False
        persist_ok = is_invitation_stage_status(status_text)
        skip_hit = row.skip_keyword_hit
        out.append(
            {
                "cell_count": len(cell_texts),
                "cells": cell_texts,
                # Retain the historical report key for ordinary diagnostics;
                # its value now comes from the shared named-column parser.
                "status_cell_idx4": status_text,
                "status_text": status_text,
                "organization": organization,
                "project_name": project_name,
                "project_number": project_number,
                "row_passes_status_filter": passes_status,
                "would_persist_invitation_rule": persist_ok,
                "status_filter_vs_persist_divergence": bool(
                    persist_ok and not passes_status
                ),
                "skip_keyword_hit": skip_hit,
                "eligible": bool(passes_status and not skip_hit),
                "full_text_sample": full_text[:400],
            }
        )
    return out


def _results_found_count(page) -> str | None:
    """e-GP renders 'จำนวนโครงการที่พบ : N' — the ground-truth result count."""
    try:
        body = page.inner_text("body")
    except Exception:
        return None
    match = re.search(r"จำนวนโครงการที่พบ\s*:?\s*([0-9,]+)", body)
    return match.group(1) if match else None


def _dump_all_tables(page) -> list[dict]:
    """Dump EVERY <table> so we can see if find_results_table picked the wrong one
    (e.g. a 1-row summary table while the real 10-row results table sits elsewhere)."""
    out: list[dict] = []
    try:
        tables = page.query_selector_all("table")
    except Exception:
        tables = []
    for idx, table in enumerate(tables):
        try:
            ths = [_safe_text(th) for th in table.query_selector_all("th")]
        except Exception:
            ths = []
        try:
            body_rows = table.query_selector_all("tbody tr")
        except Exception:
            body_rows = []
        try:
            matches = bool(bd._table_matches_results_headers(table))
        except Exception:
            matches = False
        first_row_cells: list[str] = []
        if body_rows:
            try:
                first_row_cells = [
                    _safe_text(c) for c in body_rows[0].query_selector_all("td")
                ]
            except Exception:
                first_row_cells = []
        out.append(
            {
                "table_index": idx,
                "matches_results_headers": matches,
                "tbody_row_count": len(body_rows),
                "header_ths": ths,
                "first_row_cells": first_row_cells,
            }
        )
    return out


def _advance_page(
    page,
    settings: BrowserDiscoverySettings,
    *,
    page_num: int,
) -> PaginationAdvanceResult:
    """Advance using the production typed pagination state machine."""
    return bd.advance_results_page(page, settings, page_num=page_num)


OBSERVATION_MAX_PAGES = 15

_OBSERVATION_OUTCOME_ERRORS = {
    DiscoveryPaginationOutcome.KEYWORD_NO_RESULTS: "keyword_no_results",
    DiscoveryPaginationOutcome.NEXT_CONTROL_HIDDEN: "pagination_control_hidden",
    DiscoveryPaginationOutcome.NEXT_CLICK_FAILED: "pagination_next_click_failed",
    DiscoveryPaginationOutcome.PAGE_CHANGE_TIMEOUT: "pagination_page_change_timeout",
    DiscoveryPaginationOutcome.UNEXPECTED_NO_RESULTS: "pagination_unexpected_no_results",
    DiscoveryPaginationOutcome.SITE_ERROR: "pagination_site_error",
}


def _write_observation_receipt(
    path: str,
    *,
    release_sha: str,
    status: str,
    checks: dict[str, object],
    errors: list[str],
) -> None:
    """Write only the bounded, identifier-free observation contract."""
    receipt = {
        "schema_version": 1,
        "stage": "observation",
        "status": status,
        "release_sha": release_sha,
        "observed_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
    }
    receipt_path = Path(path)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _observation_checks(
    *,
    browser_started: bool,
    eligible_invitation_page: int | None,
    keyword_exact: bool,
    page_sequence: list[int],
    terminal_outcome: DiscoveryPaginationOutcome | None,
) -> dict[str, object]:
    return {
        "browser_started": browser_started,
        "eligible_invitation_page": eligible_invitation_page,
        "keyword_exact": keyword_exact,
        "max_pages_per_keyword": OBSERVATION_MAX_PAGES,
        "page_sequence": list(page_sequence),
        "persistence_disabled": True,
        "shared_parser": bool(page_sequence),
        "terminal_outcome": terminal_outcome.value if terminal_outcome else None,
    }


def _run_observation_canary(
    args: argparse.Namespace,
    *,
    release_sha: str,
) -> int:
    """Run the identifier-free browser observation and emit its receipt."""
    settings: BrowserDiscoverySettings | None = None
    page_sequence: list[int] = []
    eligible_invitation_page: int | None = None
    terminal_outcome: DiscoveryPaginationOutcome | None = None
    browser_started = False
    keyword_exact = bool(args.keyword and args.keyword == args.keyword.strip())
    errors: list[str] = []
    pw = browser = chrome_proc = None

    def _observe() -> bool:
        nonlocal browser_started, chrome_proc, eligible_invitation_page, page_sequence
        nonlocal pw, settings, terminal_outcome

        try:
            settings = _build_settings(args)
        except SystemExit:
            errors.append("browser_start_failed")
            return False
        # Observation must always launch a fresh, real Chrome session. Argument
        # validation rejects --attach before this function is reached.
        try:
            chrome_proc = bd.launch_real_chrome(settings, clear_singleton_locks=True)
            pw = sync_playwright().start()
            browser, page = bd.connect_playwright_to_chrome(pw, settings)
            browser_started = True
        except Exception:
            errors.append("browser_start_failed")
            return False

        bd._goto_with_recovery(page, bd.MAIN_PAGE_URL, settings)
        if not bd.wait_for_cloudflare_or_operator(page, settings):
            errors.append("browser_navigation_failed")
            return False
        bd._goto_with_recovery(page, bd.SEARCH_URL, settings)
        if not bd.wait_for_cloudflare_or_operator(
            page, settings, require_search_controls=True
        ):
            errors.append("browser_navigation_failed")
            return False

        bd.search_keyword(page, args.keyword, settings)
        if bd.is_no_results_page(page):
            errors.append("keyword_no_results")
            return False

        page_num = 1
        while page_num <= settings.max_pages_per_keyword:
            parsed = bd.parse_results_page(page)
            page_sequence.append(page_num)
            for row in parsed.rows:
                if (
                    page_num >= 2
                    and row.status_eligible
                    and is_invitation_stage_status(row.source_status_text)
                    and eligible_invitation_page is None
                ):
                    eligible_invitation_page = page_num

            advance = bd.advance_results_page(page, settings, page_num=page_num)
            terminal_outcome = advance.outcome
            if advance.outcome is DiscoveryPaginationOutcome.ADVANCED:
                if advance.next_page_num != page_num + 1:
                    errors.append("page_sequence_not_contiguous")
                    return False
                page_num = advance.next_page_num
                terminal_outcome = None
                continue
            break

        if terminal_outcome is None:
            errors.append("pagination_terminal_missing")
            return False
        if terminal_outcome in _OBSERVATION_OUTCOME_ERRORS:
            errors.append(_OBSERVATION_OUTCOME_ERRORS[terminal_outcome])
            return False
        if terminal_outcome is DiscoveryPaginationOutcome.MAX_PAGES_REACHED:
            if page_sequence[-1] != OBSERVATION_MAX_PAGES:
                errors.append("max_pages_before_pinned_cap")
                return False
        elif terminal_outcome not in {
            DiscoveryPaginationOutcome.NEXT_CONTROL_ABSENT,
            DiscoveryPaginationOutcome.NEXT_CONTROL_DISABLED,
        }:
            errors.append("pagination_outcome_invalid")
            return False

        if page_sequence != list(range(1, page_sequence[-1] + 1)):
            errors.append("page_sequence_not_contiguous")
            return False
        if page_sequence[-1] < 5:
            errors.append("page_sequence_incomplete")
            return False
        if eligible_invitation_page is None:
            errors.append("eligible_invitation_page_missing")
            return False
        return True

    success = False
    try:
        success = _observe()
    except Exception:
        errors.append("observation_failed")
    finally:
        try:
            bd.safe_shutdown(browser=browser, pw=pw, chrome_proc=chrome_proc)
        except Exception:
            errors.append("browser_shutdown_failed")
            success = False
        checks = _observation_checks(
            browser_started=browser_started,
            eligible_invitation_page=eligible_invitation_page,
            keyword_exact=keyword_exact,
            page_sequence=page_sequence,
            terminal_outcome=terminal_outcome,
        )
        _write_observation_receipt(
            args.receipt,
            release_sha=release_sha,
            status="accepted" if not errors else "rejected",
            checks=checks,
            errors=errors,
        )
    return 0 if success and not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only e-GP search-row diagnostic."
    )
    parser.add_argument("--keyword", default="วิเคราะห์ข้อมูล")
    parser.add_argument("--max-pages", type=int, default=15)
    parser.add_argument("--profile-dir", default=None)
    parser.add_argument("--chrome-path", default=None)
    parser.add_argument("--cdp-port", default=None)
    parser.add_argument(
        "--expect",
        nargs="*",
        default=KNOWN_MISSED_DEFAULT,
        help="Project numbers to highlight (default: the 5 known-missed).",
    )
    parser.add_argument("--out-dir", default="artifacts/diagnostics")
    parser.add_argument(
        "--attach",
        action="store_true",
        help="Connect to an already-running warmed Chrome (CDP) instead of launching one. "
        "Use this when the keep-warm Chrome is up to avoid a profile-lock conflict.",
    )
    parser.add_argument(
        "--observation-canary",
        action="store_true",
        help="Run the identifier-free, non-persisting browser observation canary.",
    )
    parser.add_argument(
        "--receipt",
        default=None,
        help="Path for the bounded observation-canary receipt.",
    )
    args = parser.parse_args(argv)

    if args.observation_canary:
        if args.attach:
            parser.error("--observation-canary cannot be used with --attach")
        if not args.receipt:
            parser.error("--observation-canary requires --receipt")
        if args.max_pages != OBSERVATION_MAX_PAGES:
            parser.error("--observation-canary requires --max-pages 15")
        release_sha = os.environ.get("EGP_RELEASE_SHA", "")
        if not re.fullmatch(r"[0-9a-f]{40}", release_sha):
            parser.error("--observation-canary requires a 40-character lower-hex EGP_RELEASE_SHA")
        return _run_observation_canary(args, release_sha=release_sha)

    settings = _build_settings(args)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"search_rows_{stamp}.json"

    report: dict = {
        "keyword": args.keyword,
        "max_pages": args.max_pages,
        "cdp_port": settings.cdp_port,
        "profile_dir": str(settings.browser_profile_dir),
        "pages": [],
        "status_buckets": {},
        "totals": {},
        "expected_lookup": {},
        "error": None,
    }
    status_counter: Counter[str] = Counter()
    all_rows: list[dict] = []

    pw = browser = chrome_proc = None
    try:
        if not args.attach:
            chrome_proc = bd.launch_real_chrome(settings, clear_singleton_locks=True)
        pw = sync_playwright().start()
        browser, page = bd.connect_playwright_to_chrome(pw, settings)
        bd._goto_with_recovery(page, bd.MAIN_PAGE_URL, settings)
        time.sleep(3)
        bd.wait_for_cloudflare(page, settings.cloudflare_timeout_ms)
        bd._goto_with_recovery(page, bd.SEARCH_URL, settings)
        time.sleep(5)
        bd.wait_for_cloudflare(page, settings.cloudflare_timeout_ms)

        bd.search_keyword(page, args.keyword, settings)
        if bd.is_no_results_page(page):
            report["error"] = "no_results_page"
            print(
                f"[diagnose] e-GP reported NO RESULTS for {args.keyword!r}", flush=True
            )
        else:
            page_num = 1
            while page_num <= args.max_pages:
                parsed = bd.parse_results_page(page)
                headers = _dump_headers(parsed) if page_num == 1 else None
                rows = _dump_rows(parsed)
                all_tables = _dump_all_tables(page)
                found_count = _results_found_count(page)
                all_rows.extend(rows)
                eligible = sum(1 for r in rows if r["eligible"])
                divergent = sum(
                    1 for r in rows if r["status_filter_vs_persist_divergence"]
                )
                for r in rows:
                    status_counter[r["status_cell_idx4"] or "<empty>"] += 1
                page_entry = {
                    "page_num": page_num,
                    "egp_results_found_count": found_count,
                    "matched_table_row_count": len(rows),
                    "eligible_count": eligible,
                    "divergent_count": divergent,
                    "all_tables": all_tables,
                    "rows": rows,
                }
                if headers is not None:
                    page_entry["detected_headers"] = headers
                report["pages"].append(page_entry)
                tables_brief = " ".join(
                    f"t{t['table_index']}:{t['tbody_row_count']}r{'*' if t['matches_results_headers'] else ''}"
                    for t in all_tables
                )
                print(
                    f"[diagnose] page {page_num}: egp_found={found_count} "
                    f"matched_table_rows={len(rows)} eligible={eligible} "
                    f"divergent={divergent} | tables[{tables_brief}] (*=matched)",
                    flush=True,
                )
                advance = _advance_page(page, settings, page_num=page_num)
                page_entry["pagination_outcome"] = advance.outcome.value
                if advance.outcome is not DiscoveryPaginationOutcome.ADVANCED:
                    break
                page_num = advance.next_page_num
    except Exception as exc:  # diagnostic: capture and still write partial report
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[diagnose] ERROR: {report['error']}", flush=True)
    finally:
        bd.safe_shutdown(browser=browser, pw=pw, chrome_proc=chrome_proc)

    report["status_buckets"] = dict(status_counter.most_common())
    report["totals"] = {
        "rows_scanned": len(all_rows),
        "eligible": sum(1 for r in all_rows if r["eligible"]),
        "divergent_row_drops": sum(
            1 for r in all_rows if r["status_filter_vs_persist_divergence"]
        ),
        "skip_keyword_hits": sum(1 for r in all_rows if r["skip_keyword_hit"]),
    }
    for num in args.expect:
        match = next(
            (
                r
                for r in all_rows
                if r["project_number"] == num
                or num in " ".join(r["cells"])
                or num in r["full_text_sample"]
            ),
            None,
        )
        report["expected_lookup"][num] = (
            {
                "found_in_scan": True,
                "status_cell_idx4": match["status_cell_idx4"],
                "row_passes_status_filter": match["row_passes_status_filter"],
                "would_persist_invitation_rule": match["would_persist_invitation_rule"],
                "skip_keyword_hit": match["skip_keyword_hit"],
                "eligible": match["eligible"],
            }
            if match
            else {"found_in_scan": False}
        )

    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== SUMMARY ===", flush=True)
    print(
        f"keyword={args.keyword!r}  rows_scanned={report['totals']['rows_scanned']}  "
        f"eligible={report['totals']['eligible']}  "
        f"divergent_row_drops={report['totals']['divergent_row_drops']}  "
        f"skip_hits={report['totals']['skip_keyword_hits']}",
        flush=True,
    )
    print("status buckets (status-cell text -> count):", flush=True)
    for status, count in status_counter.most_common():
        print(f"  {count:4d}  {status}", flush=True)
    print("known-missed lookup:", flush=True)
    for num, info in report["expected_lookup"].items():
        print(f"  {num}: {info}", flush=True)
    print(f"\nfull dump written to: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
