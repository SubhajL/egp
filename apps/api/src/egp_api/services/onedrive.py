"""Compatibility exports for OneDrive helpers."""

from egp_db.onedrive import (
    ONEDRIVE_DEFAULT_SCOPES,
    OneDriveApiError,
    OneDriveClient,
    OneDriveOAuthConfig,
    email_from_onedrive_id_token,
    normalize_onedrive_scopes,
)

__all__ = [
    "ONEDRIVE_DEFAULT_SCOPES",
    "OneDriveApiError",
    "OneDriveClient",
    "OneDriveOAuthConfig",
    "email_from_onedrive_id_token",
    "normalize_onedrive_scopes",
]
