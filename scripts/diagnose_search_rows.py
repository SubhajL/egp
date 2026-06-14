#!/usr/bin/env python3
"""WS0 read-only discovery diagnostic.

Dumps the e-GP search-results rows for a keyword EXACTLY as the crawler sees them,
WITHOUT applying persistence, opening detail pages, or touching the database. It
reuses the production browser path (launch_real_chrome -> connect -> search) so the
dump faithfully reproduces what discovery scans, then reports, per row:

  - the raw cell texts and the detected results-table header row (to expose any
    column-index drift behind the hard-coded ``cells[4]`` assumption);
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
from egp_worker.browser_discovery import BrowserDiscoverySettings
from egp_crawler_core.invitation_rules import is_invitation_stage_status


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


def _dump_headers(page) -> list[str]:
    table = bd.find_results_table(page)
    if not table:
        return []
    try:
        return [_safe_text(th) for th in table.query_selector_all("th")]
    except Exception:
        return []


def _dump_rows(page) -> list[dict]:
    extract_num = getattr(bd, "_extract_project_number_from_text", None)
    out: list[dict] = []
    for row in bd.get_results_rows(page):
        try:
            cells = row.query_selector_all("td")
        except Exception:
            cells = []
        cell_texts = [_safe_text(c) for c in cells]
        status_text = cell_texts[4] if len(cell_texts) > 4 else ""
        project_name = cell_texts[2] if len(cell_texts) > 2 else ""
        organization = cell_texts[1] if len(cell_texts) > 1 else ""
        full_text = _safe_text(row)
        project_number = ""
        if extract_num is not None:
            try:
                project_number = extract_num(full_text) or ""
            except Exception:
                project_number = ""
        passes_status = bd.status_matches_target(status_text) if status_text else False
        persist_ok = is_invitation_stage_status(status_text)
        skip_hit = next(
            (kw for kw in bd.SKIP_KEYWORDS_IN_PROJECT if kw in project_name), None
        )
        out.append(
            {
                "cell_count": len(cell_texts),
                "cells": cell_texts,
                "status_cell_idx4": status_text,
                "organization": organization,
                "project_name": project_name,
                "project_number": project_number,
                "row_passes_status_filter": passes_status,
                "would_persist_invitation_rule": persist_ok,
                "status_filter_vs_persist_divergence": bool(persist_ok and not passes_status),
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
                first_row_cells = [_safe_text(c) for c in body_rows[0].query_selector_all("td")]
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


def _advance_page(page, settings: BrowserDiscoverySettings) -> bool:
    """Click the next-page control. Returns False when there is no further page."""
    previous_marker = bd.get_results_page_marker(page)
    next_btn = page.query_selector(bd.NEXT_PAGE_SELECTOR)
    if not (next_btn and next_btn.is_visible()):
        return False
    try:
        page.evaluate("(el) => el.click()", next_btn)
    except Exception:
        try:
            next_btn.click(timeout=10_000)
        except Exception:
            return False
    time.sleep(3)
    if not bd.wait_for_results_page_change(
        page, previous_marker, timeout_ms=settings.nav_timeout_ms
    ):
        return False
    if bd.is_no_results_page(page):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only e-GP search-row diagnostic.")
    parser.add_argument("--keyword", default="วิเคราะห์ข้อมูล")
    parser.add_argument("--max-pages", type=int, default=7)
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
    args = parser.parse_args(argv)

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
            print(f"[diagnose] e-GP reported NO RESULTS for {args.keyword!r}", flush=True)
        else:
            for page_num in range(1, args.max_pages + 1):
                headers = _dump_headers(page) if page_num == 1 else None
                rows = _dump_rows(page)
                all_tables = _dump_all_tables(page)
                found_count = _results_found_count(page)
                all_rows.extend(rows)
                eligible = sum(1 for r in rows if r["eligible"])
                divergent = sum(1 for r in rows if r["status_filter_vs_persist_divergence"])
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
                if not _advance_page(page, settings):
                    break
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
                if r["project_number"] == num or num in " ".join(r["cells"]) or num in r["full_text_sample"]
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

    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===", flush=True)
    print(f"keyword={args.keyword!r}  rows_scanned={report['totals']['rows_scanned']}  "
          f"eligible={report['totals']['eligible']}  "
          f"divergent_row_drops={report['totals']['divergent_row_drops']}  "
          f"skip_hits={report['totals']['skip_keyword_hits']}", flush=True)
    print("status buckets (cells[4] text -> count):", flush=True)
    for status, count in status_counter.most_common():
        print(f"  {count:4d}  {status}", flush=True)
    print("known-missed lookup:", flush=True)
    for num, info in report["expected_lookup"].items():
        print(f"  {num}: {info}", flush=True)
    print(f"\nfull dump written to: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
