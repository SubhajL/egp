"""Document routes for the minimal Phase 1 API slice."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from egp_api.auth import resolve_request_tenant_id
from egp_api.services.document_ingest_service import DocumentIngestService
from egp_db.repositories.document_repo import (
    DocumentDiffRecord,
    DocumentRecord,
    StoreDocumentResult,
)


router = APIRouter(prefix="/v1/documents", tags=["documents"])


class DocumentIngestRequest(BaseModel):
    tenant_id: str | None = None
    project_id: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    source_label: str = ""
    source_status_text: str = ""
    source_page_text: str = ""


class DocumentResponse(BaseModel):
    id: str
    project_id: str
    file_name: str
    sha256: str
    storage_key: str
    document_type: str
    document_phase: str
    source_label: str
    source_status_text: str
    size_bytes: int
    is_current: bool
    supersedes_document_id: str | None
    created_at: str


class DocumentDiffResponse(BaseModel):
    id: str
    project_id: str
    old_document_id: str
    new_document_id: str
    diff_type: str
    summary_json: dict[str, object] | None
    created_at: str


class StoreDocumentResponse(BaseModel):
    created: bool
    document: DocumentResponse
    diff_records: list[DocumentDiffResponse]


class ListDocumentsResponse(BaseModel):
    documents: list[DocumentResponse]


class ListDocumentDiffsResponse(BaseModel):
    diffs: list[DocumentDiffResponse]


class DocumentDiffDetailResponse(BaseModel):
    diff: DocumentDiffResponse


class DocumentDownloadResponse(BaseModel):
    download_url: str


def _service_from_request(request: Request) -> DocumentIngestService:
    return request.app.state.document_ingest_service


def _serialize_document(document: DocumentRecord) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        project_id=document.project_id,
        file_name=document.file_name,
        sha256=document.sha256,
        storage_key=document.storage_key,
        document_type=document.document_type.value,
        document_phase=document.document_phase.value,
        source_label=document.source_label,
        source_status_text=document.source_status_text,
        size_bytes=document.size_bytes,
        is_current=document.is_current,
        supersedes_document_id=document.supersedes_document_id,
        created_at=document.created_at,
    )


def _serialize_diff(diff_record: DocumentDiffRecord) -> DocumentDiffResponse:
    return DocumentDiffResponse(
        id=diff_record.id,
        project_id=diff_record.project_id,
        old_document_id=diff_record.old_document_id,
        new_document_id=diff_record.new_document_id,
        diff_type=diff_record.diff_type,
        summary_json=diff_record.summary_json,
        created_at=diff_record.created_at,
    )


def _serialize_store_result(result: StoreDocumentResult) -> StoreDocumentResponse:
    return StoreDocumentResponse(
        created=result.created,
        document=_serialize_document(result.document),
        diff_records=[_serialize_diff(diff_record) for diff_record in result.diff_records],
    )


@router.post("/ingest", response_model=StoreDocumentResponse)
def ingest_document(payload: DocumentIngestRequest, request: Request, response: Response):
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        result = service.ingest_document(
            tenant_id=resolved_tenant_id,
            project_id=payload.project_id,
            file_name=payload.file_name,
            content_base64=payload.content_base64,
            source_label=payload.source_label,
            source_status_text=payload.source_status_text,
            source_page_text=payload.source_page_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return _serialize_store_result(result)


@router.get("/projects/{project_id}", response_model=ListDocumentsResponse)
def list_documents(
    project_id: str, request: Request, tenant_id: str | None = None
) -> ListDocumentsResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    documents = service.list_documents(tenant_id=resolved_tenant_id, project_id=project_id)
    return ListDocumentsResponse(
        documents=[_serialize_document(document) for document in documents]
    )


@router.get("/projects/{project_id}/diffs", response_model=ListDocumentDiffsResponse)
def list_document_diffs(
    project_id: str, request: Request, tenant_id: str | None = None
) -> ListDocumentDiffsResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    diffs = service.list_document_diffs(
        tenant_id=resolved_tenant_id,
        project_id=project_id,
    )
    return ListDocumentDiffsResponse(
        diffs=[_serialize_diff(diff_record) for diff_record in diffs]
    )


@router.get(
    "/{document_id}/diff/{other_document_id}",
    response_model=DocumentDiffDetailResponse,
)
def get_document_diff(
    document_id: str,
    other_document_id: str,
    request: Request,
    tenant_id: str | None = None,
) -> DocumentDiffDetailResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    diff = service.get_document_diff(
        tenant_id=resolved_tenant_id,
        document_id=document_id,
        other_document_id=other_document_id,
    )
    if diff is None:
        raise HTTPException(status_code=404, detail="document diff not found")
    return DocumentDiffDetailResponse(diff=_serialize_diff(diff))


@router.get("/{document_id}/download", response_model=DocumentDownloadResponse)
def get_document_download_url(
    document_id: str,
    request: Request,
    tenant_id: str | None = None,
    expires_in: int = 300,
) -> DocumentDownloadResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        download_url = service.get_download_url(
            tenant_id=resolved_tenant_id,
            document_id=document_id,
            expires_in=expires_in,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="document not found") from exc
    return DocumentDownloadResponse(download_url=download_url)
