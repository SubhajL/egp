"""Admin route package registration tests."""

from __future__ import annotations

from importlib import import_module


EXPECTED_ADMIN_ROUTE_KEYS = {
    ("GET", "/v1/admin"),
    ("GET", "/v1/admin/audit-log"),
    ("GET", "/v1/admin/support/tenants"),
    ("GET", "/v1/admin/support/tenants/{tenant_id}/summary"),
    ("POST", "/v1/admin/users"),
    ("PATCH", "/v1/admin/users/{user_id}"),
    ("POST", "/v1/admin/users/{user_id}/invite"),
    ("PUT", "/v1/admin/users/{user_id}/notification-preferences"),
    ("PATCH", "/v1/admin/settings"),
    ("GET", "/v1/admin/storage"),
    ("PATCH", "/v1/admin/storage"),
    ("POST", "/v1/admin/storage/connect"),
    ("POST", "/v1/admin/storage/google-drive/oauth/start"),
    ("GET", "/v1/admin/storage/google-drive/oauth/callback"),
    ("POST", "/v1/admin/storage/google-drive/folder"),
    ("POST", "/v1/admin/storage/onedrive/oauth/start"),
    ("GET", "/v1/admin/storage/onedrive/oauth/callback"),
    ("POST", "/v1/admin/storage/onedrive/folder"),
    ("POST", "/v1/admin/storage/disconnect"),
    ("POST", "/v1/admin/storage/test-write"),
}


def test_admin_route_package_exposes_subdomain_modules() -> None:
    for module_name in [
        "egp_api.routes.admin.audit",
        "egp_api.routes.admin.overview",
        "egp_api.routes.admin.settings",
        "egp_api.routes.admin.storage",
        "egp_api.routes.admin.support",
    ]:
        module = import_module(module_name)

        assert getattr(module, "router", None) is not None


def test_admin_router_preserves_public_admin_paths_once() -> None:
    from egp_api.routes.admin import router

    admin_route_keys = [
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", set())
        if getattr(route, "path", "").startswith("/v1/admin")
        and method not in {"HEAD", "OPTIONS"}
    ]

    assert set(admin_route_keys) == EXPECTED_ADMIN_ROUTE_KEYS
    for route_key in EXPECTED_ADMIN_ROUTE_KEYS:
        assert admin_route_keys.count(route_key) == 1
