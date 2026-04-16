"""Browser-driven document download extraction for worker workflows."""

from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from egp_db.google_drive import GoogleDriveOAuthConfig
from egp_db.onedrive import OneDriveOAuthConfig

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
except (
    ModuleNotFoundError
):  # pragma: no cover - exercised in CI import environments without Playwright

    class PlaywrightTimeout(Exception):
        pass


from .workflows.document_ingest import ingest_document_artifact

DOCS_TO_DOWNLOAD = [
    "ประกาศเชิญชวน",
    "ประกาศราคากลาง",
    "ร่างเอกสารประกวดราคา",
    "เอกสารประกวดราคา",
]
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


def collect_downloaded_documents(page) -> list[dict[str, object]]:
    downloaded_documents: list[dict[str, object]] = []
    seen_files: set[tuple[str, str]] = set()
    dismiss_modal(page)
    for target_doc in DOCS_TO_DOWNLOAD:
        for document in _download_one_document(page, target_doc):
            dedupe_key = (
                str(document.get("source_label") or ""),
                str(document.get("file_name") or "").casefold(),
            )
            if dedupe_key in seen_files:
                continue
            seen_files.add(dedupe_key)
            downloaded_documents.append(document)
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


def _download_one_document(page, target_doc: str) -> list[dict[str, object]]:
    dismiss_modal(page)
    _sleep(0.5)
    is_draft_tor_target = target_doc == "ร่างเอกสารประกวดราคา"
    is_final_tor_target = target_doc == "เอกสารประกวดราคา"
    downloadable_rows = []
    for table in page.query_selector_all("table"):
        header_combined = " ".join(
            header.inner_text().strip() for header in table.query_selector_all("th")
        )
        if "ดูข้อมูล" not in header_combined and "ดาวน์โหลด" not in header_combined:
            continue
        downloadable_rows.extend(table.query_selector_all("tbody tr"))

    for row in downloadable_rows:
        cells = row.query_selector_all("td")
        if len(cells) < 3:
            continue
        doc_name = ""
        for cell in cells:
            text = cell.inner_text().strip()
            if target_doc in text:
                doc_name = text
                break
            if is_draft_tor_target and is_draft_tor_doc_label(text):
                doc_name = text
                break
            if is_final_tor_target and is_final_tor_doc_label(text):
                doc_name = text
                break
        if not doc_name:
            continue
        last_cell = cells[-1]
        clickable = (
            last_cell.query_selector("a[href], a[onclick], button:not([disabled]), [role='button']")
            or last_cell.query_selector("a, button, [role='button']")
            or last_cell
        )
        if is_draft_tor_doc_label(doc_name):
            dismiss_modal(page)
            return _handle_subpage_download(
                page, clickable, include_label=lambda label: is_tor_file(label)
            )
        downloaded = _handle_direct_or_page_download(page, clickable, doc_name)
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
            )
        if is_final_tor_target:
            return _download_documents_from_current_view(
                page,
                include_label=is_final_tor_doc_label,
            )
    return []


def _handle_direct_or_page_download(page, btn, doc_name: str) -> list[dict[str, object]] | None:
    dismiss_modal(page)
    clear_site_error_toast(page)
    url_before = page.url
    pages_before = list(page.context.pages)
    click_meta = _extract_click_metadata(btn)
    clicked_href = (click_meta or {}).get("href")
    clicked_onclick = (click_meta or {}).get("onclick")

    try:

        def _click_and_wait_download():
            with page.expect_download(timeout=DOWNLOAD_EVENT_TIMEOUT) as download_info:
                page.evaluate("(el) => el.click()", btn)
            return download_info.value

        download = run_with_toast_recovery(
            page,
            _click_and_wait_download,
            "Direct download",
            retries=DOWNLOAD_CLICK_RETRIES,
        )
        ext = Path(download.suggested_filename).suffix or ".pdf"
        return [
            _download_to_document(
                download,
                source_label=doc_name,
                file_name=build_safe_filename(doc_name, ext),
            )
        ]
    except PlaywrightTimeout:
        _cancel_pending_downloads(page)

    _sleep(1)
    if page.url != url_before:
        return _save_from_content_page(page, doc_name)

    new_pages = [
        current_page for current_page in page.context.pages if current_page not in pages_before
    ]
    if new_pages:
        new_page = new_pages[-1]
        try:
            return _save_from_new_tab(new_page, doc_name, fallback_url=clicked_href)
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
            return _save_from_new_tab(new_page, doc_name, fallback_url=inferred)
        except Exception:
            return None
        finally:
            try:
                new_page.close()
            except Exception:
                pass
    return None


def _save_from_content_page(page, doc_name: str) -> list[dict[str, object]]:
    document = None
    try:
        if is_show_htmlfile_url(page.url):
            document = save_show_htmlfile_as_file(page, doc_name, prefer_pdf=True)
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
            )
        except PlaywrightTimeout:
            document = None

    if document is None:
        try:
            document = _save_via_request(page, doc_name)
        except Exception:
            document = None

    page.go_back()
    _sleep(2)
    return [document] if document is not None else []


def _save_from_new_tab(
    new_page, doc_name: str, fallback_url: str | None = None
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
            document = save_show_htmlfile_as_file(new_page, doc_name, prefer_pdf=True)
            return [document] if document is not None else []
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
            )
        ]
    except (PlaywrightTimeout, Exception):
        _cancel_pending_downloads(new_page)
        document = _save_via_request(new_page, doc_name, fallback_url=fallback_url)
        return [document] if document is not None else []


def _handle_subpage_download(page, btn, include_label) -> list[dict[str, object]]:
    clear_site_error_toast(page)
    page.evaluate("(el) => el.click()", btn)
    _sleep(1)
    return _download_documents_from_current_view(page, include_label=include_label)


def _download_documents_from_current_view(page, include_label) -> list[dict[str, object]]:
    modal = _find_modal_with_downloads(page)
    download_table = None
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
            )
            downloaded_documents.append(
                _download_to_document(
                    download, source_label=file_label, file_name=download.suggested_filename
                )
            )
        except PlaywrightTimeout:
            _cancel_pending_downloads(page)
            _sleep(0.5)
            if page.url != url_before_click:
                downloaded_documents.extend(_save_from_content_page(page, file_label))
                continue
            if len(page.context.pages) > pages_before_click:
                new_page = page.context.pages[-1]
                try:
                    downloaded_documents.extend(_save_from_new_tab(new_page, file_label))
                finally:
                    try:
                        new_page.close()
                    except Exception:
                        pass
    _click_back_or_exit(page)
    return downloaded_documents


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


def clear_site_error_toast(page) -> bool:
    try:
        closed = page.evaluate(
            r"""() => {
                const compact = (value) => (value || '').replace(/\s+/g, '');
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && style.opacity !== '0'
                        && (el.offsetParent !== null || style.position === 'fixed');
                };
                const matchesToast = (el) => {
                    const text = compact(el.textContent || '');
                    return text.includes('ระบบเกิดข้อผิดพลาด') && text.includes('กรุณาตรวจสอบ');
                };
                const candidates = Array.from(
                    document.querySelectorAll('[role="alert"], .toast, .alert, .toast-error, .swal2-popup')
                ).filter(isVisible);
                const toast = candidates.find(matchesToast);
                if (!toast) return false;
                const closeSelectors = ['.toast-close-button', '.close', '[aria-label*="close" i]', '[aria-label*="ปิด"]', 'button'];
                for (const selector of closeSelectors) {
                    const button = toast.querySelector(selector);
                    if (button && isVisible(button)) {
                        button.click();
                        return true;
                    }
                }
                return false;
            }"""
        )
        if closed:
            _sleep(0.3)
            page.keyboard.press("Escape")
            _sleep(0.2)
        return bool(closed)
    except Exception:
        return False


def run_with_toast_recovery(page, action, label: str, retries: int = TOAST_RECOVERY_RETRIES):
    clear_site_error_toast(page)
    for attempt in range(retries + 1):
        try:
            return action()
        except PlaywrightTimeout:
            had_toast = clear_site_error_toast(page)
            _cancel_pending_downloads(page)
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


def _click_back_or_exit(page) -> None:
    for _ in range(3):
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
                if (!el) return { href: null, onclick: null, tag: null };
                const a = el.closest && el.closest('a[href]') ? el.closest('a[href]') : null;
                const href = (a && a.href) || el.href || el.getAttribute('href') || null;
                const onclick = el.getAttribute ? el.getAttribute('onclick') : null;
                const tag = el.tagName ? String(el.tagName).toLowerCase() : null;
                return { href, onclick, tag };
            }"""
        )
    except Exception:
        return {"href": None, "onclick": None, "tag": None}


def _download_to_document(
    download, *, source_label: str, file_name: str | None = None
) -> dict[str, object]:
    path = download.path()
    file_bytes = Path(path).read_bytes() if path else b""
    return {
        "file_name": str(file_name or download.suggested_filename),
        "file_bytes": file_bytes,
        "source_label": source_label,
        "source_status_text": "",
        "source_page_text": "",
    }


def _save_via_request(
    page, doc_name: str, fallback_url: str | None = None
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
    return {
        "file_name": filename,
        "file_bytes": data,
        "source_label": doc_name,
        "source_status_text": "",
        "source_page_text": "",
    }


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
    return None


def is_tor_file(filename: str) -> bool:
    lowered = filename.lower()
    if lowered.startswith("pricebuild"):
        return False
    return re.match(r"^pb\d+\.pdf$", lowered) is None


def is_tor_doc_label(label: str) -> bool:
    lowered = label.strip().lower()
    return any(term in lowered for term in TOR_DOC_MATCH_TERMS)


def is_draft_tor_doc_label(label: str) -> bool:
    lowered = label.strip().lower()
    return any(term in lowered for term in DRAFT_TOR_DOC_MATCH_TERMS)


def is_final_tor_doc_label(label: str) -> bool:
    return is_tor_doc_label(label) and not is_draft_tor_doc_label(label)


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
    page, doc_name: str, prefer_pdf: bool = True
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
                return {
                    "file_name": build_safe_filename(doc_name, ".pdf"),
                    "file_bytes": base64.b64decode(data_b64),
                    "source_label": doc_name,
                    "source_status_text": "",
                    "source_page_text": "",
                }
        except Exception:
            pass
    try:
        html = page.content()
    except Exception:
        return None
    return {
        "file_name": build_safe_filename(doc_name, ".html"),
        "file_bytes": html.encode("utf-8"),
        "source_label": doc_name,
        "source_status_text": "",
        "source_page_text": "",
    }


def _sleep(seconds: float) -> None:
    time.sleep(seconds)
