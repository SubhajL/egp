"""Admin route package."""

from __future__ import annotations

from fastapi import APIRouter

from egp_api.routes.admin import audit, overview, settings, storage, support


router = APIRouter(tags=["admin"])
router.include_router(overview.router, prefix="/v1/admin")
router.include_router(audit.router, prefix="/v1/admin")
router.include_router(support.router, prefix="/v1/admin")
router.include_router(settings.router, prefix="/v1/admin")
router.include_router(storage.router, prefix="/v1/admin")
