"""JWT auth helpers for tenant-scoped API access."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
import jwt

from egp_db.db_utils import normalize_uuid_string


@dataclass(frozen=True, slots=True)
class AuthContext:
    tenant_id: str
    subject: str
    claims: dict[str, Any]
    user_id: str | None = None
    email: str | None = None
    full_name: str | None = None
    role: str | None = None
    status: str | None = None
    email_verified_at: str | None = None
    mfa_enabled: bool = False
    tenant_slug: str | None = None
    tenant_name: str | None = None
    tenant_plan_code: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationClaims:
    tenant_id: str
    role: str | None


def _extract_bearer_token(header_value: str | None) -> str:
    if header_value is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="invalid bearer token")
    return token.strip()


def extract_authorization_claims(claims: dict[str, Any]) -> AuthorizationClaims:
    """Extract only direct EGP-controlled tenant and role claims."""

    direct = claims.get("tenant_id")
    if not direct:
        raise HTTPException(status_code=401, detail="tenant claim missing from token")
    return AuthorizationClaims(
        tenant_id=normalize_uuid_string(str(direct)),
        role=_normalize_optional_claim(claims.get("role")),
    )


def authenticate_bearer_request(
    *, authorization_header: str | None, jwt_secret: str
) -> AuthContext:
    token = _extract_bearer_token(authorization_header)
    try:
        claims = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid bearer token") from exc

    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise HTTPException(status_code=401, detail="subject claim missing from token")
    authorization_claims = extract_authorization_claims(claims)

    return AuthContext(
        tenant_id=authorization_claims.tenant_id,
        subject=subject,
        claims=claims,
        user_id=_normalize_optional_claim(claims.get("user_id")),
        email=_normalize_optional_claim(claims.get("email")),
        full_name=_normalize_optional_claim(claims.get("full_name")),
        role=authorization_claims.role,
        email_verified_at=_normalize_optional_claim(claims.get("email_verified_at")),
        mfa_enabled=_normalize_bool_claim(claims.get("mfa_enabled")),
    )


def authenticate_request(
    *,
    authorization_header: str | None,
    session_token: str | None,
    jwt_secret: str | None,
    session_authenticator: Callable[[str], AuthContext | None] | None = None,
) -> AuthContext:
    if authorization_header is not None:
        if not jwt_secret:
            raise HTTPException(status_code=503, detail="server auth not configured")
        return authenticate_bearer_request(
            authorization_header=authorization_header,
            jwt_secret=jwt_secret,
        )
    if session_token is not None and session_authenticator is not None:
        context = session_authenticator(session_token)
        if context is None:
            raise HTTPException(status_code=401, detail="invalid session")
        return context
    raise HTTPException(status_code=401, detail="missing authentication")


def _normalize_optional_claim(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_bool_claim(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def resolve_request_tenant_id(
    request: Request,
    supplied_tenant_id: str | None,
    *,
    allow_support_override: bool = False,
) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is not None:
        if supplied_tenant_id is not None:
            normalized_supplied = normalize_uuid_string(supplied_tenant_id)
            if normalized_supplied != auth_context.tenant_id:
                if allow_support_override and request_has_support_role(request):
                    return normalized_supplied
                raise HTTPException(status_code=403, detail="tenant mismatch")
            return normalized_supplied
        return auth_context.tenant_id

    if supplied_tenant_id is None:
        raise HTTPException(status_code=401, detail="tenant_id is required when auth is disabled")
    return normalize_uuid_string(supplied_tenant_id)


def extract_request_role(request: Request) -> str | None:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        return None
    return auth_context.role


def request_has_support_role(request: Request) -> bool:
    return extract_request_role(request) == "support"


def require_admin_role(request: Request) -> None:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        return
    role = extract_request_role(request)
    if role not in {"owner", "admin", "support"}:
        raise HTTPException(status_code=403, detail="admin role required")


def require_run_operator_role(request: Request) -> None:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        return
    role = extract_request_role(request)
    if role not in {"owner", "admin", "support", "analyst"}:
        raise HTTPException(status_code=403, detail="run operator role required")


def require_support_role(request: Request) -> None:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        return
    if not request_has_support_role(request):
        raise HTTPException(status_code=403, detail="support role required")


def require_internal_worker_token(request: Request) -> None:
    configured_token = getattr(request.app.state, "internal_worker_token", None)
    if not configured_token:
        raise HTTPException(status_code=503, detail="internal worker auth not configured")
    provided_token = str(request.headers.get("x-egp-worker-token") or "").strip()
    if not provided_token:
        raise HTTPException(status_code=401, detail="missing internal worker token")
    if not hmac.compare_digest(provided_token, configured_token):
        raise HTTPException(status_code=403, detail="invalid internal worker token")
