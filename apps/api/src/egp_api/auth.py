"""JWT auth helpers for tenant-scoped API access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from jose import JWTError, jwt

from egp_db.db_utils import normalize_uuid_string


@dataclass(frozen=True, slots=True)
class AuthContext:
    tenant_id: str
    subject: str
    claims: dict[str, Any]


def _extract_bearer_token(header_value: str | None) -> str:
    if header_value is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="invalid bearer token")
    return token.strip()


def _extract_claim_tenant_id(claims: dict[str, Any]) -> str:
    direct = claims.get("tenant_id")
    if direct:
        return normalize_uuid_string(str(direct))

    app_metadata = claims.get("app_metadata")
    if isinstance(app_metadata, dict) and app_metadata.get("tenant_id"):
        return normalize_uuid_string(str(app_metadata["tenant_id"]))

    user_metadata = claims.get("user_metadata")
    if isinstance(user_metadata, dict) and user_metadata.get("tenant_id"):
        return normalize_uuid_string(str(user_metadata["tenant_id"]))

    raise HTTPException(status_code=401, detail="tenant claim missing from token")


def authenticate_request(*, authorization_header: str | None, jwt_secret: str) -> AuthContext:
    token = _extract_bearer_token(authorization_header)
    try:
        claims = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="invalid bearer token") from exc

    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise HTTPException(status_code=401, detail="subject claim missing from token")

    return AuthContext(
        tenant_id=_extract_claim_tenant_id(claims),
        subject=subject,
        claims=claims,
    )


def resolve_request_tenant_id(request: Request, supplied_tenant_id: str | None) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is not None:
        if supplied_tenant_id is not None:
            normalized_supplied = normalize_uuid_string(supplied_tenant_id)
            if normalized_supplied != auth_context.tenant_id:
                raise HTTPException(status_code=403, detail="tenant mismatch")
        return auth_context.tenant_id

    if supplied_tenant_id is None:
        raise HTTPException(status_code=401, detail="tenant_id is required when auth is disabled")
    return normalize_uuid_string(supplied_tenant_id)


def extract_request_role(request: Request) -> str | None:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        return None
    claims = auth_context.claims
    direct = claims.get("role")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    app_metadata = claims.get("app_metadata")
    if isinstance(app_metadata, dict):
        role = app_metadata.get("role")
        if isinstance(role, str) and role.strip():
            return role.strip()

    user_metadata = claims.get("user_metadata")
    if isinstance(user_metadata, dict):
        role = user_metadata.get("role")
        if isinstance(role, str) and role.strip():
            return role.strip()

    return None


def require_admin_role(request: Request) -> None:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        return
    role = extract_request_role(request)
    if role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="admin role required")
