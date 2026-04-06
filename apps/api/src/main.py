"""Compatibility wrapper for the packaged API app."""

from egp_api.main import create_app

app = create_app()

__all__ = ["app", "create_app"]
