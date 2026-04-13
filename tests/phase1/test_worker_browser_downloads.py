from __future__ import annotations

from pathlib import Path

from egp_worker.browser_downloads import (
    DOCS_TO_DOWNLOAD,
    SUBPAGE_DOWNLOAD_TIMEOUT,
    _download_one_document,
    _save_from_new_tab,
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
    def __init__(self, headers: list[str], rows: list[FakeRow]) -> None:
        self._headers = headers
        self._rows = rows

    def query_selector_all(self, selector: str):
        if selector == "th":
            return [FakeTextElement(text) for text in self._headers]
        if selector == "tbody tr":
            return self._rows
        return []


class FakePage:
    def __init__(self, tables: list[FakeTable]) -> None:
        self._tables = tables

    def query_selector_all(self, selector: str):
        if selector == "table":
            return self._tables
        return []


class FakeResponse:
    def __init__(self, body: bytes, *, headers: dict[str, str] | None = None, ok: bool = True):
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
        if "embed[src]" in script or "iframe[src]" in script or "object[data]" in script:
            return self._embedded_src
        return None


def test_doc_targets_include_final_tor() -> None:
    assert "เอกสารประกวดราคา" in DOCS_TO_DOWNLOAD


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
    monkeypatch.setattr("egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads._handle_direct_or_page_download",
        lambda page, btn, doc_name: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_downloads._download_documents_from_current_view",
        lambda page, include_label: [
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


def test_save_from_new_tab_uses_request_for_blob_viewer(monkeypatch) -> None:
    viewer_page = FakeViewerPage(
        url="blob:https://process5.gprocurement.go.th/example-blob",
        embedded_src="https://process5.gprocurement.go.th/egp-download/final-tor.zip",
        response=FakeResponse(
            b"PK\x03\x04zip-bytes",
            headers={"content-type": "application/zip"},
        ),
    )

    monkeypatch.setattr("egp_worker.browser_downloads._sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "egp_worker.browser_downloads.run_with_toast_recovery",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("no download event")),
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
