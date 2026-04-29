"""Document routes for the minimal Phase 1 API slice."""

from __future__ import annotations

import io
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from egp_api.auth import resolve_request_tenant_id
from egp_api.services.entitlement_service import EntitlementError
from egp_api.services.document_ingest_service import DocumentIngestService
from egp_db.repositories.document_repo import (
    DocumentArtifactReadError,
    DocumentDiffRecord,
    DocumentRecord,
    DocumentReviewDetail,
    DocumentReviewEventRecord,
    DocumentReviewPage,
    StoreDocumentResult,
)
from egp_shared_types.enums import DocumentReviewAction, DocumentReviewStatus


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


class DocumentReviewEventResponse(BaseModel):
    id: str
    review_id: str
    document_diff_id: str
    event_type: str
    actor_subject: str | None
    note: str | None
    from_status: str | None
    to_status: str | None
    created_at: str


class DocumentReviewResponse(BaseModel):
    id: str
    project_id: str
    document_diff_id: str
    status: str
    resolved_at: str | None
    created_at: str
    updated_at: str
    diff: DocumentDiffResponse
    events: list[DocumentReviewEventResponse]


class ListDocumentReviewsResponse(BaseModel):
    reviews: list[DocumentReviewResponse]
    total: int
    limit: int
    offset: int


class ApplyDocumentReviewActionRequest(BaseModel):
    tenant_id: str | None = None
    action: DocumentReviewAction
    note: str | None = None


class DocumentReviewActionResponse(BaseModel):
    review: DocumentReviewResponse


def _service_from_request(request: Request) -> DocumentIngestService:
    return request.app.state.document_ingest_service


def _actor_subject_from_request(request: Request) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is not None and getattr(auth_context, "subject", None):
        return str(auth_context.subject)
    return "manual-operator"


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


def _serialize_review_event(event: DocumentReviewEventRecord) -> DocumentReviewEventResponse:
    return DocumentReviewEventResponse(
        id=event.id,
        review_id=event.review_id,
        document_diff_id=event.document_diff_id,
        event_type=event.event_type.value,
        actor_subject=event.actor_subject,
        note=event.note,
        from_status=event.from_status.value if event.from_status is not None else None,
        to_status=event.to_status.value if event.to_status is not None else None,
        created_at=event.created_at,
    )


def _serialize_review(review: DocumentReviewDetail) -> DocumentReviewResponse:
    return DocumentReviewResponse(
        id=review.id,
        project_id=review.project_id,
        document_diff_id=review.document_diff_id,
        status=review.status.value,
        resolved_at=review.resolved_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
        diff=_serialize_diff(review.diff),
        events=[_serialize_review_event(event) for event in review.events],
    )


def _serialize_review_page(page: DocumentReviewPage) -> ListDocumentReviewsResponse:
    return ListDocumentReviewsResponse(
        reviews=[_serialize_review(review) for review in page.reviews],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _build_content_disposition(file_name: str) -> str:
    normalized_file_name = str(file_name or "").strip() or "document.bin"
    safe_ascii = normalized_file_name.encode("ascii", errors="ignore").decode("ascii").strip()
    safe_ascii = safe_ascii.replace("\\", "_").replace('"', "_")
    safe_ascii = " ".join(safe_ascii.split()).strip().rstrip(".")
    if not safe_ascii or safe_ascii.startswith("."):
        suffix = "".join(Path(normalized_file_name).suffixes)
        safe_suffix = suffix.encode("ascii", errors="ignore").decode("ascii").strip()
        safe_suffix = safe_suffix.replace("\\", "_").replace('"', "_")
        if safe_suffix and not safe_suffix.startswith("."):
            safe_suffix = f".{safe_suffix}"
        safe_ascii = f"document{safe_suffix or '.bin'}"
    return f"attachment; filename=\"{safe_ascii}\"; filename*=UTF-8''{quote(normalized_file_name)}"


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
            actor_subject=_actor_subject_from_request(request),
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
    return ListDocumentDiffsResponse(diffs=[_serialize_diff(diff_record) for diff_record in diffs])


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


@router.get("/projects/{project_id}/reviews", response_model=ListDocumentReviewsResponse)
def list_document_reviews(
    project_id: str,
    request: Request,
    tenant_id: str | None = None,
    status_filter: DocumentReviewStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ListDocumentReviewsResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        page = service.list_document_reviews(
            tenant_id=resolved_tenant_id,
            project_id=project_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize_review_page(page)


@router.post(
    "/reviews/{review_id}/actions",
    response_model=DocumentReviewActionResponse,
)
def apply_document_review_action(
    review_id: str,
    payload: ApplyDocumentReviewActionRequest,
    request: Request,
) -> DocumentReviewActionResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        review = service.apply_document_review_action(
            tenant_id=resolved_tenant_id,
            review_id=review_id,
            action=payload.action,
            actor_subject=_actor_subject_from_request(request),
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="document review not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DocumentReviewActionResponse(review=_serialize_review(review))


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    request: Request,
    tenant_id: str | None = None,
    expires_in: int = 300,
) -> StreamingResponse:
    del expires_in
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        document = service.download_document(
            tenant_id=resolved_tenant_id,
            document_id=document_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="document not found") from exc
    except EntitlementError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DocumentArtifactReadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(document.file_bytes),
        media_type=document.content_type,
        headers={"Content-Disposition": _build_content_disposition(document.document.file_name)},
    )
