"""JWT auth helpers for tenant-scoped API access."""

from __future__ import annotations

import base64
import hmac
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
import jwt

from egp_db.db_utils import normalize_uuid_string


AUTHENTICATED_ROLES = frozenset({"owner", "admin", "support", "analyst", "viewer"})
JWT_ALGORITHMS = ("HS256",)
_BASE64URL_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class JwtValidationPolicy:
    issuer: str
    audience: str
    clock_skew_seconds: int

    def __post_init__(self) -> None:
        if not self.issuer or self.issuer != self.issuer.strip():
            raise ValueError("JWT issuer must be a nonblank canonical string")
        if not self.audience or self.audience != self.audience.strip():
            raise ValueError("JWT audience must be a nonblank canonical string")
        if (
            isinstance(self.clock_skew_seconds, bool)
            or not isinstance(self.clock_skew_seconds, int)
            or not 0 <= self.clock_skew_seconds <= 120
        ):
            raise ValueError("JWT clock skew must be an integer between 0 and 120")


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


class _DuplicateJsonMember(ValueError):
    pass


def _reject_duplicate_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonMember(key)
        result[key] = value
    return result


def _decode_jose_object(segment: str) -> dict[str, object]:
    if not _BASE64URL_SEGMENT.fullmatch(segment):
        raise ValueError("invalid JOSE segment encoding")
    padded = f"{segment}{'=' * (-len(segment) % 4)}"
    raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_members,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    if not isinstance(value, dict):
        raise ValueError("JOSE value must be an object")
    return value


def _preflight_compact_jwt(token: str, policy: JwtValidationPolicy) -> None:
    segments = token.split(".")
    if len(segments) != 3 or any(not segment for segment in segments):
        raise ValueError("invalid compact JWT")
    if any(_BASE64URL_SEGMENT.fullmatch(segment) is None for segment in segments):
        raise ValueError("invalid JOSE segment encoding")
    header = _decode_jose_object(segments[0])
    _decode_jose_object(segments[1])
    if header.get("alg") not in JWT_ALGORITHMS:
        raise ValueError("unsupported JWT algorithm")


def _required_string_claim(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"invalid {name} claim")
    return value


def _optional_string_claim(claims: dict[str, Any], name: str) -> str | None:
    if name not in claims:
        return None
    value = claims[name]
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"invalid {name} claim")
    return value


def _optional_bool_claim(claims: dict[str, Any], name: str) -> bool:
    if name not in claims:
        return False
    value = claims[name]
    if not isinstance(value, bool):
        raise ValueError(f"invalid {name} claim")
    return value


def _integer_timestamp_claim(
    claims: dict[str, Any], name: str, *, required: bool
) -> int | None:
    if name not in claims:
        if required:
            raise ValueError(f"missing {name} claim")
        return None
    value = claims[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid {name} claim")
    return value


def extract_authorization_claims(claims: dict[str, Any]) -> AuthorizationClaims:
    """Extract only direct EGP-controlled tenant and role claims."""

    direct = _required_string_claim(claims, "tenant_id")
    role = _optional_string_claim(claims, "role")
    return AuthorizationClaims(
        tenant_id=normalize_uuid_string(direct),
        role=role,
    )


def authenticate_bearer_request(
    *,
    authorization_header: str | None,
    jwt_secret: str,
    validation_policy: JwtValidationPolicy,
) -> AuthContext:
    try:
        token = _extract_bearer_token(authorization_header)
        _preflight_compact_jwt(token, validation_policy)
        claims = jwt.decode(
            token,
            jwt_secret,
            algorithms=list(JWT_ALGORITHMS),
            issuer=validation_policy.issuer,
            audience=validation_policy.audience,
            leeway=validation_policy.clock_skew_seconds,
            options={
                "require": ["iss", "aud", "exp", "sub", "tenant_id"],
                "strict_aud": True,
            },
        )
        _required_string_claim(claims, "iss")
        _required_string_claim(claims, "aud")
        subject = _required_string_claim(claims, "sub")
        _integer_timestamp_claim(claims, "exp", required=True)
        _integer_timestamp_claim(claims, "iat", required=False)
        _integer_timestamp_claim(claims, "nbf", required=False)
        authorization_claims = extract_authorization_claims(claims)
        context = AuthContext(
            tenant_id=authorization_claims.tenant_id,
            subject=subject,
            claims=claims,
            user_id=_optional_string_claim(claims, "user_id"),
            email=_optional_string_claim(claims, "email"),
            full_name=_optional_string_claim(claims, "full_name"),
            role=authorization_claims.role,
            email_verified_at=_optional_string_claim(claims, "email_verified_at"),
            mfa_enabled=_optional_bool_claim(claims, "mfa_enabled"),
        )
    except (HTTPException, jwt.PyJWTError, ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(status_code=401, detail="invalid bearer token") from exc
    return context


def authenticate_request(
    *,
    authorization_header: str | None,
    session_token: str | None,
    jwt_secret: str | None,
    jwt_validation_policy: JwtValidationPolicy | None,
    session_authenticator: Callable[[str], AuthContext | None] | None = None,
) -> AuthContext:
    if authorization_header is not None:
        if not jwt_secret or jwt_validation_policy is None:
            raise HTTPException(status_code=503, detail="server auth not configured")
        return authenticate_bearer_request(
            authorization_header=authorization_header,
            jwt_secret=jwt_secret,
            validation_policy=jwt_validation_policy,
        )
    if session_token is not None and session_authenticator is not None:
        context = session_authenticator(session_token)
        if context is None:
            raise HTTPException(status_code=401, detail="invalid session")
        return context
    raise HTTPException(status_code=401, detail="missing authentication")


async def authenticate_request_async(
    *,
    authorization_header: str | None,
    session_token: str | None,
    jwt_secret: str | None,
    jwt_validation_policy: JwtValidationPolicy | None,
    session_authenticator: Callable[[str], Awaitable[AuthContext | None]],
) -> AuthContext:
    if authorization_header is not None:
        if not jwt_secret or jwt_validation_policy is None:
            raise HTTPException(status_code=503, detail="server auth not configured")
        return authenticate_bearer_request(
            authorization_header=authorization_header,
            jwt_secret=jwt_secret,
            validation_policy=jwt_validation_policy,
        )
    if session_token is not None:
        context = await session_authenticator(session_token)
        if context is None:
            raise HTTPException(status_code=401, detail="invalid session")
        return context
    raise HTTPException(status_code=401, detail="missing authentication")


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


def require_authenticated_role(request: Request) -> None:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        return
    if extract_request_role(request) not in AUTHENTICATED_ROLES:
        raise HTTPException(status_code=403, detail="authenticated role required")


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
