"""Authentication routes for password login, lifecycle flows, and cookie sessions."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from egp_api.services.auth_service import (
    AuthService,
    CurrentSessionView,
    WorkspaceSlugRequiredError,
)


router = APIRouter(tags=["auth"])


AUTH_ERROR_CODES = {
    "invalid credentials": "invalid_credentials",
    "account is not active": "account_not_active",
    "mfa code required": "mfa_code_required",
    "invalid mfa code": "invalid_mfa_code",
    "invalid or expired invite token": "invalid_invite_token",
    "invalid or expired password reset token": "invalid_password_reset_token",
    "invalid or expired email verification token": "invalid_email_verification_token",
    "email delivery is not configured": "email_delivery_not_configured",
}


class LoginRequest(BaseModel):
    tenant_slug: str | None = None
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)
    mfa_code: str | None = None


class TokenRequest(BaseModel):
    token: str = Field(min_length=1)


class AcceptInviteRequest(TokenRequest):
    password: str = Field(min_length=1)


class ForgotPasswordRequest(BaseModel):
    tenant_slug: str = Field(min_length=1)
    email: str = Field(min_length=1)


class ResetPasswordRequest(TokenRequest):
    password: str = Field(min_length=1)


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=1)


class AuthenticatedUserResponse(BaseModel):
    id: str | None
    subject: str
    email: str | None
    full_name: str | None
    role: str | None
    status: str | None
    email_verified: bool
    email_verified_at: str | None
    mfa_enabled: bool


class AuthTenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan_code: str
    is_active: bool
    created_at: str
    updated_at: str


class CurrentSessionResponse(BaseModel):
    user: AuthenticatedUserResponse
    tenant: AuthTenantResponse


class ActionStatusResponse(BaseModel):
    status: str


class RegisterRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12)


class EmailVerificationResponse(BaseModel):
    email_verified: bool


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaStatusResponse(BaseModel):
    mfa_enabled: bool


def _service_from_request(request: Request) -> AuthService:
    return request.app.state.auth_service


def _json_error(*, status_code: int, detail: str, code: str | None = None) -> JSONResponse:
    content: dict[str, str] = {"detail": detail}
    if code:
        content["code"] = code
    return JSONResponse(status_code=status_code, content=content)


def _serialize_current(view: CurrentSessionView) -> CurrentSessionResponse:
    return CurrentSessionResponse(
        user=AuthenticatedUserResponse(**asdict(view.user)),
        tenant=AuthTenantResponse(**asdict(view.tenant)),
    )


def _require_auth_context(request: Request):
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return auth_context


@router.post("/v1/auth/login", response_model=CurrentSessionResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> CurrentSessionResponse:
    service = _service_from_request(request)
    try:
        result = service.login(
            tenant_slug=payload.tenant_slug,
            email=payload.email,
            password=payload.password,
            mfa_code=payload.mfa_code,
        )
    except WorkspaceSlugRequiredError:
        return _json_error(
            status_code=409,
            detail="workspace slug required",
            code="workspace_slug_required",
        )
    except PermissionError as exc:
        detail = str(exc) or "invalid credentials"
        status_code = 403 if "active" in detail else 401
        return _json_error(
            status_code=status_code,
            detail=detail,
            code=AUTH_ERROR_CODES.get(detail),
        )

    response.set_cookie(
        key=request.app.state.session_cookie_name,
        value=result.session_token,
        max_age=request.app.state.session_cookie_max_age_seconds,
        httponly=True,
        secure=request.app.state.session_cookie_secure,
        samesite=request.app.state.session_cookie_samesite,
        path="/",
    )
    return _serialize_current(result.current)


@router.post("/v1/auth/register", response_model=CurrentSessionResponse, status_code=200)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
) -> CurrentSessionResponse:
    service = _service_from_request(request)
    try:
        result = service.register(
            company_name=payload.company_name,
            email=payload.email,
            password=payload.password,
        )
    except ValueError as exc:
        detail = str(exc) or "registration failed"
        if "already registered" in detail:
            return _json_error(
                status_code=409,
                detail="account already exists for this email; please sign in",
                code="account_already_exists",
            )
        return _json_error(status_code=400, detail=detail, code="registration_failed")
    response.set_cookie(
        key=request.app.state.session_cookie_name,
        value=result.session_token,
        max_age=request.app.state.session_cookie_max_age_seconds,
        httponly=True,
        secure=request.app.state.session_cookie_secure,
        samesite=request.app.state.session_cookie_samesite,
        path="/",
    )
    return _serialize_current(result.current)


@router.post(
    "/v1/auth/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ActionStatusResponse,
)
def forgot_password(payload: ForgotPasswordRequest, request: Request) -> ActionStatusResponse:
    service = _service_from_request(request)
    service.request_password_reset(tenant_slug=payload.tenant_slug, email=payload.email)
    return ActionStatusResponse(status="accepted")


@router.post("/v1/auth/password/reset", response_model=ActionStatusResponse)
def reset_password(payload: ResetPasswordRequest, request: Request) -> ActionStatusResponse:
    service = _service_from_request(request)
    try:
        service.reset_password(token=payload.token, password=payload.password)
    except PermissionError as exc:
        detail = str(exc) or "invalid token"
        return _json_error(status_code=400, detail=detail, code=AUTH_ERROR_CODES.get(detail))
    return ActionStatusResponse(status="password_reset")


@router.post("/v1/auth/invite/accept", response_model=CurrentSessionResponse)
def accept_invite(
    payload: AcceptInviteRequest,
    request: Request,
    response: Response,
) -> CurrentSessionResponse:
    service = _service_from_request(request)
    try:
        result = service.accept_invite(token=payload.token, password=payload.password)
    except PermissionError as exc:
        detail = str(exc) or "invalid invite token"
        return _json_error(status_code=400, detail=detail, code=AUTH_ERROR_CODES.get(detail))
    response.set_cookie(
        key=request.app.state.session_cookie_name,
        value=result.session_token,
        max_age=request.app.state.session_cookie_max_age_seconds,
        httponly=True,
        secure=request.app.state.session_cookie_secure,
        samesite=request.app.state.session_cookie_samesite,
        path="/",
    )
    return _serialize_current(result.current)


@router.post(
    "/v1/auth/email/verification/send",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ActionStatusResponse,
)
def send_email_verification(request: Request) -> ActionStatusResponse:
    service = _service_from_request(request)
    try:
        service.send_email_verification(_require_auth_context(request))
    except RuntimeError as exc:
        detail = str(exc) or "email delivery is not configured"
        return _json_error(status_code=503, detail=detail, code=AUTH_ERROR_CODES.get(detail))
    return ActionStatusResponse(status="accepted")


@router.post("/v1/auth/email/verify", response_model=EmailVerificationResponse)
def verify_email(payload: TokenRequest, request: Request) -> EmailVerificationResponse:
    service = _service_from_request(request)
    try:
        email_verified = service.verify_email(token=payload.token)
    except PermissionError as exc:
        detail = str(exc) or "invalid token"
        return _json_error(status_code=400, detail=detail, code=AUTH_ERROR_CODES.get(detail))
    return EmailVerificationResponse(email_verified=email_verified)


@router.post("/v1/auth/mfa/setup", response_model=MfaSetupResponse)
def setup_mfa(request: Request) -> MfaSetupResponse:
    service = _service_from_request(request)
    secret, otpauth_uri = service.setup_mfa(_require_auth_context(request))
    return MfaSetupResponse(secret=secret, otpauth_uri=otpauth_uri)


@router.post("/v1/auth/mfa/enable", response_model=MfaStatusResponse)
def enable_mfa(payload: MfaCodeRequest, request: Request) -> MfaStatusResponse:
    service = _service_from_request(request)
    try:
        enabled = service.enable_mfa(_require_auth_context(request), code=payload.code)
    except PermissionError as exc:
        detail = str(exc) or "invalid mfa code"
        return _json_error(status_code=400, detail=detail, code=AUTH_ERROR_CODES.get(detail))
    return MfaStatusResponse(mfa_enabled=enabled)


@router.post("/v1/auth/mfa/disable", response_model=MfaStatusResponse)
def disable_mfa(payload: MfaCodeRequest, request: Request) -> MfaStatusResponse:
    service = _service_from_request(request)
    try:
        enabled = service.disable_mfa(_require_auth_context(request), code=payload.code)
    except PermissionError as exc:
        detail = str(exc) or "invalid mfa code"
        return _json_error(status_code=400, detail=detail, code=AUTH_ERROR_CODES.get(detail))
    return MfaStatusResponse(mfa_enabled=enabled)


@router.post("/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    service = _service_from_request(request)
    session_token = request.cookies.get(request.app.state.session_cookie_name)
    service.revoke_session(session_token=session_token)
    response.delete_cookie(
        key=request.app.state.session_cookie_name,
        path="/",
        httponly=True,
        secure=request.app.state.session_cookie_secure,
        samesite=request.app.state.session_cookie_samesite,
    )


@router.get("/v1/me", response_model=CurrentSessionResponse)
def me(request: Request) -> CurrentSessionResponse:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        raise HTTPException(status_code=401, detail="authentication required")
    service = _service_from_request(request)
    try:
        current = service.describe_current(auth_context)
    except KeyError as exc:
        raise HTTPException(status_code=401, detail="tenant not found") from exc
    return _serialize_current(current)
