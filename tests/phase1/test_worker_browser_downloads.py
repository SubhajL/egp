from __future__ import annotations

import logging
from pathlib import Path

from egp_worker.browser_downloads import (
    DOCS_TO_DOWNLOAD,
    PlaywrightTimeout,
    SUBPAGE_DOWNLOAD_TIMEOUT,
    collect_downloaded_documents,
    _click_back_or_exit,
    _capture_followup_after_click,
    _download_one_document,
    _download_to_document,
    _handle_direct_or_page_download,
    _download_documents_from_current_view,
    _infer_document_url_from_page,
    _save_from_content_page,
    _save_from_new_tab,
    is_final_tor_doc_label,
    is_tor_file,
)


class FakeTextElement:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text


class FakeCell:
    def __init__(self, text: str = "", clickable=None) -> None:
        self._text = text
        self._clickable = clickable

    def inner_text(self) -> str:
        return self._text

    def query_selector(self, selector: str):
        if self._clickable and any(
            key in selector
            for key in ("a", "button", "[role='button']", '[role="button"]')
        ):
            return self._clickable
        return None


class FakeRow:
    def __init__(self, cells) -> None:
        self._cells = cells

    def query_selector_all(self, selector: str):
        if selector == "td":
            return self._cells
        return []


class FakeTable:
    def __init__(
        self, headers: list[str], rows: list[FakeRow], *, has_tbody: bool = True
    ) -> None:
        self._headers = headers
        self._rows = rows
        self._has_tbody = has_tbody

    def query_selector_all(self, selector: str):
        if selector == "th":
            return [FakeTextElement(text) for text in self._headers]
        if selector == "tbody tr":
            return self._rows if self._has_tbody else []
        if selector == "tr":
            return self._rows
        return []


class FakePage:
    def __init__(self, tables: list[FakeTable], *, standalone_clickables=None) -> None:
        self._tables = tables
        self._standalone_clickables = list(standalone_clickables or [])
        self._modal = None
        self.url = "https://process5.gprocurement.go.th/example"
        self.context = type("Context", (), {"pages": []})()
        self.evaluate_calls: list[tuple[str, object | None]] = []

    def query_selector_all(self, selector: str):
        if selector == ".modal.show, .modal.fade.show, .swal2-popup, [role='dialog']":
            return [self._modal] if self._modal is not None else []
        if selector == "table":
            return self._tables
        if selector in {
            "a[href], a[onclick]",
            "a[href], a[onclick], a",
            "a[href], a[onclick], button[onclick]",
        }:
            return self._standalone_clickables
        return []

    def evaluate(self, script: str, arg=None):
        self.evaluate_calls.append((script, arg))
        if arg is not None and hasattr(arg, "click"):
            arg.click()
        return None


class FakeNoDownloadWaitPage(FakePage):
    def expect_download(self, timeout=None):
        raise AssertionError(
            "should not enter expect_download for immediate E4514 modal"
        )


class FakeResponse:
    def __init__(
        self, body: bytes, *, headers: dict[str, str] | None = None, ok: bool = True
    ):
        self._body = body
        self.headers = headers or {}
        self.ok = ok
        self.status = 200 if ok else 500

    def body(self):
        return self._body


class FakeRequestClient:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, timeout=None):
        self.calls.append({"url": url, "timeout": timeout})
        return self._response


class FakeDownloadWithExpiredPath:
    suggested_filename = "tor.zip"

    def __init__(self, expired_path: Path) -> None:
        self.expired_path = expired_path
        self.saved_paths: list[Path] = []

    def path(self) -> str:
        return str(self.expired_path)

    def save_as(self, target_path: str) -> None:
        saved_path = Path(target_path)
        saved_path.write_bytes(b"zip-bytes")
        self.saved_paths.append(saved_path)


class FakeKeyboard:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def press(self, key: str) -> None:
        self.keys.append(key)


class FakeViewerPage:
    def __init__(self, *, url: str, embedded_src: str, response: FakeResponse) -> None:
        self.url = url
        self._embedded_src = embedded_src
        self.request = FakeRequestClient(response)
        self.keyboard = FakeKeyboard()

    def wait_for_load_state(self, state: str, timeout=None) -> None:
        return None

    def evaluate(self, script: str):
        if (
            "embed[src]" in script
            or "iframe[src]" in script
            or "object[data]" in script
        ):
            return self._embedded_src
        return None


class FakeBlobOnlyViewerPage(FakeViewerPage):
    def __init__(self, *, url: str, response: FakeResponse, mime_type: str) -> None:
        super().__init__(url=url, embedded_src="", response=response)
        self._mime_type = mime_type

    def evaluate(self, script: str):
        if (
            "embed[src]" in script
            or "iframe[src]" in script
            or "object[data]" in script
        ):
            return None
        if "fetch(window.location.href)" in script:
            return {
                "base64": "UEsDBHppcC1ieXRlcw==",
                "mimeType": self._mime_type,
            }
        return None


class FakeAnchorOnlyViewerPage(FakeViewerPage):
    def __init__(self, *, url: str, link_urls: list[str]) -> None:
        super().__init__(
            url=url,
            embedded_src="",
            response=FakeResponse(b""),
        )
        self._link_urls = link_urls

    def evaluate(self, script: str):
        if "document.querySelectorAll('a[href]')" in script:
            return self._link_urls
        if (
            "embed[src]" in script
            or "iframe[src]" in script
            or "object[data]" in script
        ):
            return None
        return None


class FakeClickable:
    def __init__(self, metadata: dict[str, object] | None = None) -> None:
        self.metadata = metadata or {}
        self.click_calls = 0

    def click(self) -> None:
        self.click_calls += 1

    def evaluate(self, script: str):
        return {
            "href": self.metadata.get("href"),
            "onclick": self.metadata.get("onclick"),
            "tag": self.metadata.get("tag"),
            "dataToggle": self.metadata.get("dataToggle"),
            "className": self.metadata.get("className"),
            "textContent": self.metadata.get("textContent"),
        }


class FakeContextPageRecord:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeModalPage:
    def __init__(self, modal) -> None:
        self._modal = modal
        self.url = "https://process5.gprocurement.go.th/example/detail"
        self.context = type(
            "Context",
            (),
            {"pages": [FakeContextPageRecord("chrome://new-tab-page/")]},
        )()

    def query_selector_all(self, selector: str):
        if selector == ".modal.show, .modal.fade.show, .swal2-popup, [role='dialog']":
            return [self._modal] if self._modal is not None else []
        if selector == ".modal.show, .modal.fade.show":
            return [self._modal]
        if selector == "table tbody tr":
            return []
        return []

    def wait_for_selector(self, selector: str, timeout=None) -> None:
        return None

    def evaluate(self, script: str, arg=None):
        if arg is not None and hasattr(arg, "click"):
            arg.click()
        return None

    @property
    def keyboard(self):
        return FakeKeyboard()


class FakeNoDownloadWaitModalPage(FakeModalPage):
    def expect_download(self, timeout=None):
        raise AssertionError(
            "should not enter expect_download for immediate E4514 modal"
        )


class FakeModal:
    def __init__(self, rows) -> None:
        self._rows = rows

    def query_selector_all(self, selector: str):
        if selector == "table tbody tr":
            return self._rows
        if selector == "th":
            return [
                FakeTextElement("ลำดับ"),
                FakeTextElement("รายละเอียด"),
                FakeTextElement("วันที่ประกาศ"),
                FakeTextElement("ดาวน์โหลด"),
            ]
        return []

    def is_visible(self) -> bool:
        return True


class FakePopupClickable(FakeClickable):
    def __init__(self, page, metadata: dict[str, object] | None = None) -> None:
        super().__init__(metadata)
        self._page = page

    def click(self) -> None:
        super().click()
        self._page.context.pages.append(
            FakeContextPageRecord("https://process5.gprocurement.go.th/new-tab.pdf")
        )


class FakeMissingFileClickable(FakeClickable):
    def __init__(self, page, modal, metadata: dict[str, object] | None = None) -> None:
        super().__init__(metadata)
        self._page = page
        self._modal = modal

    def click(self) -> None:
        super().click()
        self._page._modal = self._modal


class FakeOpensModalClickable(FakeClickable):
    def __init__(self, page, modal, metadata: dict[str, object] | None = None) -> None:
        super().__init__(metadata)
        self._page = page
        self._modal = modal

    def click(self) -> None:
        super().click()
        self._page._modal = self._modal


class FakeMissingFileModal:
    def __init__(self) -> None:
        self.dismissed = False

    def inner_text(self) -> str:
        return "ข้อความจากระบบ E4514 : ค้นหาไฟล์เอกสารไม่พบ ไม่พบไฟล์ในโครงการนี้"

    def is_visible(self) -> bool:
        return True

    def query_selector(self, selector: str):
        if "button" in selector:
            return self
        return None

    def click(self) -> None:
        self.dismissed = True


class FakeContentViewerPage(FakeViewerPage):
    def __init__(self, *, url: str, embedded_src: str, response: FakeResponse) -> None:
        super().__init__(url=url, embedded_src=embedded_src, response=response)
        self.go_back_calls = 0

    def go_back(self) -> None:
        self.go_back_calls += 1


class FakeDetailFlowPage:
    def __init__(self, *, url: str) -> None:
        self.url = url
        self.goto_calls: list[tuple[str, str | None, int | None]] = []
        self.keyboard = FakeKeyboard()

    def goto(self, url: str, wait_until=None, timeout=None) -> None:
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url


def test_doc_targets_include_final_tor() -> None:
    assert "เอกสารประกวดราคา" in DOCS_TO_DOWNLOAD


def test_consulting_document_label_counts_as_final_tor() -> None:
    assert is_final_tor_doc_label("เอกสารจ้างที่ปรึกษา") is True


def test_scope_of_work_label_counts_as_final_tor() -> None:
    assert is_final_tor_doc_label("ขอบเขตของงาน") is True


def test_budget_build_pdf_files_are_not_tor_files() -> None:
    assert is_tor_file("pB1.pdf") is False
    assert is_tor_file("B1.pdf") is False
    assert is_tor_file("B12.PDF") is False
    assert is_tor_file("tor-final.pdf") is True


def test_invitation_popup_collects_final_tor(monkeypatch, tmp_path: Path) -> None:
    clickable = object()
    page = FakePage(
        [
            FakeTable(
                ["ลำดับ", "ประกาศที่เกี่ยวข้อง", "วันที่ประกาศ", "ดูข้อมูล"],
                [
                    FakeRow(
                        [
                            FakeCell("1"),
                            FakeCell("ประกาศเชิญชวน"),
                            FakeCell("10/04/2569"),
                            FakeCell("", clickable=clickable),
                        ]
                    )
                ],
            )
        ]
    )

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._handle_direct_or_page_download",
        lambda page, btn, doc_name, document_context=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_documents_from_current_view",
        lambda page, include_label, document_context=None, **kwargs: [
            {
                "file_name": "invite.pdf",
                "file_bytes": b"invite",
                "source_label": "ประกาศเชิญชวน",
                "source_status_text": "",
                "source_page_text": "",
            },
            {
                "file_name": "tor.pdf",
                "file_bytes": b"tor",
                "source_label": "เอกสารประกวดราคา",
                "source_status_text": "",
                "source_page_text": "",
            },
        ],
        raising=False,
    )

    downloaded = _download_one_document(page, "ประกาศเชิญชวน")

    assert [document["source_label"] for document in downloaded] == [
        "ประกาศเชิญชวน",
        "เอกสารประกวดราคา",
    ]


def test_final_tor_target_does_not_match_draft_tor_row(monkeypatch) -> None:
    draft_clickable = FakeClickable()
    final_clickable = FakeClickable()
    page = FakePage(
        [
            FakeTable(
                ["ลำดับ", "เอกสาร", "วันที่ประกาศ", "ดูข้อมูล"],
                [
                    FakeRow(
                        [
                            FakeCell("1"),
                            FakeCell("ร่างเอกสารประกวดราคา(e-Bidding)"),
                            FakeCell("10/04/2569"),
                            FakeCell("", clickable=draft_clickable),
                        ]
                    ),
                    FakeRow(
                        [
                            FakeCell("2"),
                            FakeCell("เอกสารประกวดราคา"),
                            FakeCell("11/04/2569"),
                            FakeCell("", clickable=final_clickable),
                        ]
                    ),
                ],
            )
        ]
    )
    selected_doc_names: list[str] = []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._handle_subpage_download",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("final TOR target should not reuse the draft TOR row")
        ),
    )

    def fake_handle_direct_or_page_download(page, btn, doc_name, document_context=None):
        selected_doc_names.append(doc_name)
        assert btn is final_clickable
        return [
            {
                "file_name": "final-tor.zip",
                "file_bytes": b"zip",
                "source_label": doc_name,
                "source_status_text": "",
                "source_page_text": "",
            }
        ]

    monkeypatch.setattr(
        "egp_worker.browser_downloads._handle_direct_or_page_download",
        fake_handle_direct_or_page_download,
    )

    downloaded = _download_one_document(page, "เอกสารประกวดราคา")

    assert selected_doc_names == ["เอกสารประกวดราคา"]
    assert downloaded == [
        {
            "file_name": "final-tor.zip",
            "file_bytes": b"zip",
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]


def test_collect_downloaded_documents_preserves_provenance_fields(monkeypatch) -> None:
    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        lambda page, target_doc, document_context=None: (
            [
                {
                    "file_name": f"{target_doc}.pdf",
                    "file_bytes": target_doc.encode("utf-8"),
                    "source_label": target_doc,
                    "source_status_text": "",
                    "source_page_text": "",
                    "project_state": None,
                }
            ]
            if target_doc == "ประกาศเชิญชวน"
            else []
        ),
    )

    downloaded = collect_downloaded_documents(
        object(),
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
        source_page_text="รายละเอียดโครงการ",
        project_state="open_invitation",
    )

    assert downloaded == [
        {
            "file_name": "ประกาศเชิญชวน.pdf",
            "file_bytes": "ประกาศเชิญชวน".encode("utf-8"),
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_collect_downloaded_documents_skips_fallback_after_clean_targeted_success(
    monkeypatch,
) -> None:
    fallback_calls: list[str] = []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        lambda page, target_doc, document_context=None: (
            [
                {
                    "file_name": "invite.pdf",
                    "file_bytes": b"invite",
                    "source_label": target_doc,
                    "source_status_text": "",
                    "source_page_text": "",
                }
            ]
            if target_doc == "ประกาศเชิญชวน"
            else []
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._collect_detail_page_link_documents",
        lambda *args, **kwargs: fallback_calls.append("called") or [],
    )

    downloaded = collect_downloaded_documents(FakeDetailFlowPage(url="https://detail"))

    assert downloaded == [
        {
            "file_name": "invite.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]
    assert fallback_calls == []


def test_collect_downloaded_documents_keeps_fallback_when_targeted_collection_failed(
    monkeypatch,
) -> None:
    fallback_calls: list[str] = []

    def fake_download_one_document(page, target_doc, document_context=None):
        if target_doc == "ประกาศเชิญชวน":
            raise PlaywrightTimeout("invite stalled")
        if target_doc == "ประกาศราคากลาง":
            return [
                {
                    "file_name": "price.pdf",
                    "file_bytes": b"price",
                    "source_label": target_doc,
                    "source_status_text": "",
                    "source_page_text": "",
                }
            ]
        return []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        fake_download_one_document,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._collect_detail_page_link_documents",
        lambda *args, **kwargs: fallback_calls.append("called") or [],
    )

    downloaded = collect_downloaded_documents(FakeDetailFlowPage(url="https://detail"))

    assert downloaded == [
        {
            "file_name": "price.pdf",
            "file_bytes": b"price",
            "source_label": "ประกาศราคากลาง",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]
    assert fallback_calls == ["called"]


def test_click_back_or_exit_prefers_modal_local_exit_before_page_back(
    monkeypatch,
) -> None:
    class FakeExitPage:
        def __init__(self) -> None:
            self.keyboard = FakeKeyboard()
            self.modal_exit_attempts = 0
            self.page_back_attempts = 0

        def evaluate(self, script: str, arg=None):
            if "closestDialogs" in script:
                self.modal_exit_attempts += 1
                return True
            if "document.querySelectorAll('button')" in script:
                self.page_back_attempts += 1
                raise AssertionError(
                    "page-level back should not run after modal-local exit"
                )
            return False

    page = FakeExitPage()

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.clear_site_error_toast", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    _click_back_or_exit(page)

    assert page.modal_exit_attempts == 1
    assert page.page_back_attempts == 0
    assert page.keyboard.keys == []


def test_collect_downloaded_documents_continues_after_single_target_timeout(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_download_one_document(page, target_doc, document_context=None):
        calls.append(target_doc)
        if target_doc == "ประกาศเชิญชวน":
            raise PlaywrightTimeout("first target stalled")
        if target_doc == "ประกาศราคากลาง":
            return [
                {
                    "file_name": "price.pdf",
                    "file_bytes": b"price",
                    "source_label": target_doc,
                    "source_status_text": "",
                    "source_page_text": "",
                }
            ]
        return []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        fake_download_one_document,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._collect_detail_page_link_documents",
        lambda *args, **kwargs: [],
    )

    downloaded = collect_downloaded_documents(FakeDetailFlowPage(url="https://detail"))

    assert calls == DOCS_TO_DOWNLOAD
    assert downloaded == [
        {
            "file_name": "price.pdf",
            "file_bytes": b"price",
            "source_label": "ประกาศราคากลาง",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]


def test_collect_downloaded_documents_restores_project_detail_after_subpage_flow(
    monkeypatch,
) -> None:
    detail_url = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/detail/123"
    subpage_url = (
        "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/document/list"
    )
    page = FakeDetailFlowPage(url=detail_url)
    exit_clicks: list[str] = []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    def fake_download_one_document(page, target_doc, document_context=None):
        if target_doc == "ประกาศเชิญชวน":
            page.url = subpage_url
            return [
                {
                    "file_name": "invite.pdf",
                    "file_bytes": b"invite",
                    "source_label": "ประกาศเชิญชวน",
                    "source_status_text": "",
                    "source_page_text": "",
                }
            ]
        return []

    def fake_click_back_or_exit(page) -> None:
        exit_clicks.append(page.url)
        if page.url == subpage_url:
            page.url = detail_url

    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        fake_download_one_document,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._click_back_or_exit",
        fake_click_back_or_exit,
    )

    downloaded = collect_downloaded_documents(page)

    assert downloaded == [
        {
            "file_name": "invite.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]
    assert page.url == detail_url
    assert exit_clicks == [subpage_url]


def test_collect_downloaded_documents_keeps_exiting_until_original_detail_page(
    monkeypatch,
) -> None:
    detail_url = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/detail/123"
    popup_url = (
        "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/document/popup"
    )
    file_list_url = (
        "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/document/list"
    )
    page = FakeDetailFlowPage(url=detail_url)
    exit_clicks: list[str] = []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    def fake_download_one_document(page, target_doc, document_context=None):
        if target_doc == "ประกาศเชิญชวน":
            page.url = popup_url
            return [
                {
                    "file_name": "invite.pdf",
                    "file_bytes": b"invite",
                    "source_label": "ประกาศเชิญชวน",
                    "source_status_text": "",
                    "source_page_text": "",
                }
            ]
        return []

    def fake_click_back_or_exit(page) -> None:
        exit_clicks.append(page.url)
        if page.url == popup_url:
            page.url = file_list_url
        elif page.url == file_list_url:
            page.url = detail_url

    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        fake_download_one_document,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._click_back_or_exit",
        fake_click_back_or_exit,
    )

    collect_downloaded_documents(page)

    assert page.url == detail_url
    assert exit_clicks == [popup_url, file_list_url]


def test_collect_downloaded_documents_falls_back_to_procurement_plan_link_when_known_rows_missing(
    monkeypatch,
) -> None:
    plan_label = "P69020016424 - เอกสารแผนการจัดซื้อจัดจ้าง"
    clickable = FakeClickable(
        {
            "href": "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/plan/123",
            "textContent": plan_label,
            "tag": "a",
        }
    )
    page = FakePage(
        [
            FakeTable(
                ["รายการ", "ลิงก์"],
                [
                    FakeRow(
                        [
                            FakeCell("แผนการจัดซื้อจัดจ้าง"),
                            FakeCell(plan_label, clickable=clickable),
                        ]
                    )
                ],
            )
        ]
    )
    captured_doc_names: list[str] = []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        lambda page, target_doc, document_context=None: [],
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    def fake_handle_direct_or_page_download(page, btn, doc_name, document_context=None):
        captured_doc_names.append(doc_name)
        return [
            {
                "file_name": "procurement-plan.pdf",
                "file_bytes": b"plan",
                "source_label": doc_name,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ]

    monkeypatch.setattr(
        "egp_worker.browser_downloads._handle_direct_or_page_download",
        fake_handle_direct_or_page_download,
    )

    downloaded = collect_downloaded_documents(
        page,
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
        source_page_text="รายละเอียดโครงการ",
        project_state="open_invitation",
    )

    assert captured_doc_names == [plan_label]
    assert downloaded == [
        {
            "file_name": "procurement-plan.pdf",
            "file_bytes": b"plan",
            "source_label": plan_label,
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_collect_downloaded_documents_dedupes_procurement_plan_fallback_results(
    monkeypatch,
) -> None:
    plan_label = "P69020016424 - เอกสารแผนการจัดซื้อจัดจ้าง"
    clickable = FakeClickable(
        {
            "href": "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/plan/123",
            "textContent": plan_label,
            "tag": "a",
        }
    )
    page = FakePage(
        [
            FakeTable(
                ["รายการ", "ลิงก์"],
                [
                    FakeRow(
                        [
                            FakeCell("แผนการจัดซื้อจัดจ้าง"),
                            FakeCell(plan_label, clickable=clickable),
                        ]
                    )
                ],
            )
        ]
    )

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    def fake_download_one_document(page, target_doc, document_context=None):
        if target_doc == "ประกาศเชิญชวน":
            return [
                {
                    "file_name": "procurement-plan.pdf",
                    "file_bytes": b"plan",
                    "source_label": plan_label,
                    "source_status_text": document_context["source_status_text"],
                    "source_page_text": document_context["source_page_text"],
                    "project_state": document_context["project_state"],
                }
            ]
        return []

    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        fake_download_one_document,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._handle_direct_or_page_download",
        lambda page, btn, doc_name, document_context=None: [
            {
                "file_name": "procurement-plan.pdf",
                "file_bytes": b"plan",
                "source_label": doc_name,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ],
    )

    downloaded = collect_downloaded_documents(
        page,
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
        source_page_text="รายละเอียดโครงการ",
        project_state="open_invitation",
    )

    assert downloaded == [
        {
            "file_name": "procurement-plan.pdf",
            "file_bytes": b"plan",
            "source_label": plan_label,
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_collect_downloaded_documents_falls_back_to_safe_standalone_anchor(
    monkeypatch,
) -> None:
    plan_label = "P69020016424 - เอกสารแผนการจัดซื้อจัดจ้าง"
    clickable = FakeClickable(
        {
            "href": "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/plan/123",
            "textContent": plan_label,
            "tag": "a",
        }
    )
    page = FakePage([], standalone_clickables=[clickable])
    captured_doc_names: list[str] = []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        lambda page, target_doc, document_context=None: [],
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    def fake_handle_direct_or_page_download(page, btn, doc_name, document_context=None):
        captured_doc_names.append(doc_name)
        return [
            {
                "file_name": "procurement-plan.pdf",
                "file_bytes": b"plan",
                "source_label": doc_name,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ]

    monkeypatch.setattr(
        "egp_worker.browser_downloads._handle_direct_or_page_download",
        fake_handle_direct_or_page_download,
    )

    downloaded = collect_downloaded_documents(
        page,
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
        source_page_text="รายละเอียดโครงการ",
        project_state="open_invitation",
    )

    assert captured_doc_names == [plan_label]
    assert downloaded == [
        {
            "file_name": "procurement-plan.pdf",
            "file_bytes": b"plan",
            "source_label": plan_label,
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_collect_downloaded_documents_dedupes_table_and_standalone_anchor_candidates(
    monkeypatch,
) -> None:
    plan_label = "P69020016424 - เอกสารแผนการจัดซื้อจัดจ้าง"
    table_clickable = FakeClickable(
        {
            "href": "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/plan/123",
            "textContent": plan_label,
            "tag": "a",
        }
    )
    anchor_clickable = FakeClickable(
        {
            "href": "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/plan/123",
            "textContent": plan_label,
            "tag": "a",
        }
    )
    page = FakePage(
        [
            FakeTable(
                ["รายการ", "ลิงก์"],
                [
                    FakeRow(
                        [
                            FakeCell("แผนการจัดซื้อจัดจ้าง"),
                            FakeCell(plan_label, clickable=table_clickable),
                        ]
                    )
                ],
            )
        ],
        standalone_clickables=[anchor_clickable],
    )
    captured_doc_names: list[str] = []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        lambda page, target_doc, document_context=None: [],
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    def fake_handle_direct_or_page_download(page, btn, doc_name, document_context=None):
        captured_doc_names.append(doc_name)
        return [
            {
                "file_name": "procurement-plan.pdf",
                "file_bytes": b"plan",
                "source_label": doc_name,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ]

    monkeypatch.setattr(
        "egp_worker.browser_downloads._handle_direct_or_page_download",
        fake_handle_direct_or_page_download,
    )

    downloaded = collect_downloaded_documents(
        page,
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
        source_page_text="รายละเอียดโครงการ",
        project_state="open_invitation",
    )

    assert set(captured_doc_names) == {plan_label}
    assert downloaded == [
        {
            "file_name": "procurement-plan.pdf",
            "file_bytes": b"plan",
            "source_label": plan_label,
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_collect_downloaded_documents_falls_back_to_plain_table_anchor_without_tbody(
    monkeypatch,
) -> None:
    plan_label = (
        "P69020016424 - การศึกษารูปแบบการทำงานของระบบสนับสนุนการแลกเปลี่ยนข้อมูลด้านการค้าดิจิทัล"
    )
    clickable = FakeClickable(
        {
            "href": None,
            "onclick": None,
            "textContent": plan_label,
            "tag": "a",
        }
    )
    page = FakePage(
        [
            FakeTable(
                [],
                [
                    FakeRow(
                        [
                            FakeCell("แผนการจัดซื้อจัดจ้าง"),
                            FakeCell(plan_label, clickable=clickable),
                        ]
                    )
                ],
                has_tbody=False,
            )
        ]
    )
    captured_doc_names: list[str] = []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_one_document",
        lambda page, target_doc, document_context=None: [],
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    def fake_handle_direct_or_page_download(page, btn, doc_name, document_context=None):
        captured_doc_names.append(doc_name)
        return [
            {
                "file_name": "procurement-plan.pdf",
                "file_bytes": b"plan",
                "source_label": doc_name,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ]

    monkeypatch.setattr(
        "egp_worker.browser_downloads._handle_direct_or_page_download",
        fake_handle_direct_or_page_download,
    )

    downloaded = collect_downloaded_documents(
        page,
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
        source_page_text="รายละเอียดโครงการ",
        project_state="open_invitation",
    )

    assert captured_doc_names == [plan_label]
    assert downloaded == [
        {
            "file_name": "procurement-plan.pdf",
            "file_bytes": b"plan",
            "source_label": plan_label,
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_invitation_popup_preserves_provenance_for_nested_downloads(
    monkeypatch, tmp_path: Path
) -> None:
    clickable = object()
    page = FakePage(
        [
            FakeTable(
                ["ลำดับ", "ประกาศที่เกี่ยวข้อง", "วันที่ประกาศ", "ดูข้อมูล"],
                [
                    FakeRow(
                        [
                            FakeCell("1"),
                            FakeCell("ประกาศเชิญชวน"),
                            FakeCell("10/04/2569"),
                            FakeCell("", clickable=clickable),
                        ]
                    )
                ],
            )
        ]
    )

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._handle_direct_or_page_download",
        lambda page, btn, doc_name, document_context=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_documents_from_current_view",
        lambda page, include_label, document_context=None, **kwargs: [
            {
                "file_name": "invite.pdf",
                "file_bytes": b"invite",
                "source_label": "ประกาศเชิญชวน",
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ],
        raising=False,
    )

    downloaded = _download_one_document(
        page,
        "ประกาศเชิญชวน",
        document_context={
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        },
    )

    assert downloaded == [
        {
            "file_name": "invite.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_save_from_new_tab_uses_request_for_blob_viewer(monkeypatch) -> None:
    viewer_page = FakeViewerPage(
        url="blob:https://process5.gprocurement.go.th/example-blob",
        embedded_src="https://process5.gprocurement.go.th/egp-download/final-tor.zip",
        response=FakeResponse(
            b"PK\x03\x04zip-bytes",
            headers={"content-type": "application/zip"},
        ),
    )

    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not try Ctrl+S before request fallback")
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._cancel_pending_downloads", lambda page: None
    )

    downloaded = _save_from_new_tab(viewer_page, "ประกาศเชิญชวน")

    assert downloaded == [
        {
            "file_name": "ประกาศเชิญชวน.zip",
            "file_bytes": b"PK\x03\x04zip-bytes",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]
    assert viewer_page.request.calls == [
        {
            "url": "https://process5.gprocurement.go.th/egp-download/final-tor.zip",
            "timeout": SUBPAGE_DOWNLOAD_TIMEOUT,
        }
    ]


def test_save_from_new_tab_uses_blob_fetch_before_ctrl_s_when_no_request_url(
    monkeypatch,
) -> None:
    viewer_page = FakeBlobOnlyViewerPage(
        url="blob:https://process5.gprocurement.go.th/example-blob",
        response=FakeResponse(
            b"PK\x03\x04zip-bytes",
            headers={"content-type": "application/zip"},
        ),
        mime_type="application/zip",
    )

    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not try Ctrl+S when blob fetch succeeds")
        ),
    )

    downloaded = _save_from_new_tab(viewer_page, "ประกาศเชิญชวน")

    assert downloaded == [
        {
            "file_name": "ประกาศเชิญชวน.zip",
            "file_bytes": b"PK\x03\x04zip-bytes",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]
    assert viewer_page.request.calls == []


def test_infer_document_url_scans_anchor_links_when_viewer_has_no_embed() -> None:
    page = FakeAnchorOnlyViewerPage(
        url="https://process5.gprocurement.go.th/egp2procmainWeb/jsp/procsearch.sch?proc_id=ShowHTMLFile",
        link_urls=[
            "https://example.com/not-allowed.pdf",
            "/egp-download/invitation.pdf",
        ],
    )

    assert (
        _infer_document_url_from_page(page)
        == "https://process5.gprocurement.go.th/egp-download/invitation.pdf"
    )


def test_handle_direct_or_page_download_skips_expect_download_for_modal_buttons(
    monkeypatch,
) -> None:
    page = FakePage([])
    clickable = FakeClickable(
        {
            "href": None,
            "onclick": None,
            "tag": "a",
            "dataToggle": "modal",
            "className": "btn btn-light btn-icon",
            "textContent": "description",
        }
    )

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.clear_site_error_toast", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not wait for a download event")
        ),
    )

    downloaded = _handle_direct_or_page_download(page, clickable, "ประกาศเชิญชวน")

    assert downloaded is None
    assert clickable.click_calls == 1


def test_handle_direct_or_page_download_modal_button_captures_online_viewer_tab(
    monkeypatch,
) -> None:
    page = FakePage([])
    page.context.pages = [page]
    delayed_viewer = FakeContextPageRecord("about:blank")

    class FakeModalOnlineViewerClickable(FakeClickable):
        def click(self) -> None:
            super().click()
            page.context.pages.append(delayed_viewer)

    clickable = FakeModalOnlineViewerClickable(
        {
            "href": None,
            "onclick": None,
            "tag": "a",
            "dataToggle": "modal",
            "className": "btn btn-light btn-icon",
            "textContent": "description",
        }
    )
    sleep_state = {"count": 0}

    def fake_sleep(*args, **kwargs) -> None:
        sleep_state["count"] += 1
        if sleep_state["count"] >= 2 and not delayed_viewer.closed:
            delayed_viewer.url = "blob:https://process5.gprocurement.go.th/invitation"

    def fake_save_from_new_tab(
        new_page, file_label, fallback_url=None, document_context=None
    ):
        assert new_page is delayed_viewer
        return [
            {
                "file_name": "invite.pdf",
                "file_bytes": b"invite",
                "source_label": file_label,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ]

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.clear_site_error_toast", lambda page: False
    )
    monkeypatch.setattr("egp_worker.browser_downloads._sleep", fake_sleep)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._skip_known_missing_file_modal",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._save_from_new_tab",
        fake_save_from_new_tab,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "modal-looking online viewer should not wait for download event"
            )
        ),
    )

    downloaded = _handle_direct_or_page_download(
        page,
        clickable,
        "ประกาศเชิญชวน",
        document_context={
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        },
    )

    assert clickable.click_calls == 1
    assert delayed_viewer.closed is True
    assert downloaded == [
        {
            "file_name": "invite.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_download_documents_from_current_view_handles_modal_button_popup_without_download_wait(
    monkeypatch,
) -> None:
    page = FakeModalPage(None)
    download_button = FakePopupClickable(
        page,
        {
            "href": None,
            "onclick": None,
            "tag": "a",
            "dataToggle": "modal",
            "className": "btn btn-light btn-icon ng-star-inserted",
            "textContent": "file_download",
        },
    )
    page._modal = FakeModal(
        [
            FakeRow(
                [
                    FakeCell("1"),
                    FakeCell("ประกาศเชิญชวน"),
                    FakeCell("16/04/2569"),
                    FakeCell("", clickable=download_button),
                ]
            )
        ]
    )

    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not wait for download event for modal popup buttons")
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._save_from_new_tab",
        lambda new_page, file_label, document_context=None: [
            {
                "file_name": "invite.pdf",
                "file_bytes": b"invite",
                "source_label": file_label,
                "source_status_text": "",
                "source_page_text": "",
            }
        ],
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._click_back_or_exit", lambda page: None
    )

    downloaded = _download_documents_from_current_view(
        page,
        include_label=lambda label: "ประกาศเชิญชวน" in label,
    )

    assert downloaded == [
        {
            "file_name": "invite.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]


def test_capture_followup_skips_known_missing_file_modal(monkeypatch, caplog) -> None:
    page = FakePage([])
    missing_modal = FakeMissingFileModal()
    page._modal = missing_modal

    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    caplog.set_level(logging.INFO, logger="egp_worker.browser_downloads")

    downloaded = _capture_followup_after_click(
        page,
        file_label="เอกสารประกวดราคา",
        source_doc_label="ประกาศเชิญชวน",
        url_before_click=page.url,
        pages_before_click=0,
        timeout_s=0.2,
    )

    assert downloaded == []
    assert missing_modal.dismissed is True
    event = next(
        record
        for record in caplog.records
        if record.egp_event == "document_unavailable_on_source"
    )
    assert event.source_doc_label == "ประกาศเชิญชวน"
    assert event.inner_file_label == "เอกสารประกวดราคา"
    assert event.download_click_context == "nested_modal_followup"


def test_capture_followup_collects_download_modal_after_plain_link_click(
    monkeypatch,
) -> None:
    page = FakePage([])
    modal = FakeModal(
        [
            FakeRow(
                [
                    FakeCell("1"),
                    FakeCell("เอกสารแผนการจัดซื้อจัดจ้าง"),
                    FakeCell("18/02/2569"),
                    FakeCell(""),
                ]
            )
        ]
    )

    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._find_modal_with_downloads",
        lambda page: modal,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_documents_from_current_view",
        lambda page, include_label, source_doc_label="", document_context=None, current_modal_signature=None: [
            {
                "file_name": "procurement-plan.pdf",
                "file_bytes": b"plan",
                "source_label": source_doc_label,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ],
    )

    downloaded = _capture_followup_after_click(
        page,
        file_label="P69020016424 - แผนการจัดซื้อจัดจ้าง",
        url_before_click=page.url,
        pages_before_click=len(page.context.pages),
        source_doc_label="P69020016424 - แผนการจัดซื้อจัดจ้าง",
        document_context={
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        },
        timeout_s=0.2,
    )

    assert downloaded == [
        {
            "file_name": "procurement-plan.pdf",
            "file_bytes": b"plan",
            "source_label": "P69020016424 - แผนการจัดซื้อจัดจ้าง",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_download_documents_from_current_view_does_not_recurse_when_modal_reopens_unchanged(
    monkeypatch,
) -> None:
    page = FakeModalPage(None)
    clock = {"now": 0.0}

    def fake_sleep(*args, **kwargs) -> None:
        clock["now"] += 0.1

    class FakeReopensSameModalClickable(FakeClickable):
        def __init__(self, metadata: dict[str, object] | None = None) -> None:
            super().__init__(metadata)

        def click(self) -> None:
            super().click()
            page._modal = modal

    download_button = FakeReopensSameModalClickable(
        {
            "href": None,
            "onclick": None,
            "tag": "a",
            "dataToggle": "modal",
            "textContent": "description",
        }
    )
    modal = FakeModal(
        [
            FakeRow(
                [
                    FakeCell("1"),
                    FakeCell("ร่างขอบเขตของงาน"),
                    FakeCell("18/02/2569"),
                    FakeCell("", clickable=download_button),
                ]
            )
        ]
    )
    page._modal = modal

    monkeypatch.setattr("egp_worker.browser_downloads._sleep", fake_sleep)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.time.monotonic", lambda: clock["now"]
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._skip_known_missing_file_modal",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._click_and_capture_immediate_download_or_missing_modal",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        lambda *args, **kwargs: (_ for _ in ()).throw(PlaywrightTimeout("timed out")),
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._cancel_pending_downloads", lambda page: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._wait_for_actionable_new_page",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._click_back_or_exit", lambda page: None
    )

    downloaded = _download_documents_from_current_view(
        page,
        include_label=lambda label: "ร่างขอบเขตของงาน" in label,
        source_doc_label="ร่างเอกสารประกวดราคา(e-Bidding)",
    )

    assert download_button.click_calls == 3
    assert downloaded == []


def test_capture_followup_ignores_blank_new_tab_until_modal_appears(
    monkeypatch,
) -> None:
    page = FakePage([])
    blank_page = FakeContextPageRecord("about:blank")
    page.context.pages = [FakeContextPageRecord("chrome://new-tab-page/"), blank_page]
    modal = FakeModal(
        [
            FakeRow(
                [
                    FakeCell("1"),
                    FakeCell("เอกสารแผนการจัดซื้อจัดจ้าง"),
                    FakeCell("18/02/2569"),
                    FakeCell(""),
                ]
            )
        ]
    )
    modal_state = {"visible": False}

    def fake_sleep(*args, **kwargs) -> None:
        modal_state["visible"] = True

    monkeypatch.setattr("egp_worker.browser_downloads._sleep", fake_sleep)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._find_modal_with_downloads",
        lambda page: modal if modal_state["visible"] else None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._save_from_new_tab",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("blank placeholder tab should be ignored")
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_documents_from_current_view",
        lambda page, include_label, source_doc_label="", document_context=None, current_modal_signature=None: [
            {
                "file_name": "procurement-plan.pdf",
                "file_bytes": b"plan",
                "source_label": source_doc_label,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ],
    )

    downloaded = _capture_followup_after_click(
        page,
        file_label="P69020016424 - แผนการจัดซื้อจัดจ้าง",
        url_before_click=page.url,
        pages_before_click=1,
        source_doc_label="P69020016424 - แผนการจัดซื้อจัดจ้าง",
        document_context={
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        },
        timeout_s=0.2,
    )

    assert blank_page.closed is True
    assert downloaded == [
        {
            "file_name": "procurement-plan.pdf",
            "file_bytes": b"plan",
            "source_label": "P69020016424 - แผนการจัดซื้อจัดจ้าง",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_capture_followup_keeps_blank_tab_until_it_becomes_blob_viewer(
    monkeypatch,
) -> None:
    page = FakePage([])
    delayed_viewer = FakeContextPageRecord("about:blank")
    page.context.pages = [
        FakeContextPageRecord("chrome://new-tab-page/"),
        delayed_viewer,
    ]
    sleep_state = {"count": 0}

    def fake_sleep(*args, **kwargs) -> None:
        sleep_state["count"] += 1
        if sleep_state["count"] == 1 and not delayed_viewer.closed:
            delayed_viewer.url = "blob:https://process5.gprocurement.go.th/invitation"

    def fake_save_from_new_tab(new_page, file_label, document_context=None):
        assert new_page is delayed_viewer
        assert delayed_viewer.closed is False
        return [
            {
                "file_name": "invite.pdf",
                "file_bytes": b"invite",
                "source_label": file_label,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ]

    monkeypatch.setattr("egp_worker.browser_downloads._sleep", fake_sleep)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._find_modal_with_downloads",
        lambda page: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._save_from_new_tab",
        fake_save_from_new_tab,
    )

    downloaded = _capture_followup_after_click(
        page,
        file_label="ประกาศเชิญชวน",
        url_before_click=page.url,
        pages_before_click=1,
        source_doc_label="ประกาศเชิญชวน",
        document_context={
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        },
        timeout_s=0.5,
    )

    assert delayed_viewer.closed is True
    assert downloaded == [
        {
            "file_name": "invite.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_capture_followup_closes_surplus_new_tabs_before_processing_latest(
    monkeypatch,
) -> None:
    page = FakePage([])
    first_tab = FakeContextPageRecord("blob:https://process5.gprocurement.go.th/first")
    latest_tab = FakeContextPageRecord(
        "blob:https://process5.gprocurement.go.th/latest"
    )
    page.context.pages = [
        FakeContextPageRecord("chrome://new-tab-page/"),
        first_tab,
        latest_tab,
    ]
    captured_pages: list[FakeContextPageRecord] = []

    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._find_modal_with_downloads",
        lambda page: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._save_from_new_tab",
        lambda new_page, file_label, document_context=None: (
            captured_pages.append(new_page)
            or [
                {
                    "file_name": "invite.pdf",
                    "file_bytes": b"invite",
                    "source_label": file_label,
                    "source_status_text": document_context["source_status_text"],
                    "source_page_text": document_context["source_page_text"],
                    "project_state": document_context["project_state"],
                }
            ]
        ),
    )

    downloaded = _capture_followup_after_click(
        page,
        file_label="ประกาศเชิญชวน",
        url_before_click=page.url,
        pages_before_click=1,
        source_doc_label="ประกาศเชิญชวน",
        document_context={
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        },
        timeout_s=0.2,
    )

    assert captured_pages == [latest_tab]
    assert first_tab.closed is True
    assert latest_tab.closed is True
    assert downloaded == [
        {
            "file_name": "invite.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_capture_followup_detects_same_page_inline_viewer(
    monkeypatch,
) -> None:
    page = FakePage([])

    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._find_modal_with_downloads",
        lambda page: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._infer_document_url_from_page",
        lambda page: "https://process5.gprocurement.go.th/egp-download/invitation.pdf",
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._save_from_content_page",
        lambda page, file_label, document_context=None: [
            {
                "file_name": "invitation.pdf",
                "file_bytes": b"invite",
                "source_label": file_label,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ],
    )

    downloaded = _capture_followup_after_click(
        page,
        file_label="ประกาศเชิญชวน",
        url_before_click=page.url,
        pages_before_click=len(page.context.pages),
        source_doc_label="ประกาศเชิญชวน",
        document_context={
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_consulting",
        },
        timeout_s=0.2,
    )

    assert downloaded == [
        {
            "file_name": "invitation.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_consulting",
        }
    ]


def test_handle_direct_or_page_download_uses_followup_after_plain_link_click(
    monkeypatch,
) -> None:
    page = FakePage([])
    clickable = FakeClickable(
        {
            "href": None,
            "onclick": None,
            "tag": "a",
            "textContent": "P69020016424 - แผนการจัดซื้อจัดจ้าง",
        }
    )

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.clear_site_error_toast", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    def fake_immediate(page, click_action, **kwargs):
        click_action()
        return None

    monkeypatch.setattr(
        "egp_worker.browser_downloads._click_and_capture_immediate_download_or_missing_modal",
        fake_immediate,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._capture_followup_after_click",
        lambda page, **kwargs: [
            {
                "file_name": "procurement-plan.pdf",
                "file_bytes": b"plan",
                "source_label": kwargs["source_doc_label"],
                "source_status_text": kwargs["document_context"]["source_status_text"],
                "source_page_text": kwargs["document_context"]["source_page_text"],
                "project_state": kwargs["document_context"]["project_state"],
            }
        ],
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not fall through to expect_download retry")
        ),
    )

    downloaded = _handle_direct_or_page_download(
        page,
        clickable,
        "P69020016424 - แผนการจัดซื้อจัดจ้าง",
        document_context={
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        },
    )

    assert clickable.click_calls == 1
    assert downloaded == [
        {
            "file_name": "procurement-plan.pdf",
            "file_bytes": b"plan",
            "source_label": "P69020016424 - แผนการจัดซื้อจัดจ้าง",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_handle_direct_or_page_download_closes_surplus_new_tabs_for_consulting_invitation(
    monkeypatch,
) -> None:
    page = FakePage([])
    clickable = FakeClickable(
        {
            "href": "javascript:void(0)",
            "onclick": None,
            "tag": "a",
            "textContent": "ประกาศเชิญชวน",
        }
    )
    first_tab = FakeContextPageRecord("blob:https://process5.gprocurement.go.th/first")
    latest_tab = FakeContextPageRecord(
        "blob:https://process5.gprocurement.go.th/latest"
    )
    captured_pages: list[FakeContextPageRecord] = []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.clear_site_error_toast", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    def fake_immediate(page, click_action, **kwargs):
        click_action()
        page.context.pages.extend([first_tab, latest_tab])
        return None

    monkeypatch.setattr(
        "egp_worker.browser_downloads._click_and_capture_immediate_download_or_missing_modal",
        fake_immediate,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._save_from_new_tab",
        lambda new_page, file_label, fallback_url=None, document_context=None: (
            captured_pages.append(new_page)
            or [
                {
                    "file_name": "invite.pdf",
                    "file_bytes": b"invite",
                    "source_label": file_label,
                    "source_status_text": "",
                    "source_page_text": "",
                }
            ]
        ),
    )

    downloaded = _handle_direct_or_page_download(
        page,
        clickable,
        "ประกาศเชิญชวน",
        document_context={"project_state": "open_consulting"},
    )

    assert captured_pages == [latest_tab]
    assert first_tab.closed is True
    assert latest_tab.closed is True
    assert downloaded == [
        {
            "file_name": "invite.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]


def test_handle_direct_or_page_download_uses_longer_followup_for_consulting_invitation(
    monkeypatch,
) -> None:
    page = FakePage([])
    clickable = FakeClickable(
        {
            "href": None,
            "onclick": None,
            "tag": "a",
            "textContent": "ประกาศเชิญชวน",
        }
    )
    captured_timeouts: list[float] = []

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.clear_site_error_toast", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    def fake_immediate(page, click_action, **kwargs):
        click_action()
        return None

    monkeypatch.setattr(
        "egp_worker.browser_downloads._click_and_capture_immediate_download_or_missing_modal",
        fake_immediate,
    )

    def fake_followup(page, **kwargs):
        captured_timeouts.append(float(kwargs["timeout_s"]))
        return []

    monkeypatch.setattr(
        "egp_worker.browser_downloads._capture_followup_after_click", fake_followup
    )

    downloaded = _handle_direct_or_page_download(
        page,
        clickable,
        "ประกาศเชิญชวน",
        document_context={"project_state": "open_consulting"},
    )

    assert downloaded == []
    assert captured_timeouts == [4.0]


def test_handle_direct_or_page_download_standard_invitation_skips_probe_click(
    monkeypatch,
) -> None:
    page = FakePage([])
    clickable = FakeClickable(
        {
            "href": "javascript:void(0)",
            "onclick": None,
            "tag": "a",
            "textContent": "ประกาศเชิญชวน",
        }
    )

    class FakeDownload:
        suggested_filename = "invite.pdf"

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.clear_site_error_toast", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._click_and_capture_immediate_download_or_missing_modal",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "standard invitation path should not pre-click before expect_download"
            )
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._capture_followup_after_click",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "standard invitation path should not prefer followup capture"
            )
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        lambda *args, **kwargs: FakeDownload(),
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_to_document",
        lambda download, source_label, file_name, document_context=None: {
            "file_name": file_name,
            "file_bytes": b"invite",
            "source_label": source_label,
            "source_status_text": "",
            "source_page_text": "",
        },
    )

    downloaded = _handle_direct_or_page_download(page, clickable, "ประกาศเชิญชวน")

    assert downloaded == [
        {
            "file_name": "ประกาศเชิญชวน.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]


def test_handle_direct_or_page_download_waits_for_delayed_online_viewer_after_timeout(
    monkeypatch,
) -> None:
    page = FakePage([])
    page.context.pages = [page]
    delayed_viewer = FakeContextPageRecord("about:blank")
    clickable = FakeClickable(
        {
            "href": "javascript:void(0)",
            "onclick": None,
            "tag": "a",
            "textContent": "ประกาศเชิญชวน",
        }
    )
    sleep_state = {"after_viewer_added": 0}

    def fake_run_with_toast_recovery(page, action, label, retries=0, **kwargs):
        assert retries == 0
        page.context.pages.append(delayed_viewer)
        raise PlaywrightTimeout("direct download timed out")

    def fake_sleep(*args, **kwargs) -> None:
        if delayed_viewer in page.context.pages:
            sleep_state["after_viewer_added"] += 1
            if sleep_state["after_viewer_added"] >= 2 and not delayed_viewer.closed:
                delayed_viewer.url = (
                    "blob:https://process5.gprocurement.go.th/invitation"
                )

    def fake_save_from_new_tab(
        new_page, file_label, fallback_url=None, document_context=None
    ):
        assert new_page is delayed_viewer
        assert delayed_viewer.closed is False
        return [
            {
                "file_name": "invite.pdf",
                "file_bytes": b"invite",
                "source_label": file_label,
                "source_status_text": document_context["source_status_text"],
                "source_page_text": document_context["source_page_text"],
                "project_state": document_context["project_state"],
            }
        ]

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.clear_site_error_toast", lambda page: False
    )
    monkeypatch.setattr("egp_worker.browser_downloads._sleep", fake_sleep)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        fake_run_with_toast_recovery,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._cancel_pending_downloads", lambda page: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._skip_known_missing_file_modal",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._save_from_new_tab",
        fake_save_from_new_tab,
    )

    downloaded = _handle_direct_or_page_download(
        page,
        clickable,
        "ประกาศเชิญชวน",
        document_context={
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        },
    )

    assert delayed_viewer.closed is True
    assert downloaded == [
        {
            "file_name": "invite.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "รายละเอียดโครงการ",
            "project_state": "open_invitation",
        }
    ]


def test_handle_direct_or_page_download_skips_known_missing_file_modal(
    monkeypatch,
) -> None:
    page = FakePage([])
    missing_modal = FakeMissingFileModal()
    clickable = FakeClickable(
        {
            "href": None,
            "onclick": None,
            "tag": "a",
            "dataToggle": None,
            "className": "btn btn-light btn-icon",
            "textContent": "download",
        }
    )

    def fake_download_attempt(page, action, label, retries=0, **kwargs):
        page._modal = missing_modal
        raise PlaywrightTimeout("timed out")

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.clear_site_error_toast", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        fake_download_attempt,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._cancel_pending_downloads", lambda page: None
    )

    downloaded = _handle_direct_or_page_download(page, clickable, "ประกาศเชิญชวน")

    assert downloaded == []
    assert missing_modal.dismissed is True


def test_handle_direct_or_page_download_consulting_path_checks_immediate_missing_modal_before_download_wait(
    monkeypatch,
) -> None:
    page = FakeNoDownloadWaitPage([])
    missing_modal = FakeMissingFileModal()
    clickable = FakeMissingFileClickable(
        page,
        missing_modal,
        {
            "href": None,
            "onclick": None,
            "tag": "a",
            "dataToggle": None,
            "className": "btn btn-light btn-icon",
            "textContent": "download",
        },
    )

    monkeypatch.setattr("egp_worker.browser_downloads.dismiss_modal", lambda page: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.clear_site_error_toast", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )

    downloaded = _handle_direct_or_page_download(
        page,
        clickable,
        "ประกาศเชิญชวน",
        document_context={"project_state": "open_consulting"},
    )

    assert downloaded == []
    assert clickable.click_calls == 1
    assert missing_modal.dismissed is True


def test_download_documents_from_current_view_checks_immediate_missing_modal_before_nested_wait(
    monkeypatch,
) -> None:
    page = FakeNoDownloadWaitModalPage(None)
    missing_modal = FakeMissingFileModal()
    download_button = FakeMissingFileClickable(
        page,
        missing_modal,
        {
            "href": None,
            "onclick": None,
            "tag": "a",
            "dataToggle": None,
            "className": "btn btn-light btn-icon",
            "textContent": "download",
        },
    )
    page._modal = FakeModal(
        [
            FakeRow(
                [
                    FakeCell("1"),
                    FakeCell("ประกาศเชิญชวน"),
                    FakeCell("16/04/2569"),
                    FakeCell("", clickable=download_button),
                ]
            )
        ]
    )

    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._click_back_or_exit", lambda page: None
    )

    downloaded = _download_documents_from_current_view(
        page,
        include_label=lambda label: "ประกาศเชิญชวน" in label,
    )

    assert downloaded == []
    assert download_button.click_calls == 1
    assert missing_modal.dismissed is True


def test_save_from_content_page_uses_request_for_blob_viewer_before_ctrl_s(
    monkeypatch,
) -> None:
    viewer_page = FakeContentViewerPage(
        url="blob:https://process5.gprocurement.go.th/example-blob",
        embedded_src="https://process5.gprocurement.go.th/egp-download/final-tor.zip",
        response=FakeResponse(
            b"PK\x03\x04zip-bytes",
            headers={"content-type": "application/zip"},
        ),
    )

    monkeypatch.setattr(
        "egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not try Ctrl+S")
        ),
    )

    downloaded = _save_from_content_page(viewer_page, "ประกาศเชิญชวน")

    assert downloaded == [
        {
            "file_name": "ประกาศเชิญชวน.zip",
            "file_bytes": b"PK\x03\x04zip-bytes",
            "source_label": "ประกาศเชิญชวน",
            "source_status_text": "",
            "source_page_text": "",
        }
    ]
    assert viewer_page.request.calls == [
        {
            "url": "https://process5.gprocurement.go.th/egp-download/final-tor.zip",
            "timeout": SUBPAGE_DOWNLOAD_TIMEOUT,
        }
    ]
    assert viewer_page.go_back_calls == 1


def test_download_to_document_falls_back_to_save_as_when_playwright_path_expired(
    tmp_path,
) -> None:
    expired_path = tmp_path / "missing-playwright-artifact"
    download = FakeDownloadWithExpiredPath(expired_path)

    document = _download_to_document(download, source_label="ร่างเอกสารประกวดราคา")

    assert document["file_name"] == "tor.zip"
    assert document["file_bytes"] == b"zip-bytes"
    assert document["source_label"] == "ร่างเอกสารประกวดราคา"
    assert len(download.saved_paths) == 1
