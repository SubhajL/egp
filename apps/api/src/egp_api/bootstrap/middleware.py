"""HTTP middleware, exception handlers, and router registration."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from egp_api.auth import authenticate_request_async
from egp_api.services.session_auth_runtime import SessionAuthenticationUnavailableError
from egp_api.routes.admin import router as admin_router
from egp_api.routes.auth import router as auth_router
from egp_api.routes.billing import router as billing_router
from egp_api.routes.crawler_agent import (
    internal_router as crawler_agent_internal_router,
)
from egp_api.routes.crawler_agent import router as crawler_agent_router
from egp_api.routes.crawler_runtime import (
    internal_router as crawler_runtime_internal_router,
)
from egp_api.routes.crawler_runtime import router as crawler_runtime_router
from egp_api.routes.dashboard import router as dashboard_router
from egp_api.routes.documents import router as documents_router
from egp_api.routes.exports import router as exports_router
from egp_api.routes.line_integration import router as line_integration_router
from egp_api.routes.project_ingest import router as project_ingest_router
from egp_api.routes.projects import router as projects_router
from egp_api.routes.rules import router as rules_router
from egp_api.routes.runs import router as runs_router
from egp_api.routes.webhooks import router as webhooks_router

VALIDATION_CODE_OVERRIDES: dict[tuple[str, str, str], str] = {
    ("/v1/auth/register", "password", "string_too_short"): "validation_password_too_short",
    ("/v1/auth/register", "email", "missing"): "validation_email_required",
    ("/v1/auth/register", "password", "missing"): "validation_password_required",
    ("/v1/auth/register", "company_name", "missing"): "validation_company_name_required",
    ("/v1/rules/profiles", "name", "missing"): "validation_profile_name_required",
    ("/v1/rules/profiles", "keywords", "missing"): "validation_keywords_required",
}
_logger = logging.getLogger(__name__)


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class ReadinessDatabaseCheckResponse(BaseModel):
    status: Literal["ok", "error", "unknown"]


class ReadinessMigrationCheckResponse(ReadinessDatabaseCheckResponse):
    pending_count: int | None
    unexpected_count: int | None


class ReadinessChecksResponse(BaseModel):
    database: ReadinessDatabaseCheckResponse
    migrations: ReadinessMigrationCheckResponse


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    reason: str | None = None
    checks: ReadinessChecksResponse


def _validation_error_code(exc: RequestValidationError, *, path: str) -> str | None:
    for error in exc.errors():
        loc = error.get("loc")
        if not isinstance(loc, (list, tuple)) or len(loc) < 2:
            continue
        if loc[0] != "body":
            continue
        field = str(loc[-1])
        code = VALIDATION_CODE_OVERRIDES.get((path, field, str(error.get("type") or "")))
        if code is not None:
            return code
    return None


def configure_http_pipeline(
    *,
    app: FastAPI,
    resolved_web_allowed_origins: list[str],
    resolved_web_allow_origin_regex: str | None,
) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc: RequestValidationError):
        content: dict[str, object] = {"detail": exc.errors()}
        code = _validation_error_code(exc, path=request.url.path)
        if code is not None:
            content["code"] = code
        return JSONResponse(status_code=422, content=content)

    def cors_headers_for_origin(origin: str | None) -> dict[str, str]:
        normalized_origin = str(origin or "").strip().rstrip("/")
        if not normalized_origin:
            return {}
        if normalized_origin in resolved_web_allowed_origins or (
            resolved_web_allow_origin_regex
            and re.fullmatch(resolved_web_allow_origin_regex, normalized_origin)
        ):
            return {
                "Access-Control-Allow-Origin": normalized_origin,
                "Access-Control-Allow-Credentials": "true",
                "Vary": "Origin",
            }
        return {}

    if resolved_web_allowed_origins or resolved_web_allow_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_web_allowed_origins,
            allow_origin_regex=resolved_web_allow_origin_regex,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Content-Disposition"],
        )

    _register_auth_middleware(app=app, cors_headers_for_origin=cors_headers_for_origin)
    _register_routes(app)


def _register_auth_middleware(
    *,
    app: FastAPI,
    cors_headers_for_origin: Callable[[str | None], dict[str, str]],
) -> None:
    @app.middleware("http")
    async def auth_middleware(request, call_next):
        if request.method == "OPTIONS":
            request.state.auth_context = None
            headers = cors_headers_for_origin(request.headers.get("origin"))
            if headers:
                headers.update(
                    {
                        "Access-Control-Allow-Methods": "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT",
                        "Access-Control-Max-Age": "600",
                    }
                )
                requested_headers = request.headers.get("access-control-request-headers")
                if requested_headers:
                    headers["Access-Control-Allow-Headers"] = requested_headers
            return Response(status_code=200, headers=headers)
        if (
            request.url.path
            in {
                "/health",
                "/live",
                "/ready",
                "/metrics",
                "/openapi.json",
                "/docs",
                "/docs/oauth2-redirect",
                "/redoc",
                "/v1/auth/login",
                "/v1/auth/logout",
                "/v1/auth/register",
                "/v1/auth/password/forgot",
                "/v1/auth/password/reset",
                "/v1/auth/invite/accept",
                "/v1/auth/email/verify",
            }
            or request.url.path.startswith("/internal/worker/")
            or (
                request.url.path.startswith("/v1/billing/payment-requests/")
                and request.url.path.endswith("/callbacks")
            )
            or request.url.path == "/v1/billing/providers/opn/webhooks"
            or request.url.path == "/v1/billing/providers/stripe/webhooks"
            # LINE delivers webhooks unauthenticated; the route enforces the
            # mandatory X-Line-Signature HMAC check instead of JWT auth.
            or request.url.path == "/v1/integrations/line/webhook"
        ):
            request.state.auth_context = None
            return await call_next(request)

        if not app.state.auth_required:
            request.state.auth_context = None
            return await call_next(request)

        try:
            authorization_values = request.headers.getlist("authorization")
            if len(authorization_values) > 1:
                raise HTTPException(status_code=401, detail="invalid bearer token")
            request.state.auth_context = await authenticate_request_async(
                authorization_header=(authorization_values[0] if authorization_values else None),
                session_token=request.cookies.get(app.state.session_cookie_name),
                jwt_secret=app.state.jwt_secret,
                jwt_validation_policy=app.state.jwt_validation_policy,
                session_authenticator=app.state.session_auth_runtime.authenticate,
            )
        except SessionAuthenticationUnavailableError:
            return JSONResponse(
                status_code=503,
                content={"detail": "session authentication temporarily unavailable"},
                headers=cors_headers_for_origin(request.headers.get("origin")),
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "invalid bearer token")
            return JSONResponse(
                status_code=status_code,
                content={"detail": detail},
                headers=cors_headers_for_origin(request.headers.get("origin")),
            )
        response = await call_next(request)
        cors_headers = cors_headers_for_origin(request.headers.get("origin"))
        for key, value in cors_headers.items():
            response.headers.setdefault(key, value)
        return response


def _register_routes(app: FastAPI) -> None:
    @app.get("/health", response_model=LivenessResponse)
    def health() -> LivenessResponse:
        return LivenessResponse(status="ok")

    @app.get("/live", response_model=LivenessResponse)
    def live() -> LivenessResponse:
        return LivenessResponse(status="ok")

    @app.get(
        "/ready",
        response_model=ReadinessResponse,
        responses={503: {"model": ReadinessResponse}},
    )
    def ready(response: Response) -> ReadinessResponse:
        snapshot = app.state.readiness_service.build_readiness_snapshot()
        if not snapshot.is_ready:
            _logger.warning(
                "readiness check failed",
                extra={
                    "readiness_reason": snapshot.reason,
                    "pending_migration_count": snapshot.pending_count,
                },
            )
        response.status_code = 200 if snapshot.is_ready else 503
        return ReadinessResponse.model_validate(snapshot.to_payload())

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(billing_router)
    app.include_router(crawler_agent_internal_router)
    app.include_router(crawler_agent_router)
    app.include_router(crawler_runtime_internal_router)
    app.include_router(crawler_runtime_router)
    app.include_router(dashboard_router)
    app.include_router(documents_router)
    app.include_router(exports_router)
    app.include_router(line_integration_router)
    app.include_router(project_ingest_router)
    app.include_router(projects_router)
    app.include_router(rules_router)
    app.include_router(runs_router)
    app.include_router(webhooks_router)
