"""Browser-driven document download extraction for worker workflows."""

from __future__ import annotations

import base64
import logging
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from egp_document_classifier import classify_document
from egp_db.google_drive import GoogleDriveOAuthConfig
from egp_db.onedrive import OneDriveOAuthConfig
from egp_shared_types.enums import DocumentPhase, DocumentType, ProjectState

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
except (
    ModuleNotFoundError
):  # pragma: no cover - exercised in CI import environments without Playwright

    class PlaywrightTimeout(Exception):
        pass


from .browser_site_state import clear_site_error_toast
from .workflows.document_ingest import ingest_document_artifact

logger = logging.getLogger(__name__)

DOCS_TO_DOWNLOAD = [
    "ประกาศเชิญชวน",
    "ประกาศราคากลาง",
    "ร่างเอกสารประกวดราคา",
    "เอกสารประกวดราคา",
]
DETAIL_PAGE_LINK_FALLBACK_TERMS = (
    "แผนการจัดซื้อ",
    "procurement plan",
    "showhtmlfile",
)
TOR_DOC_MATCH_TERMS = [
    "ร่างขอบเขตของงาน",
    "ร่างเอกสารประกวดราคา",
    "เอกสารประกวดราคา",
    "terms of reference",
    "tor",
]
DRAFT_TOR_DOC_MATCH_TERMS = [
    "ร่างขอบเขตของงาน",
    "ร่างเอกสารประกวดราคา",
    "draft tor",
    "draft terms of reference",
]
ALLOWED_DOWNLOAD_HOST_SUFFIXES = ("gprocurement.go.th",)
DOWNLOAD_TIMEOUT = 30_000
SUBPAGE_DOWNLOAD_TIMEOUT = 90_000
DOWNLOAD_EVENT_TIMEOUT = 15_000
DOWNLOAD_CLICK_RETRIES = 2
TOAST_RECOVERY_RETRIES = 2
IMMEDIATE_MODAL_CHECK_TIMEOUT_S = 1.0
NEW_PAGE_ACTIONABLE_TIMEOUT_S = 4.0
NEW_PAGE_ACTIONABLE_POLL_INTERVAL_S = 0.25
SYSTEM_MODAL_SELECTORS = ".modal.show, .modal.fade.show, .swal2-popup, [role='dialog']"
MISSING_FILE_MODAL_MARKERS = (
    "E4514",
    "ค้นหาไฟล์เอกสารไม่พบ",
    "ไม่พบไฟล์ในโครงการนี้",
)


class KnownMissingFileModal(Exception):
    """Raised when e-GP reports a deterministic missing source document."""


def _trace_document_progress(stage: str, **fields: object) -> None:
    parts = [f"stage={stage}"]
    for key, value in fields.items():
        rendered = str(value).replace("\n", " ").strip()
        if rendered:
            parts.append(f"{key}={rendered}")
    print(f"DOCUMENT_PROGRESS {' | '.join(parts)}", flush=True)


def collect_downloaded_documents(
    page,
    *,
    source_status_text: str = "",
    source_page_text: str = "",
    project_state: str | None = None,
) -> list[dict[str, object]]:
    downloaded_documents: list[dict[str, object]] = []
    seen_files: set[tuple[str, str]] = set()
    detail_url = _get_page_url(page)
    document_context = _build_document_context(
        source_status_text=source_status_text,
        source_page_text=source_page_text,
        project_state=project_state,
    )
    dismiss_modal(page)
    for target_doc in DOCS_TO_DOWNLOAD:
        started_at = time.monotonic()
        _trace_document_progress(
            "target_start",
            target_doc=target_doc,
            project_state=project_state or "",
            source_status_text=source_status_text,
        )
        try:
            target_documents = _download_one_document(
                page, target_doc, document_context=document_context
            )
        except Exception as exc:
            logger.warning(
                "e-GP document target collection failed; continuing",
                extra={
                    "egp_event": "document_target_failed",
                    "target_doc": target_doc,
                    "project_detail_url": detail_url,
                    "error": str(exc),
                },
            )
            _trace_document_progress(
                "target_failed",
                target_doc=target_doc,
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
                error=str(exc),
            )
            target_documents = []
        for document in target_documents:
            resolved_document = _apply_document_context(document, document_context)
            dedupe_key = (
                str(resolved_document.get("source_label") or ""),
                str(resolved_document.get("file_name") or "").casefold(),
            )
            if dedupe_key in seen_files:
                continue
            seen_files.add(dedupe_key)
            downloaded_documents.append(resolved_document)
        _trace_document_progress(
            "target_finished",
            target_doc=target_doc,
            document_count=len(downloaded_documents),
            elapsed_ms=int((time.monotonic() - started_at) * 1000),
        )
        _ensure_project_detail_page(page, detail_url=detail_url)
    fallback_started_at = time.monotonic()
    _trace_document_progress("fallback_start", detail_url=detail_url)
    for document in _collect_detail_page_link_documents(
        page,
        detail_url=detail_url,
        document_context=document_context,
    ):
        resolved_document = _apply_document_context(document, document_context)
        dedupe_key = (
            str(resolved_document.get("source_label") or ""),
            str(resolved_document.get("file_name") or "").casefold(),
        )
        if dedupe_key in seen_files:
            continue
        seen_files.add(dedupe_key)
        downloaded_documents.append(resolved_document)
    _trace_document_progress(
        "fallback_finished",
        document_count=len(downloaded_documents),
        elapsed_ms=int((time.monotonic() - fallback_started_at) * 1000),
    )
    return downloaded_documents


def ingest_downloaded_documents(
    *,
    artifact_root: Path | str,
    database_url: str | None,
    tenant_id: str,
    project_id: str,
    downloaded_documents: list[dict[str, object]],
    storage_credentials_secret: str | None = None,
    google_drive_oauth_config: GoogleDriveOAuthConfig | None = None,
    google_drive_client: object | None = None,
    onedrive_oauth_config: OneDriveOAuthConfig | None = None,
    onedrive_client: object | None = None,
) -> list:
    results = []
    for document in downloaded_documents:
        results.append(
            ingest_document_artifact(
                artifact_root=artifact_root,
                database_url=database_url,
                storage_credentials_secret=storage_credentials_secret,
                google_drive_oauth_config=google_drive_oauth_config,
                google_drive_client=google_drive_client,
                onedrive_oauth_config=onedrive_oauth_config,
                onedrive_client=onedrive_client,
                tenant_id=tenant_id,
                project_id=project_id,
                file_name=str(document["file_name"]),
                file_bytes=bytes(document["file_bytes"]),
                source_label=str(document.get("source_label") or ""),
                source_status_text=str(document.get("source_status_text") or ""),
                source_page_text=str(document.get("source_page_text") or ""),
                project_state=(
                    str(document["project_state"])
                    if document.get("project_state") is not None
                    else None
                ),
            )
        )
    return results


def _download_one_document(
    page,
    target_doc: str,
    *,
    document_context: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    _trace_document_progress("target_prepare_start", target_doc=target_doc)
    dismiss_modal(page)
    _trace_document_progress("target_prepare_finished", target_doc=target_doc)
    _sleep(0.5)
    is_final_tor_target = target_doc == "เอกสารประกวดราคา"
    downloadable_rows = []
    _trace_document_progress("table_scan_start", target_doc=target_doc)
    try:
        tables = page.query_selector_all("table")
    except Exception:
        tables = []
    for table in tables:
        header_combined = " ".join(
            header.inner_text().strip() for header in table.query_selector_all("th")
        )
        if "ดูข้อมูล" not in header_combined and "ดาวน์โหลด" not in header_combined:
            continue
        downloadable_rows.extend(table.query_selector_all("tbody tr"))
    _trace_document_progress(
        "table_scan_finished",
        target_doc=target_doc,
        row_count=len(downloadable_rows),
    )

    for row in downloadable_rows:
        cells = row.query_selector_all("td")
        if len(cells) < 3:
            continue
        doc_name = ""
        for cell in cells:
            text = cell.inner_text().strip()
            if _matches_target_document_label(target_doc, text):
                doc_name = text
                break
        if not doc_name:
            continue
        _trace_document_progress("row_matched", target_doc=target_doc, doc_name=doc_name)
        last_cell = cells[-1]
        clickable = (
            last_cell.query_selector("a[href], a[onclick], button:not([disabled]), [role='button']")
            or last_cell.query_selector("a, button, [role='button']")
            or last_cell
        )
        _trace_document_progress("clickable_selected", target_doc=target_doc, doc_name=doc_name)
        if is_draft_tor_doc_label(doc_name):
            dismiss_modal(page)
            return _handle_subpage_download(
                page,
                clickable,
                include_label=lambda label: is_tor_file(label),
                source_doc_label=doc_name,
                document_context=document_context,
            )
        downloaded = _handle_direct_or_page_download(
            page,
            clickable,
            doc_name,
            document_context=document_context,
        )
        if downloaded is not None:
            if is_final_tor_target:
                return [
                    document
                    for document in downloaded
                    if is_final_tor_doc_label(str(document.get("source_label") or doc_name))
                ]
            return downloaded
        if target_doc == "ประกาศเชิญชวน":
            return _download_documents_from_current_view(
                page,
                include_label=lambda label: (
                    "ประกาศเชิญชวน" in label or is_final_tor_doc_label(label)
                ),
                source_doc_label=doc_name,
                document_context=document_context,
            )
        if is_final_tor_target:
            return _download_documents_from_current_view(
                page,
                include_label=is_final_tor_doc_label,
                source_doc_label=doc_name,
                document_context=document_context,
            )
    return []


def _collect_detail_page_link_documents(
    page,
    *,
    detail_url: str,
    document_context: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    downloaded_documents: list[dict[str, object]] = []
    for label, download_button in _iter_detail_page_fallback_candidates(page):
        downloaded = _handle_direct_or_page_download(
            page,
            download_button,
            label,
            document_context=document_context,
        )
        if downloaded:
            downloaded_documents.extend(downloaded)
        _ensure_project_detail_page(page, detail_url=detail_url)
    return downloaded_documents


def _iter_detail_page_fallback_candidates(page) -> list[tuple[str, object]]:
    candidates: list[tuple[str, object]] = []
    seen_candidate_keys: set[tuple[str, str, str, str]] = set()

    def _append_candidate(label: str, download_button) -> None:
        click_meta = _extract_click_metadata(download_button)
        candidate_key = (
            label.casefold(),
            str(click_meta.get("href") or "").strip(),
            str(click_meta.get("onclick") or "").strip(),
            str(click_meta.get("textContent") or "").strip().casefold(),
        )
        if candidate_key in seen_candidate_keys:
            return
        seen_candidate_keys.add(candidate_key)
        candidates.append((label, download_button))

    try:
        tables = page.query_selector_all("table")
    except Exception:
        tables = []
    for table in tables:
        header_combined = " ".join(
            header.inner_text().strip() for header in table.query_selector_all("th")
        )
        if "ดูข้อมูล" in header_combined or "ดาวน์โหลด" in header_combined:
            continue
        for row in _detail_page_table_rows(table):
            cells = row.query_selector_all("td")
            if len(cells) < 2:
                continue
            cell_texts = [cell.inner_text().strip() for cell in cells]
            if not _is_detail_page_fallback_row(cell_texts):
                continue
            download_button = None
            for cell in reversed(cells):
                download_button = cell.query_selector(
                    "a[href], a[onclick], button:not([disabled]), [role='button']"
                ) or cell.query_selector("a, button, [role='button']")
                if download_button is not None:
                    break
            if download_button is None:
                continue
            _append_candidate(_select_detail_page_fallback_label(cell_texts), download_button)

    try:
        anchors = page.query_selector_all("a[href], a[onclick], a")
    except Exception:
        anchors = []
    for anchor in anchors:
        click_meta = _extract_click_metadata(anchor)
        label = _select_detail_page_anchor_fallback_label(click_meta)
        if not _is_detail_page_fallback_anchor(
            click_meta,
            label=label,
            base_url=_get_page_url(page),
        ):
            continue
        _append_candidate(label, anchor)

    return candidates


def _detail_page_table_rows(table) -> list[object]:
    rows = table.query_selector_all("tbody tr")
    if rows:
        return rows
    return table.query_selector_all("tr")


def _is_detail_page_fallback_row(cell_texts: list[str]) -> bool:
    combined = " ".join(text for text in cell_texts if text).strip().casefold()
    if not combined:
        return False
    if any(term in combined for term in DETAIL_PAGE_LINK_FALLBACK_TERMS):
        return True
    return any(
        re.search(r"\.(?:zip|pdf|docx?|xlsx?)\b", text, flags=re.IGNORECASE) for text in cell_texts
    )


def _select_detail_page_fallback_label(cell_texts: list[str]) -> str:
    for text in reversed(cell_texts):
        cleaned = str(text or "").strip()
        if cleaned:
            return cleaned
    return "document"


def _select_detail_page_anchor_fallback_label(click_meta: dict[str, object] | None) -> str:
    text_content = str((click_meta or {}).get("textContent") or "").strip()
    if text_content:
        return text_content
    resolved_url = resolve_http_url(str((click_meta or {}).get("href") or "").strip())
    if resolved_url:
        file_name = Path(urlparse(resolved_url).path).name.strip()
        if file_name:
            return file_name
    inferred_url = extract_url_from_onclick(str((click_meta or {}).get("onclick") or "").strip())
    if inferred_url:
        file_name = Path(urlparse(inferred_url).path).name.strip()
        if file_name:
            return file_name
    return "document"


def _is_detail_page_fallback_anchor(
    click_meta: dict[str, object] | None,
    *,
    label: str,
    base_url: str,
) -> bool:
    if not click_meta or click_meta.get("insideTable"):
        return False
    if _looks_like_modal_open_action(click_meta):
        return False
    href = resolve_http_url(str(click_meta.get("href") or "").strip(), base_url=base_url)
    onclick_url = extract_url_from_onclick(
        str(click_meta.get("onclick") or "").strip(),
        base_url=base_url,
    )
    combined = " ".join(
        part
        for part in (
            label,
            str(click_meta.get("textContent") or "").strip(),
            href or "",
            onclick_url or "",
        )
        if part
    ).casefold()
    if not combined:
        return False
    if any(term in combined for term in DETAIL_PAGE_LINK_FALLBACK_TERMS):
        return True
    return any(
        re.search(r"\.(?:zip|pdf|docx?|xlsx?)\b", value, flags=re.IGNORECASE)
        for value in (label, href or "", onclick_url or "")
    )


def _handle_direct_or_page_download(
    page,
    btn,
    doc_name: str,
    *,
    document_context: dict[str, object] | None = None,
) -> list[dict[str, object]] | None:
    _trace_document_progress("direct_handler_start", source_label=doc_name)
    dismiss_modal(page)
    _trace_document_progress("direct_handler_dismissed", source_label=doc_name)
    clear_site_error_toast(page)
    _trace_document_progress("direct_handler_toast_cleared", source_label=doc_name)
    url_before = page.url
    pages_before = list(page.context.pages)
    click_meta = _extract_click_metadata(btn)
    _trace_document_progress(
        "direct_handler_metadata",
        source_label=doc_name,
        tag=str((click_meta or {}).get("tag") or ""),
        href=str((click_meta or {}).get("href") or ""),
        data_toggle=str((click_meta or {}).get("dataToggle") or ""),
        text=str((click_meta or {}).get("textContent") or ""),
    )
    clicked_href = (click_meta or {}).get("href")
    clicked_onclick = (click_meta or {}).get("onclick")
    follow_up_timeout_s = _followup_timeout_for_document(
        doc_name,
        click_meta,
        document_context=document_context,
    )
    should_probe_before_expect_download = _should_probe_before_expect_download(
        doc_name,
        click_meta,
        document_context=document_context,
    )
    prefer_followup_capture = _should_prefer_followup_capture(
        doc_name,
        click_meta,
        document_context=document_context,
    )
    if _looks_like_modal_open_action(click_meta):
        try:
            _trace_document_progress("modal_click_start", source_label=doc_name, mode="native")
            try:
                btn.click(timeout=5_000)
            except TypeError:
                btn.click()
        except Exception:
            return None
        _trace_document_progress("modal_click_finished", source_label=doc_name)
        _sleep(1)
        if _skip_known_missing_file_modal(
            page,
            file_label=doc_name,
            click_context="top_level_modal_button",
            source_doc_label=doc_name,
        ):
            return []
        if page.url != url_before:
            _trace_document_progress("content_view_after_modal_click", source_label=doc_name)
            return _save_from_content_page(page, doc_name, document_context=document_context)
        if _page_has_inline_document_view(page, url_before_click=url_before):
            _trace_document_progress("inline_content_after_modal_click", source_label=doc_name)
            return _save_from_content_page(page, doc_name, document_context=document_context)
        new_page = _wait_for_actionable_new_page(
            page,
            pages_before=pages_before,
            timeout_s=NEW_PAGE_ACTIONABLE_TIMEOUT_S,
        )
        if new_page is not None:
            try:
                _trace_document_progress("new_tab_after_modal_click", source_label=doc_name)
                return _save_from_new_tab(
                    new_page,
                    doc_name,
                    fallback_url=clicked_href,
                    document_context=document_context,
                )
            finally:
                try:
                    new_page.close()
                except Exception:
                    pass
        return None

    if should_probe_before_expect_download:
        try:
            immediate_download = _click_and_capture_immediate_download_or_missing_modal(
                page,
                lambda: page.evaluate("(el) => el.click()", btn),
                file_label=doc_name,
                click_context="top_level_document_row",
                source_doc_label=doc_name,
            )
            if immediate_download is not None:
                ext = Path(immediate_download.suggested_filename).suffix or ".pdf"
                return [
                    _download_to_document(
                        immediate_download,
                        source_label=doc_name,
                        file_name=build_safe_filename(doc_name, ext),
                        document_context=document_context,
                    )
                ]
        except KnownMissingFileModal:
            return []
        except Exception:
            pass

        if page.url != url_before:
            _trace_document_progress("content_view_after_immediate_click", source_label=doc_name)
            return _save_from_content_page(page, doc_name, document_context=document_context)

        if _page_has_inline_document_view(page, url_before_click=url_before):
            _trace_document_progress("inline_content_after_immediate_click", source_label=doc_name)
            return _save_from_content_page(page, doc_name, document_context=document_context)

        new_page = _wait_for_actionable_new_page(
            page,
            pages_before=pages_before,
            timeout_s=NEW_PAGE_ACTIONABLE_TIMEOUT_S,
        )
        if new_page is not None:
            try:
                _trace_document_progress("new_tab_after_immediate_click", source_label=doc_name)
                return _save_from_new_tab(
                    new_page,
                    doc_name,
                    fallback_url=clicked_href,
                    document_context=document_context,
                )
            finally:
                try:
                    new_page.close()
                except Exception:
                    pass

        if prefer_followup_capture:
            follow_up_documents = _capture_followup_after_click(
                page,
                file_label=doc_name,
                url_before_click=url_before,
                pages_before_click=len(pages_before),
                source_doc_label=doc_name,
                document_context=document_context,
                timeout_s=follow_up_timeout_s,
            )
            if follow_up_documents is not None:
                _trace_document_progress(
                    "followup_captured",
                    source_label=doc_name,
                    document_count=len(follow_up_documents),
                    timeout_s=follow_up_timeout_s,
                )
                return follow_up_documents

    try:
        direct_download_retries = (
            DOWNLOAD_CLICK_RETRIES if should_probe_before_expect_download else 0
        )

        def _click_and_wait_download():
            with page.expect_download(timeout=DOWNLOAD_EVENT_TIMEOUT) as download_info:
                page.evaluate("(el) => el.click()", btn)
            return download_info.value

        download = run_with_toast_recovery(
            page,
            _click_and_wait_download,
            "Direct download",
            retries=direct_download_retries,
            missing_file_context={
                "file_label": doc_name,
                "source_doc_label": doc_name,
                "click_context": "top_level_document_row",
            },
        )
        ext = Path(download.suggested_filename).suffix or ".pdf"
        _trace_document_progress("direct_download", source_label=doc_name)
        return [
            _download_to_document(
                download,
                source_label=doc_name,
                file_name=build_safe_filename(doc_name, ext),
                document_context=document_context,
            )
        ]
    except KnownMissingFileModal:
        return []
    except PlaywrightTimeout:
        _cancel_pending_downloads(page)
        _trace_document_progress(
            "direct_download_timeout",
            source_label=doc_name,
            timeout_s=DOWNLOAD_EVENT_TIMEOUT,
            retries=direct_download_retries,
        )
        if _skip_known_missing_file_modal(
            page,
            file_label=doc_name,
            click_context="top_level_document_row",
            source_doc_label=doc_name,
        ):
            return []

    _sleep(1)
    if page.url != url_before:
        _trace_document_progress("content_view_after_retry_timeout", source_label=doc_name)
        return _save_from_content_page(page, doc_name, document_context=document_context)

    if _page_has_inline_document_view(page, url_before_click=url_before):
        _trace_document_progress("inline_content_after_retry_timeout", source_label=doc_name)
        return _save_from_content_page(page, doc_name, document_context=document_context)

    new_page = _wait_for_actionable_new_page(
        page,
        pages_before=pages_before,
        timeout_s=NEW_PAGE_ACTIONABLE_TIMEOUT_S,
    )
    if new_page is not None:
        try:
            _trace_document_progress("new_tab_after_retry_timeout", source_label=doc_name)
            return _save_from_new_tab(
                new_page,
                doc_name,
                fallback_url=clicked_href,
                document_context=document_context,
            )
        finally:
            try:
                new_page.close()
            except Exception:
                pass

    inferred = extract_url_from_onclick(clicked_onclick, base_url=page.url)
    if inferred and is_allowed_download_url(inferred):
        new_page = page.context.new_page()
        try:
            new_page.goto(inferred, wait_until="domcontentloaded", timeout=DOWNLOAD_TIMEOUT)
            _trace_document_progress("inferred_viewer_url", source_label=doc_name, url=inferred)
            return _save_from_new_tab(
                new_page,
                doc_name,
                fallback_url=inferred,
                document_context=document_context,
            )
        except Exception:
            return None
        finally:
            try:
                new_page.close()
            except Exception:
                pass
    return None


def _save_from_content_page(
    page,
    doc_name: str,
    *,
    document_context: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    document = None
    try:
        if is_show_htmlfile_url(page.url):
            document = save_show_htmlfile_as_file(
                page,
                doc_name,
                prefer_pdf=True,
                document_context=document_context,
            )
    except Exception:
        document = None

    if document is None:
        try:
            current_url = getattr(page, "url", "") or ""
        except Exception:
            current_url = ""
        if current_url.startswith("blob:"):
            try:
                document = _save_blob_url_from_page(
                    page,
                    doc_name,
                    document_context=document_context,
                )
            except Exception:
                document = None
        if current_url.startswith("blob:") or _infer_document_url_from_page(page) is not None:
            try:
                if document is None:
                    document = _save_via_request(
                        page,
                        doc_name,
                        document_context=document_context,
                    )
            except Exception:
                document = None

    if document is None:
        try:

            def _save_with_ctrl_s():
                with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as download_info:
                    page.keyboard.press("Control+s")
                return download_info.value

            download = run_with_toast_recovery(page, _save_with_ctrl_s, "Content save (Ctrl+S)")
            ext = Path(download.suggested_filename).suffix or ".pdf"
            document = _download_to_document(
                download,
                source_label=doc_name,
                file_name=build_safe_filename(doc_name, ext),
                document_context=document_context,
            )
        except PlaywrightTimeout:
            document = None

    if document is None:
        try:
            document = _save_via_request(
                page,
                doc_name,
                document_context=document_context,
            )
        except Exception:
            document = None

    try:
        page.go_back()
    except Exception:
        try:
            page.go_back(wait_until="domcontentloaded", timeout=DOWNLOAD_TIMEOUT)
        except Exception:
            pass
    _sleep(2)
    return [document] if document is not None else []


def _save_from_new_tab(
    new_page,
    doc_name: str,
    fallback_url: str | None = None,
    *,
    document_context: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    try:
        new_page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    for _ in range(10):
        current_url = ""
        try:
            current_url = new_page.url
        except Exception:
            current_url = ""
        if current_url and not current_url.startswith(("chrome://new-tab-page", "about:blank")):
            break
        _sleep(0.5)

    try:
        if is_show_htmlfile_url(new_page.url):
            document = save_show_htmlfile_as_file(
                new_page,
                doc_name,
                prefer_pdf=True,
                document_context=document_context,
            )
            return [document] if document is not None else []
    except Exception:
        pass

    try:
        current_url = getattr(new_page, "url", "") or ""
    except Exception:
        current_url = ""
    if current_url.startswith("blob:") and _infer_document_url_from_page(new_page) is None:
        try:
            document = _save_blob_url_from_page(
                new_page,
                doc_name,
                document_context=document_context,
            )
            if document is not None:
                return [document]
        except Exception:
            pass

    try:
        document = _save_via_request(
            new_page,
            doc_name,
            fallback_url=fallback_url,
            document_context=document_context,
        )
        if document is not None:
            return [document]
    except Exception:
        pass

    try:

        def _save_from_tab():
            with new_page.expect_download(timeout=DOWNLOAD_TIMEOUT) as download_info:
                new_page.keyboard.press("Control+s")
            return download_info.value

        download = run_with_toast_recovery(new_page, _save_from_tab, "New-tab save")
        ext = Path(download.suggested_filename).suffix or ".pdf"
        return [
            _download_to_document(
                download,
                source_label=doc_name,
                file_name=build_safe_filename(doc_name, ext),
                document_context=document_context,
            )
        ]
    except (PlaywrightTimeout, Exception):
        _cancel_pending_downloads(new_page)
        document = _save_via_request(
            new_page,
            doc_name,
            fallback_url=fallback_url,
            document_context=document_context,
        )
        return [document] if document is not None else []


def _handle_subpage_download(
    page,
    btn,
    include_label,
    *,
    source_doc_label: str = "",
    document_context: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    clear_site_error_toast(page)
    page.evaluate("(el) => el.click()", btn)
    _sleep(1)
    return _download_documents_from_current_view(
        page,
        include_label=include_label,
        source_doc_label=source_doc_label,
        document_context=document_context,
    )


def _download_documents_from_current_view(
    page,
    include_label,
    *,
    source_doc_label: str = "",
    document_context: dict[str, object] | None = None,
    current_modal_signature: tuple[str, ...] | None = None,
) -> list[dict[str, object]]:
    modal = _find_modal_with_downloads(page)
    download_table = None
    if current_modal_signature is None:
        current_modal_signature = _download_modal_signature(modal)
    if modal is None:
        try:
            page.wait_for_selector("table", timeout=15_000)
        except PlaywrightTimeout:
            _click_back_or_exit(page)
            return []
        for table in page.query_selector_all("table"):
            header = " ".join(
                header.inner_text().strip() for header in table.query_selector_all("th")
            )
            if "ดาวน์โหลด" in header:
                download_table = table
                break

    rows = (
        modal.query_selector_all("table tbody tr")
        if modal is not None
        else download_table.query_selector_all("tbody tr")
        if download_table is not None
        else page.query_selector_all("table tbody tr")
    )
    downloaded_documents: list[dict[str, object]] = []
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) < 2:
            continue
        cell_texts = [cell.inner_text().strip() for cell in cells]
        file_label = extract_file_label_from_cell_texts(cell_texts) or "TOR"
        if not include_label(file_label):
            continue
        last_cell = cells[-1]
        download_button = (
            last_cell.query_selector("a[href], a[onclick], button:not([disabled]), [role='button']")
            or last_cell.query_selector("a, button, [role='button']")
            or row.query_selector("a[href], a[onclick], button:not([disabled]), [role='button']")
            or row.query_selector("a, button, [role='button']")
        )
        if download_button is None:
            continue
        url_before_click = page.url
        pages_before_click = len(page.context.pages)
        click_meta = _extract_click_metadata(download_button)
        if _looks_like_modal_open_action(click_meta):
            follow_up_documents = _handle_modal_download_action(
                page,
                download_button,
                file_label=file_label,
                url_before_click=url_before_click,
                pages_before_click=pages_before_click,
                source_doc_label=source_doc_label,
                document_context=document_context,
                current_modal_signature=current_modal_signature,
            )
            if follow_up_documents is not None:
                downloaded_documents.extend(follow_up_documents)
                continue
        try:
            immediate_download = _click_and_capture_immediate_download_or_missing_modal(
                page,
                lambda: page.evaluate("(el) => el.click()", download_button),
                file_label=file_label,
                click_context="nested_file_row",
                source_doc_label=source_doc_label,
            )
            if immediate_download is not None:
                downloaded_documents.append(
                    _download_to_document(
                        immediate_download,
                        source_label=file_label,
                        file_name=immediate_download.suggested_filename,
                        document_context=document_context,
                    )
                )
                continue
        except KnownMissingFileModal:
            continue
        except Exception:
            pass

        if page.url != url_before_click:
            downloaded_documents.extend(
                _save_from_content_page(
                    page,
                    file_label,
                    document_context=document_context,
                )
            )
            continue
        new_page = _wait_for_actionable_new_page(
            page,
            pages_before_count=pages_before_click,
            timeout_s=NEW_PAGE_ACTIONABLE_TIMEOUT_S,
        )
        if new_page is not None:
            try:
                downloaded_documents.extend(
                    _save_from_new_tab(
                        new_page,
                        file_label,
                        document_context=document_context,
                    )
                )
            finally:
                try:
                    new_page.close()
                except Exception:
                    pass
            continue

        try:

            def _click_and_wait_subpage_download():
                with page.expect_download(timeout=DOWNLOAD_EVENT_TIMEOUT) as download_info:
                    page.evaluate("(el) => el.click()", download_button)
                return download_info.value

            download = run_with_toast_recovery(
                page,
                _click_and_wait_subpage_download,
                "Subpage file download",
                retries=DOWNLOAD_CLICK_RETRIES,
                missing_file_context={
                    "file_label": file_label,
                    "source_doc_label": source_doc_label,
                    "click_context": "nested_file_row",
                },
            )
            downloaded_documents.append(
                _download_to_document(
                    download,
                    source_label=file_label,
                    file_name=download.suggested_filename,
                    document_context=document_context,
                )
            )
        except KnownMissingFileModal:
            continue
        except PlaywrightTimeout:
            _cancel_pending_downloads(page)
            if _skip_known_missing_file_modal(
                page,
                file_label=file_label,
                click_context="nested_file_row",
                source_doc_label=source_doc_label,
            ):
                continue
            _sleep(0.5)
            if page.url != url_before_click:
                downloaded_documents.extend(
                    _save_from_content_page(
                        page,
                        file_label,
                        document_context=document_context,
                    )
                )
                continue
            new_page = _wait_for_actionable_new_page(
                page,
                pages_before_count=pages_before_click,
                timeout_s=NEW_PAGE_ACTIONABLE_TIMEOUT_S,
            )
            if new_page is not None:
                try:
                    downloaded_documents.extend(
                        _save_from_new_tab(
                            new_page,
                            file_label,
                            document_context=document_context,
                        )
                    )
                finally:
                    try:
                        new_page.close()
                    except Exception:
                        pass
    _click_back_or_exit(page)
    return downloaded_documents


def _handle_modal_download_action(
    page,
    download_button,
    *,
    file_label: str,
    url_before_click: str,
    pages_before_click: int,
    source_doc_label: str = "",
    document_context: dict[str, object] | None = None,
    current_modal_signature: tuple[str, ...] | None = None,
) -> list[dict[str, object]] | None:
    for click_mode in ("native", "dom", "native"):
        try:
            if click_mode == "native":
                download_button.click()
            else:
                page.evaluate("(el) => el.click()", download_button)
        except Exception:
            continue
        follow_up = _capture_followup_after_click(
            page,
            file_label=file_label,
            url_before_click=url_before_click,
            pages_before_click=pages_before_click,
            source_doc_label=source_doc_label,
            document_context=document_context,
            current_modal_signature=current_modal_signature,
        )
        if follow_up is not None:
            return follow_up
    return None


def _capture_followup_after_click(
    page,
    *,
    file_label: str,
    url_before_click: str,
    pages_before_click: int,
    source_doc_label: str = "",
    document_context: dict[str, object] | None = None,
    timeout_s: float = 8.0,
    current_modal_signature: tuple[str, ...] | None = None,
) -> list[dict[str, object]] | None:
    deadline = time.monotonic() + max(0.2, timeout_s)
    while time.monotonic() < deadline:
        if _skip_known_missing_file_modal(
            page,
            file_label=file_label,
            click_context="nested_modal_followup",
            source_doc_label=source_doc_label,
        ):
            return []
        if _page_has_inline_document_view(page, url_before_click=url_before_click):
            return _save_from_content_page(
                page,
                file_label,
                document_context=document_context,
            )
        if page.url != url_before_click:
            return _save_from_content_page(
                page,
                file_label,
                document_context=document_context,
            )
        new_page = _latest_actionable_new_page(
            page,
            pages_before_count=pages_before_click,
            close_placeholders=False,
        )
        if new_page is not None:
            try:
                return _save_from_new_tab(
                    new_page,
                    file_label,
                    document_context=document_context,
                )
            finally:
                try:
                    new_page.close()
                except Exception:
                    pass
        modal = _find_modal_with_downloads(page)
        if modal is not None:
            followup_modal_signature = _download_modal_signature(modal)
            if followup_modal_signature == current_modal_signature:
                _sleep(NEW_PAGE_ACTIONABLE_POLL_INTERVAL_S)
                continue
            _close_placeholder_new_pages(page, pages_before_count=pages_before_click)
            return _download_documents_from_current_view(
                page,
                include_label=lambda label: True,
                source_doc_label=source_doc_label or file_label,
                document_context=document_context,
                current_modal_signature=followup_modal_signature,
            )
        _sleep(NEW_PAGE_ACTIONABLE_POLL_INTERVAL_S)
    _close_placeholder_new_pages(page, pages_before_count=pages_before_click)
    return None


def _download_modal_signature(modal) -> tuple[str, ...] | None:
    if modal is None:
        return None
    try:
        rows = modal.query_selector_all("table tbody tr")
    except Exception:
        rows = []
    row_signatures: list[str] = []
    for row in rows[:5]:
        try:
            cells = row.query_selector_all("td")
        except Exception:
            cells = []
        parts = [str(cell.inner_text() or "").strip() for cell in cells]
        row_signatures.append(" | ".join(part for part in parts if part))
    return tuple(row_signatures)


def _actionable_new_pages(
    page,
    *,
    pages_before: list[object] | None = None,
    pages_before_count: int | None = None,
    close_placeholders: bool = True,
) -> list[object]:
    try:
        current_pages = list(page.context.pages)
    except Exception:
        return []
    if pages_before is not None:
        new_pages = [
            current_page for current_page in current_pages if current_page not in pages_before
        ]
    elif pages_before_count is not None:
        new_pages = current_pages[max(0, int(pages_before_count)) :]
    else:
        new_pages = current_pages
    actionable_pages: list[object] = []
    for new_page in new_pages:
        page_url = _safe_page_url(new_page)
        if _is_placeholder_browser_page(page_url):
            if close_placeholders:
                try:
                    new_page.close()
                except Exception:
                    pass
            continue
        actionable_pages.append(new_page)
    return actionable_pages


def _latest_actionable_new_page(
    page,
    *,
    pages_before: list[object] | None = None,
    pages_before_count: int | None = None,
    close_placeholders: bool = True,
):
    new_pages = _actionable_new_pages(
        page,
        pages_before=pages_before,
        pages_before_count=pages_before_count,
        close_placeholders=close_placeholders,
    )
    if not new_pages:
        return None
    latest_page = new_pages[-1]
    for surplus_page in new_pages[:-1]:
        try:
            surplus_page.close()
        except Exception:
            pass
    return latest_page


def _wait_for_actionable_new_page(
    page,
    *,
    pages_before: list[object] | None = None,
    pages_before_count: int | None = None,
    timeout_s: float = NEW_PAGE_ACTIONABLE_TIMEOUT_S,
):
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        new_page = _latest_actionable_new_page(
            page,
            pages_before=pages_before,
            pages_before_count=pages_before_count,
            close_placeholders=False,
        )
        if new_page is not None:
            return new_page
        if time.monotonic() >= deadline:
            _close_placeholder_new_pages(
                page,
                pages_before=pages_before,
                pages_before_count=pages_before_count,
            )
            return None
        _sleep(NEW_PAGE_ACTIONABLE_POLL_INTERVAL_S)


def _close_placeholder_new_pages(
    page,
    *,
    pages_before: list[object] | None = None,
    pages_before_count: int | None = None,
) -> None:
    _actionable_new_pages(
        page,
        pages_before=pages_before,
        pages_before_count=pages_before_count,
        close_placeholders=True,
    )


def _safe_page_url(page) -> str:
    try:
        return str(getattr(page, "url", "") or "")
    except Exception:
        return ""


def _is_placeholder_browser_page(url: str | None) -> bool:
    lowered = str(url or "").strip().lower()
    return lowered.startswith(("about:blank", "chrome://new-tab-page"))


def _page_has_inline_document_view(page, *, url_before_click: str) -> bool:
    current_url = _safe_page_url(page)
    if current_url and current_url != url_before_click and is_show_htmlfile_url(current_url):
        return True
    if current_url.startswith("blob:"):
        return True
    inferred_url = _infer_document_url_from_page(page)
    return bool(inferred_url and is_allowed_download_url(inferred_url))


def _is_consulting_document_context(document_context: dict[str, object] | None) -> bool:
    project_state = str((document_context or {}).get("project_state") or "").strip().casefold()
    return project_state == ProjectState.OPEN_CONSULTING.value


def _should_prefer_followup_capture(
    doc_name: str,
    click_meta: dict[str, object] | None,
    *,
    document_context: dict[str, object] | None = None,
) -> bool:
    document_type, _ = classify_document(label=doc_name)
    lowered_name = str(doc_name or "").strip().casefold()
    href = str((click_meta or {}).get("href") or "").strip()
    tag = str((click_meta or {}).get("tag") or "").strip().casefold()
    if "แผนการจัดซื้อ" in lowered_name or "procurement plan" in lowered_name:
        return True
    if document_type is DocumentType.INVITATION and _is_consulting_document_context(
        document_context
    ):
        return True
    return not href and tag == "a" and _is_consulting_document_context(document_context)


def _should_probe_before_expect_download(
    doc_name: str,
    click_meta: dict[str, object] | None,
    *,
    document_context: dict[str, object] | None = None,
) -> bool:
    return _should_prefer_followup_capture(
        doc_name,
        click_meta,
        document_context=document_context,
    )


def _followup_timeout_for_document(
    doc_name: str,
    click_meta: dict[str, object] | None,
    *,
    document_context: dict[str, object] | None = None,
) -> float:
    document_type, _ = classify_document(label=doc_name)
    lowered_name = str(doc_name or "").strip().casefold()
    href = str((click_meta or {}).get("href") or "").strip()
    tag = str((click_meta or {}).get("tag") or "").strip().casefold()
    if document_type is DocumentType.INVITATION and _is_consulting_document_context(
        document_context
    ):
        return 4.0
    if "แผนการจัดซื้อ" in lowered_name or "procurement plan" in lowered_name:
        return 4.0
    if not href and tag == "a" and _is_consulting_document_context(document_context):
        return 4.0
    return 2.0


def _click_and_capture_immediate_download_or_missing_modal(
    page,
    click_action,
    *,
    file_label: str,
    click_context: str,
    source_doc_label: str = "",
    timeout_s: float = IMMEDIATE_MODAL_CHECK_TIMEOUT_S,
):
    downloads = []

    def _record_download(download) -> None:
        downloads.append(download)

    listener_registered = _register_download_listener(page, _record_download)
    try:
        click_action()
        deadline = time.monotonic() + max(0.1, timeout_s)
        while time.monotonic() < deadline:
            if downloads:
                return downloads[-1]
            if _skip_known_missing_file_modal(
                page,
                file_label=file_label,
                click_context=click_context,
                source_doc_label=source_doc_label,
            ):
                raise KnownMissingFileModal from None
            _sleep(0.1)
        if downloads:
            return downloads[-1]
        if _skip_known_missing_file_modal(
            page,
            file_label=file_label,
            click_context=click_context,
            source_doc_label=source_doc_label,
        ):
            raise KnownMissingFileModal from None
        return None
    finally:
        if listener_registered:
            _remove_download_listener(page, _record_download)


def _register_download_listener(page, handler) -> bool:
    try:
        page.on("download", handler)
        return True
    except Exception:
        return False


def _remove_download_listener(page, handler) -> None:
    for method_name in ("remove_listener", "off"):
        try:
            method = getattr(page, method_name)
        except Exception:
            continue
        try:
            method("download", handler)
            return
        except Exception:
            continue


def _find_modal_with_downloads(page):
    try:
        page.wait_for_selector(
            ".modal.show table tbody tr, .modal.fade.show table tbody tr",
            timeout=8_000,
        )
    except PlaywrightTimeout:
        return None
    for modal in page.query_selector_all(".modal.show, .modal.fade.show"):
        try:
            if not modal.is_visible():
                continue
            header = " ".join(
                title.inner_text().strip() for title in modal.query_selector_all("th")
            )
            if "ดาวน์โหลด" in header:
                return modal
        except Exception:
            continue
    return None


def _get_page_url(page) -> str:
    try:
        return str(getattr(page, "url", "") or "")
    except Exception:
        return ""


def _is_project_detail_page(page, *, detail_url: str) -> bool:
    current_url = _get_page_url(page)
    if detail_url:
        return current_url.rstrip("/") == detail_url.rstrip("/")
    return "/procurement/" in current_url


def _ensure_project_detail_page(page, *, detail_url: str) -> None:
    if not detail_url:
        return
    if _is_project_detail_page(page, detail_url=detail_url):
        return
    for _ in range(3):
        _click_back_or_exit(page)
        if _is_project_detail_page(page, detail_url=detail_url):
            return
    try:
        page.goto(detail_url, wait_until="domcontentloaded", timeout=DOWNLOAD_TIMEOUT)
    except Exception:
        return
    _sleep(1)


def dismiss_modal(page) -> None:
    clear_site_error_toast(page)
    page.evaluate(
        """() => {
            document.querySelectorAll('.modal.show, .modal.fade.show').forEach(modal => {
                modal.classList.remove('show');
                modal.style.display = 'none';
                modal.setAttribute('aria-hidden', 'true');
            });
            document.querySelectorAll('.modal-backdrop').forEach(backdrop => backdrop.remove());
            document.body.classList.remove('modal-open');
            document.body.style.removeProperty('overflow');
            document.body.style.removeProperty('padding-right');
        }"""
    )
    _sleep(0.5)


def _compact_modal_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _normalize_modal_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _matches_target_document_label(target_doc: str, label_text: str) -> bool:
    normalized_label = str(label_text or "").strip()
    if not normalized_label:
        return False
    if target_doc == "ร่างเอกสารประกวดราคา":
        return is_draft_tor_doc_label(normalized_label)
    if target_doc == "เอกสารประกวดราคา":
        return is_final_tor_doc_label(normalized_label)
    return target_doc in normalized_label


def _read_element_text(element) -> str:
    try:
        return str(element.inner_text() or "")
    except Exception:
        try:
            return str(element.text_content() or "")
        except Exception:
            return ""


def _find_known_missing_file_modal(page) -> dict[str, object] | None:
    try:
        candidates = page.query_selector_all(SYSTEM_MODAL_SELECTORS)
    except Exception:
        return None
    for modal in candidates:
        try:
            if hasattr(modal, "is_visible") and not modal.is_visible():
                continue
        except Exception:
            continue
        text = _normalize_modal_text(_read_element_text(modal))
        compact_text = _compact_modal_text(text)
        if not any(
            _compact_modal_text(marker) in compact_text for marker in MISSING_FILE_MODAL_MARKERS
        ):
            continue
        code_match = re.search(r"\bE\d{4,}\b", text)
        return {
            "modal": modal,
            "text": text,
            "code": code_match.group(0) if code_match else "",
        }
    return None


def _dismiss_known_system_modal(page, modal) -> None:
    clicked = False
    try:
        button = modal.query_selector(
            ".swal2-confirm, button, [role='button'], input[type='button'], input[type='submit']"
        )
        if button is not None:
            button.click()
            clicked = True
    except Exception:
        clicked = False
    if not clicked:
        try:
            page.keyboard.press("Escape")
            clicked = True
        except Exception:
            clicked = False
    if not clicked:
        try:
            page.evaluate(
                """() => {
                    const visible = (el) => {
                        const style = window.getComputedStyle(el);
                        return style.display !== 'none' && style.visibility !== 'hidden';
                    };
                    const markers = ['E4514', 'ค้นหาไฟล์เอกสารไม่พบ', 'ไม่พบไฟล์ในโครงการนี้'];
                    const dialogs = Array.from(
                        document.querySelectorAll(
                            '.modal.show, .modal.fade.show, .swal2-popup, [role="dialog"]'
                        )
                    ).filter(visible);
                    const dialog = dialogs.find((candidate) => {
                        const text = (candidate.textContent || '').replace(/\\s+/g, '');
                        return markers.some((marker) => text.includes(marker.replace(/\\s+/g, '')));
                    });
                    if (!dialog) return false;
                    const buttons = Array.from(
                        dialog.querySelectorAll(
                            '.swal2-confirm, button, [role="button"], input[type="button"], input[type="submit"]'
                        )
                    ).filter(visible);
                    const preferred = buttons.find((button) => {
                        const text = (button.textContent || button.value || '').trim();
                        return ['ตกลง', 'OK', 'Ok', 'ปิด', 'Close'].some((label) => text.includes(label));
                    }) || buttons[0];
                    if (preferred) {
                        preferred.click();
                        return true;
                    }
                    dialog.classList.remove('show');
                    dialog.style.display = 'none';
                    return true;
                }"""
            )
        except Exception:
            pass
    _sleep(0.3)


def _skip_known_missing_file_modal(
    page,
    *,
    file_label: str,
    click_context: str,
    source_doc_label: str = "",
) -> bool:
    modal_info = _find_known_missing_file_modal(page)
    if modal_info is None:
        return False
    modal_text = str(modal_info.get("text") or "")
    modal_code = str(modal_info.get("code") or "")
    logger.info(
        "e-GP source document is unavailable",
        extra={
            "egp_event": "document_unavailable_on_source",
            "project_detail_url": _get_page_url(page),
            "source_label": file_label,
            "source_doc_label": source_doc_label,
            "inner_file_label": file_label if source_doc_label else "",
            "download_click_context": click_context,
            "modal_code": modal_code,
            "modal_text": modal_text,
            "unavailable_reason": "known_missing_file_modal",
        },
    )
    _dismiss_known_system_modal(page, modal_info.get("modal"))
    return True


def run_with_toast_recovery(
    page,
    action,
    label: str,
    retries: int = TOAST_RECOVERY_RETRIES,
    missing_file_context: dict[str, str] | None = None,
):
    clear_site_error_toast(page)
    for attempt in range(retries + 1):
        try:
            return action()
        except PlaywrightTimeout:
            had_toast = clear_site_error_toast(page)
            _cancel_pending_downloads(page)
            if missing_file_context and _skip_known_missing_file_modal(
                page,
                file_label=str(missing_file_context.get("file_label") or label),
                click_context=str(missing_file_context.get("click_context") or label),
                source_doc_label=str(missing_file_context.get("source_doc_label") or ""),
            ):
                raise KnownMissingFileModal from None
            if attempt < retries:
                if had_toast:
                    _sleep(0.8)
                continue
            raise


def _cancel_pending_downloads(page) -> None:
    try:
        page.evaluate(
            """() => {
                window.stop();
            }"""
        )
    except Exception:
        pass


def _click_local_modal_exit(page) -> bool:
    try:
        clicked = page.evaluate(
            """() => {
                const labels = ['ออก', 'กลับ', 'ปิด', 'Close'];
                const normalize = (value) => String(value || '').trim();
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && style.opacity !== '0'
                        && (el.offsetParent !== null || style.position === 'fixed');
                };
                const closestDialogs = Array.from(
                    document.querySelectorAll(
                        '.modal.show, .modal.fade.show, .swal2-popup, [role="dialog"]'
                    )
                ).filter(isVisible);
                for (let index = closestDialogs.length - 1; index >= 0; index -= 1) {
                    const dialog = closestDialogs[index];
                    const candidates = Array.from(
                        dialog.querySelectorAll(
                            '[data-dismiss="modal"], .btn-close, .close, button, [role="button"], input[type="button"], input[type="submit"]'
                        )
                    ).filter(isVisible);
                    const preferred = candidates.find((button) => {
                        const text = normalize(button.textContent || button.value || '');
                        const aria = normalize(
                            (button.getAttribute && (
                                button.getAttribute('aria-label') ||
                                button.getAttribute('title')
                            )) || ''
                        );
                        if (text && labels.some((label) => text.includes(label))) {
                            return true;
                        }
                        return ['close', 'dismiss', 'ปิด'].some((label) =>
                            aria.toLowerCase().includes(label)
                        );
                    });
                    if (preferred) {
                        preferred.click();
                        return true;
                    }
                }
                return false;
            }"""
        )
    except Exception:
        return False
    if clicked:
        _sleep(1)
    return bool(clicked)


def _click_back_or_exit(page) -> None:
    for _ in range(3):
        clear_site_error_toast(page)
        if _click_local_modal_exit(page):
            return
        dismiss_modal(page)
        clear_site_error_toast(page)
        _sleep(0.5)
        clicked = page.evaluate(
            """() => {
                const labels = ['ออก', 'กลับ', 'ปิด', 'Close'];
                for (const label of labels) {
                    const buttons = document.querySelectorAll('button');
                    for (const button of buttons) {
                        if (button.textContent.trim().includes(label) && button.offsetParent !== null) {
                            button.click();
                            return true;
                        }
                    }
                }
                return false;
            }"""
        )
        if clicked:
            _sleep(1)
            return
    page.keyboard.press("Escape")
    _sleep(1)


def _extract_click_metadata(btn) -> dict[str, object]:
    try:
        return btn.evaluate(
            """(el) => {
                if (!el) {
                    return {
                        href: null,
                        onclick: null,
                        tag: null,
                        dataToggle: null,
                        className: null,
                        textContent: null,
                        insideTable: null,
                    };
                }
                const a = el.closest && el.closest('a[href]') ? el.closest('a[href]') : null;
                const href = (a && a.href) || el.href || el.getAttribute('href') || null;
                const onclick = el.getAttribute ? el.getAttribute('onclick') : null;
                const tag = el.tagName ? String(el.tagName).toLowerCase() : null;
                const dataToggle = el.getAttribute ? el.getAttribute('data-toggle') : null;
                const className = el.className ? String(el.className) : null;
                const textContent = el.textContent ? String(el.textContent).trim() : null;
                const insideTable = Boolean(el.closest && el.closest('table'));
                return { href, onclick, tag, dataToggle, className, textContent, insideTable };
            }"""
        )
    except Exception:
        return {
            "href": None,
            "onclick": None,
            "tag": None,
            "dataToggle": None,
            "className": None,
            "textContent": None,
            "insideTable": None,
        }


def _looks_like_modal_open_action(click_meta: dict[str, object] | None) -> bool:
    if not click_meta:
        return False
    data_toggle = str(click_meta.get("dataToggle") or "").strip().casefold()
    onclick = str(click_meta.get("onclick") or "").strip().casefold()
    class_name = str(click_meta.get("className") or "").strip().casefold()
    text_content = str(click_meta.get("textContent") or "").strip().casefold()
    href = str(click_meta.get("href") or "").strip()
    if data_toggle == "modal":
        return True
    if "modal" in onclick or "modal" in class_name:
        return True
    if not href and text_content == "description":
        return True
    return False


def _download_to_document(
    download,
    *,
    source_label: str,
    file_name: str | None = None,
    document_context: dict[str, object] | None = None,
) -> dict[str, object]:
    resolved_file_name = str(file_name or download.suggested_filename)
    file_bytes = _read_download_bytes(download, resolved_file_name)
    return _apply_document_context(
        {
            "file_name": resolved_file_name,
            "file_bytes": file_bytes,
            "source_label": source_label,
            "source_status_text": "",
            "source_page_text": "",
        },
        document_context,
    )


def _read_download_bytes(download, file_name: str) -> bytes:
    path = download.path()
    if path:
        try:
            return Path(path).read_bytes()
        except FileNotFoundError:
            pass
    if not hasattr(download, "save_as"):
        return b""
    suffix = Path(file_name).suffix or ".download"
    with tempfile.TemporaryDirectory(prefix="egp-download-") as tmp_dir:
        saved_path = Path(tmp_dir) / f"download{suffix}"
        download.save_as(str(saved_path))
        return saved_path.read_bytes()


def _build_document_context(
    *,
    source_status_text: str = "",
    source_page_text: str = "",
    project_state: str | None = None,
) -> dict[str, object]:
    return {
        "source_status_text": source_status_text,
        "source_page_text": source_page_text,
        "project_state": project_state,
    }


def _apply_document_context(
    document: dict[str, object],
    document_context: dict[str, object] | None,
) -> dict[str, object]:
    if not document_context:
        return document
    resolved = dict(document)
    if not resolved.get("source_status_text"):
        resolved["source_status_text"] = str(document_context.get("source_status_text") or "")
    if not resolved.get("source_page_text"):
        resolved["source_page_text"] = str(document_context.get("source_page_text") or "")
    if resolved.get("project_state") is None and document_context.get("project_state") is not None:
        resolved["project_state"] = str(document_context["project_state"])
    return resolved


def _save_via_request(
    page,
    doc_name: str,
    fallback_url: str | None = None,
    *,
    document_context: dict[str, object] | None = None,
) -> dict[str, object] | None:
    url = _infer_document_url_from_page(page) or resolve_http_url(
        fallback_url, base_url=getattr(page, "url", None)
    )
    if not url or not is_allowed_download_url(url):
        return None
    response = page.request.get(url, timeout=SUBPAGE_DOWNLOAD_TIMEOUT)
    if not response.ok:
        return None
    data = response.body()
    content_type = response.headers.get("content-type") if hasattr(response, "headers") else None
    if looks_like_html_bytes(data) or (content_type and "text/html" in content_type.lower()):
        return None
    guessed = filename_from_content_disposition(
        response.headers.get("content-disposition") if hasattr(response, "headers") else None
    )
    sniffed_ext = sniff_extension_from_bytes(data)
    ext = (
        sniffed_ext
        or guess_extension_from_content_type(content_type)
        or (Path(urlparse(url).path).suffix or None)
    )
    if guessed:
        filename = sanitize_filename_preserve_suffix(guessed, max_len=100)
        if sniffed_ext and not filename.lower().endswith(sniffed_ext):
            filename = build_safe_filename(Path(filename).stem, sniffed_ext, max_len=100)
    else:
        filename = build_safe_filename(doc_name, ext, max_len=100)
    return _apply_document_context(
        {
            "file_name": filename,
            "file_bytes": data,
            "source_label": doc_name,
            "source_status_text": "",
            "source_page_text": "",
        },
        document_context,
    )


def _save_blob_url_from_page(
    page,
    doc_name: str,
    *,
    document_context: dict[str, object] | None = None,
) -> dict[str, object] | None:
    current_url = str(getattr(page, "url", "") or "")
    if not current_url.startswith("blob:"):
        return None
    payload = page.evaluate(
        """async () => {
            try {
                const response = await fetch(window.location.href);
                const blob = await response.blob();
                const buffer = await blob.arrayBuffer();
                const bytes = new Uint8Array(buffer);
                const chunkSize = 0x8000;
                let binary = '';
                for (let index = 0; index < bytes.length; index += chunkSize) {
                    binary += String.fromCharCode(...bytes.slice(index, index + chunkSize));
                }
                return {
                    base64: btoa(binary),
                    mimeType: blob.type || null,
                };
            } catch (error) {
                return null;
            }
        }"""
    )
    if not payload or not payload.get("base64"):
        return None
    data = base64.b64decode(str(payload["base64"]))
    mime_type = str(payload.get("mimeType") or "").strip() or None
    ext = sniff_extension_from_bytes(data) or guess_extension_from_content_type(mime_type)
    filename = build_safe_filename(doc_name, ext, max_len=100)
    return _apply_document_context(
        {
            "file_name": filename,
            "file_bytes": data,
            "source_label": doc_name,
            "source_status_text": "",
            "source_page_text": "",
        },
        document_context,
    )


def _infer_document_url_from_page(page) -> str | None:
    try:
        viewer_url = page.url
    except Exception:
        viewer_url = ""
    candidate = extract_document_url_from_viewer_url(viewer_url)
    if candidate:
        return candidate
    if viewer_url.startswith(("http://", "https://")):
        lowered = viewer_url.lower()
        if any(marker in lowered for marker in (".pdf", ".zip", "download", "dl=")):
            return viewer_url
    try:
        src = page.evaluate(
            """() => {
                const el = document.querySelector('embed[src], iframe[src], object[data]');
                if (!el) return null;
                return el.getAttribute('src') || el.getAttribute('data');
            }"""
        )
        if src:
            extracted = extract_document_url_from_viewer_url(str(src))
            resolved = extracted or str(src)
            if resolved.startswith(("http://", "https://")):
                return resolved
    except Exception:
        pass
    try:
        urls = page.evaluate(
            """() => {
                const out = [];
                const add = (value) => {
                    if (!value) return;
                    try {
                        out.push(new URL(value, window.location.href).toString());
                    } catch (error) {}
                };
                document.querySelectorAll('a[href]').forEach((anchor) => {
                    add(anchor.getAttribute('href'));
                });
                document.querySelectorAll('embed[src], iframe[src], object[data]').forEach((el) => {
                    add(el.getAttribute('src') || el.getAttribute('data'));
                });
                return out.slice(0, 200);
            }"""
        )
        try:
            base_url = page.url
        except Exception:
            base_url = None
        for raw_url in urls or []:
            extracted = extract_document_url_from_viewer_url(str(raw_url))
            resolved = extracted or resolve_http_url(str(raw_url), base_url=base_url)
            if not resolved or not is_allowed_download_url(resolved):
                continue
            lowered = resolved.lower()
            if any(marker in lowered for marker in (".pdf", ".zip", "download", "file=", "dl=")):
                return resolved
    except Exception:
        pass
    return None


def is_tor_file(filename: str) -> bool:
    lowered = filename.lower()
    if lowered.startswith("pricebuild"):
        return False
    return re.match(r"^pb\d+\.pdf$", lowered) is None


def is_tor_doc_label(label: str) -> bool:
    document_type, _ = classify_document(label=label)
    return document_type is DocumentType.TOR


def is_draft_tor_doc_label(label: str) -> bool:
    document_type, document_phase = classify_document(label=label)
    return document_type is DocumentType.TOR and document_phase is DocumentPhase.PUBLIC_HEARING


def is_final_tor_doc_label(label: str) -> bool:
    document_type, document_phase = classify_document(label=label)
    return document_type is DocumentType.TOR and document_phase is DocumentPhase.FINAL


def extract_file_label_from_cell_texts(texts: list[str]) -> str:
    cleaned = [str(text or "").strip() for text in texts or []]
    cleaned = [text for text in cleaned if text]
    if not cleaned:
        return ""
    for text in cleaned:
        if re.search(r"\.(?:zip|pdf|docx?|xlsx?)\b", text, flags=re.IGNORECASE):
            return text
    if len(cleaned) >= 2 and cleaned[0].isdigit():
        return cleaned[1]
    return cleaned[0]


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = cleaned.replace("\n", " ").replace("\r", " ").strip()
    return re.sub(r"\s+", " ", cleaned)


def sanitize_filename_preserve_suffix(name: str, max_len: int = 100) -> str:
    cleaned = sanitize_filename(name)
    if len(cleaned) <= max_len:
        return cleaned
    suffixes = Path(cleaned).suffixes
    ext = "".join(suffixes)
    stem = cleaned[: -len(ext)] if ext and cleaned.endswith(ext) else cleaned
    if not ext:
        return cleaned[:max_len]
    max_stem_len = max_len - len(ext)
    if max_stem_len < 1:
        return ext[-max_len:]
    stem = stem.strip()[:max_stem_len].rstrip() or "file"[:max_stem_len]
    return f"{stem}{ext}"


def build_safe_filename(stem: str, ext: str | None, max_len: int = 100) -> str:
    safe_stem = sanitize_filename(stem) or "file"
    safe_ext = (ext or "").strip()
    if safe_ext and not safe_ext.startswith("."):
        safe_ext = f".{safe_ext}"
    if not safe_ext:
        return safe_stem[:max_len]
    max_stem_len = max_len - len(safe_ext)
    if max_stem_len < 1:
        return safe_ext[-max_len:]
    return f"{safe_stem[:max_stem_len]}{safe_ext}"


def extract_document_url_from_viewer_url(url: str) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        candidates = (qs.get("file") or []) + (qs.get("url") or [])
        for raw in candidates:
            decoded = unquote(raw)
            if decoded.startswith(("http://", "https://")):
                return decoded
        for values in qs.values():
            for raw in values:
                decoded = unquote(raw)
                if decoded.startswith(("http://", "https://")):
                    return decoded
    except Exception:
        return None
    return None


def filename_from_content_disposition(header_value: str | None) -> str | None:
    if not header_value:
        return None
    header = header_value.strip()
    match = re.search(r"""filename\*\s*=\s*([^']*)''([^;]+)""", header, flags=re.IGNORECASE)
    if match:
        raw = match.group(2).strip().strip('"')
        try:
            return unquote(raw)
        except Exception:
            return raw
    match = re.search(r"""filename\s*=\s*\"?([^\";]+)\"?""", header, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def guess_extension_from_content_type(content_type: str | None) -> str | None:
    lowered = (content_type or "").lower()
    if "application/pdf" in lowered:
        return ".pdf"
    if "application/zip" in lowered or "application/x-zip-compressed" in lowered:
        return ".zip"
    return None


def sniff_extension_from_bytes(data: bytes) -> str | None:
    stripped = data.lstrip()
    if stripped.startswith(b"%PDF-"):
        return ".pdf"
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return ".zip"
    return None


def looks_like_html_bytes(data: bytes) -> bool:
    prefix = data.lstrip()[:2048].lower()
    return (
        prefix.startswith(b"<!doctype html")
        or prefix.startswith(b"<html")
        or b"<html" in prefix
        or b"<head" in prefix
        or b"<title" in prefix
    )


def is_allowed_download_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host) or host == "localhost":
        return False
    return any(
        host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_DOWNLOAD_HOST_SUFFIXES
    )


def resolve_http_url(candidate: str | None, base_url: str | None = None) -> str | None:
    if not candidate:
        return None
    raw = candidate.strip()
    if not raw:
        return None
    extracted = extract_document_url_from_viewer_url(raw)
    if extracted:
        raw = extracted
    if raw.startswith(("http://", "https://")):
        return raw
    if base_url and not raw.lower().startswith(
        ("javascript:", "data:", "blob:", "chrome:", "about:")
    ):
        try:
            resolved = urljoin(base_url, raw)
        except Exception:
            resolved = None
        if resolved and resolved.startswith(("http://", "https://")):
            return resolved
    return None


def is_show_htmlfile_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return "showhtmlfile" in url.lower()
    if "showhtmlfile" in (parsed.path or "").lower():
        return True
    qs = parse_qs(parsed.query)
    proc_id = (qs.get("proc_id") or qs.get("procId") or qs.get("procID") or [""])[0]
    return str(proc_id).lower() == "showhtmlfile"


def extract_url_from_onclick(onclick: str | None, base_url: str | None = None) -> str | None:
    if not onclick:
        return None
    text = str(onclick)
    match = re.search(r"""https?://[^\s'")\\]+""", text, flags=re.IGNORECASE)
    if match:
        return resolve_http_url(match.group(0), base_url=base_url)
    match = re.search(r"""['"](/[^'"]+)['"]""", text)
    if match:
        return resolve_http_url(match.group(1), base_url=base_url)
    match = re.search(
        r"""['"]([^'"]*(?:procsearch\.sch|ShowHTMLFile)[^'"]*)['"]""",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return resolve_http_url(match.group(1), base_url=base_url)
    return None


def save_show_htmlfile_as_file(
    page,
    doc_name: str,
    prefer_pdf: bool = True,
    document_context: dict[str, object] | None = None,
) -> dict[str, object] | None:
    try:
        url = page.url
    except Exception:
        url = ""
    if not is_show_htmlfile_url(url):
        return None
    if prefer_pdf:
        try:
            cdp = page.context.new_cdp_session(page)
            try:
                cdp.send("Page.enable")
            except Exception:
                pass
            result = cdp.send(
                "Page.printToPDF",
                {"printBackground": True, "preferCSSPageSize": True},
            )
            data_b64 = (result or {}).get("data")
            if data_b64:
                return _apply_document_context(
                    {
                        "file_name": build_safe_filename(doc_name, ".pdf"),
                        "file_bytes": base64.b64decode(data_b64),
                        "source_label": doc_name,
                        "source_status_text": "",
                        "source_page_text": "",
                    },
                    document_context,
                )
        except Exception:
            pass
    try:
        html = page.content()
    except Exception:
        return None
    document = {
        "file_name": build_safe_filename(doc_name, ".html"),
        "file_bytes": html.encode("utf-8"),
        "source_label": doc_name,
        "source_status_text": "",
        "source_page_text": "",
    }
    return _apply_document_context(document, document_context)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)
