"""Google Drive OAuth and REST helpers."""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import HTTP


GOOGLE_DRIVE_DEFAULT_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/drive.file",
)


@dataclass(frozen=True, slots=True)
class GoogleDriveOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...] = GOOGLE_DRIVE_DEFAULT_SCOPES


class GoogleDriveApiError(RuntimeError):
    pass


def email_from_id_token(id_token: str | None) -> str | None:
    if not id_token:
        return None
    parts = id_token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8"))
        parsed = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    email = parsed.get("email")
    return str(email).strip() or None if email is not None else None


class GoogleDriveClient:
    authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    upload_endpoint = "https://www.googleapis.com/upload/drive/v3/files"
    files_endpoint = "https://www.googleapis.com/drive/v3/files"

    def build_authorization_url(
        self,
        *,
        config: GoogleDriveOAuthConfig,
        state: str,
    ) -> str:
        return (
            self.authorization_endpoint
            + "?"
            + urllib.parse.urlencode(
                {
                    "client_id": config.client_id,
                    "redirect_uri": config.redirect_uri,
                    "response_type": "code",
                    "scope": " ".join(config.scopes),
                    "state": state,
                    "access_type": "offline",
                    "prompt": "consent",
                    "include_granted_scopes": "true",
                }
            )
        )

    def exchange_code(
        self,
        *,
        config: GoogleDriveOAuthConfig,
        code: str,
    ) -> dict[str, object]:
        return self._post_form(
            self.token_endpoint,
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": config.redirect_uri,
            },
        )

    def refresh_access_token(
        self,
        *,
        config: GoogleDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]:
        return self._post_form(
            self.token_endpoint,
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )

    def upload_file(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {"name": name}
        if folder_id:
            metadata["parents"] = [folder_id]
        body, content_type_header = _multipart_body(
            metadata=metadata,
            data=data,
            content_type=content_type
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream",
        )
        url = (
            self.upload_endpoint
            + "?"
            + urllib.parse.urlencode(
                {
                    "uploadType": "multipart",
                    "fields": "id,name,webViewLink,webContentLink",
                    "supportsAllDrives": "true",
                }
            )
        )
        return self._request_json(
            urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": content_type_header,
                },
            )
        )

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        url = f"{self.files_endpoint}/{urllib.parse.quote(file_id)}?alt=media"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise GoogleDriveApiError(f"Google Drive download failed: HTTP {exc.code}") from exc

    def delete_file(self, *, access_token: str, file_id: str) -> None:
        url = f"{self.files_endpoint}/{urllib.parse.quote(file_id)}"
        request = urllib.request.Request(
            url,
            method="DELETE",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30):
                return
        except urllib.error.HTTPError as exc:
            raise GoogleDriveApiError(f"Google Drive delete failed: HTTP {exc.code}") from exc

    def download_url(self, *, file_id: str) -> str:
        return f"https://drive.google.com/uc?id={urllib.parse.quote(file_id)}&export=download"

    def _post_form(self, url: str, payload: dict[str, str]) -> dict[str, object]:
        return self._request_json(
            urllib.request.Request(
                url,
                data=urllib.parse.urlencode(payload).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        )

    def _request_json(self, request: urllib.request.Request) -> dict[str, object]:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise GoogleDriveApiError(
                f"Google Drive API request failed: HTTP {exc.code}: {body}"
            ) from exc
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise GoogleDriveApiError("Google Drive API response was not an object")
        return parsed


def _multipart_body(
    *,
    metadata: dict[str, object],
    data: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    message = EmailMessage(policy=HTTP)
    message.set_type("multipart/related")
    message.add_attachment(
        json.dumps(metadata).encode("utf-8"),
        maintype="application",
        subtype="json",
        filename=None,
    )
    message.add_attachment(
        data,
        maintype=content_type.split("/", 1)[0],
        subtype=content_type.split("/", 1)[1] if "/" in content_type else "octet-stream",
        filename=None,
    )
    body = message.as_bytes().split(b"\r\n\r\n", 1)[1]
    return body, message["Content-Type"]


def normalize_google_drive_scopes(scopes: Sequence[str] | None) -> tuple[str, ...]:
    if scopes is None:
        return GOOGLE_DRIVE_DEFAULT_SCOPES
    normalized = tuple(scope.strip() for scope in scopes if scope.strip())
    return normalized or GOOGLE_DRIVE_DEFAULT_SCOPES
