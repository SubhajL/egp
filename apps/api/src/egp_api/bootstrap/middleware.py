"""HTTP middleware, exception handlers, and router registration."""

from __future__ import annotations

import re
from collections.abc import Callable

from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from egp_api.auth import authenticate_request
from egp_api.routes.admin import router as admin_router
from egp_api.routes.auth import router as auth_router
from egp_api.routes.billing import router as billing_router
from egp_api.routes.dashboard import router as dashboard_router
from egp_api.routes.documents import router as documents_router
from egp_api.routes.exports import router as exports_router
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
                "/internal/worker/projects/discover",
                "/internal/worker/projects/close-check",
            }
            or (
                request.url.path.startswith("/v1/billing/payment-requests/")
                and request.url.path.endswith("/callbacks")
            )
            or request.url.path == "/v1/billing/providers/opn/webhooks"
        ):
            request.state.auth_context = None
            return await call_next(request)

        if not app.state.auth_required:
            request.state.auth_context = None
            return await call_next(request)

        try:
            request.state.auth_context = authenticate_request(
                authorization_header=request.headers.get("authorization"),
                session_token=request.cookies.get(app.state.session_cookie_name),
                jwt_secret=app.state.jwt_secret,
                session_authenticator=app.state.auth_service.authenticate_session,
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
    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(billing_router)
    app.include_router(dashboard_router)
    app.include_router(documents_router)
    app.include_router(exports_router)
    app.include_router(project_ingest_router)
    app.include_router(projects_router)
    app.include_router(rules_router)
    app.include_router(runs_router)
    app.include_router(webhooks_router)
