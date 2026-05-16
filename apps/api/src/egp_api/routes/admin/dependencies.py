"""Shared admin route request helpers."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import Request, status
from fastapi.responses import RedirectResponse

from egp_api.services.admin_service import AdminService
from egp_api.services.audit_service import AuditService
from egp_api.services.auth_service import AuthService
from egp_api.services.storage_settings_service import StorageSettingsService
from egp_api.services.support_service import SupportService


def admin_service_from_request(request: Request) -> AdminService:
    return request.app.state.admin_service


def storage_service_from_request(request: Request) -> StorageSettingsService:
    return request.app.state.storage_settings_service


def audit_service_from_request(request: Request) -> AuditService:
    return request.app.state.audit_service


def support_service_from_request(request: Request) -> SupportService:
    return request.app.state.support_service


def auth_service_from_request(request: Request) -> AuthService:
    return request.app.state.auth_service


def actor_subject_from_request(request: Request) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is not None and getattr(auth_context, "subject", None):
        return str(auth_context.subject)
    return "manual-operator"


def accepts_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


def storage_settings_redirect(
    request: Request,
    *,
    provider: str,
    outcome: str,
) -> RedirectResponse:
    web_base_url = str(getattr(request.app.state, "web_base_url", "http://localhost:3000")).rstrip(
        "/"
    )
    query = urlencode({"provider": provider, "status": outcome})
    return RedirectResponse(
        f"{web_base_url}/admin/storage?{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
