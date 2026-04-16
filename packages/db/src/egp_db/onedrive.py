"""OneDrive OAuth and Microsoft Graph helpers shared by API and worker runtimes."""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


ONEDRIVE_DEFAULT_SCOPES = (
    "openid",
    "email",
    "offline_access",
    "Files.ReadWrite",
)


@dataclass(frozen=True, slots=True)
class OneDriveOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...] = ONEDRIVE_DEFAULT_SCOPES
    tenant: str = "common"


class OneDriveApiError(RuntimeError):
    pass


def email_from_onedrive_id_token(id_token: str | None) -> str | None:
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
    for key in ("email", "preferred_username", "upn"):
        value = parsed.get(key)
        if value is not None:
            normalized = str(value).strip()
            if normalized:
                return normalized
    return None


class OneDriveClient:
    authority_host = "https://login.microsoftonline.com"
    graph_endpoint = "https://graph.microsoft.com/v1.0"
    upload_chunk_size = 10 * 1024 * 1024

    def build_authorization_url(
        self,
        *,
        config: OneDriveOAuthConfig,
        state: str,
    ) -> str:
        return (
            self._authorization_endpoint(config)
            + "?"
            + urllib.parse.urlencode(
                {
                    "client_id": config.client_id,
                    "redirect_uri": config.redirect_uri,
                    "response_type": "code",
                    "response_mode": "query",
                    "scope": " ".join(config.scopes),
                    "state": state,
                }
            )
        )

    def exchange_code(
        self,
        *,
        config: OneDriveOAuthConfig,
        code: str,
    ) -> dict[str, object]:
        return self._post_form(
            self._token_endpoint(config),
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
        config: OneDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]:
        return self._post_form(
            self._token_endpoint(config),
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "redirect_uri": config.redirect_uri,
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
        resolved_content_type = (
            content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        if not data:
            return self._put_content(
                access_token=access_token,
                folder_id=folder_id,
                name=name,
                data=data,
                content_type=resolved_content_type,
            )
        upload_session = self._create_upload_session(
            access_token=access_token,
            folder_id=folder_id,
            name=name,
        )
        upload_url = str(upload_session.get("uploadUrl") or "").strip()
        if not upload_url:
            raise OneDriveApiError("OneDrive upload session did not include uploadUrl")
        total_size = len(data)
        last_response: dict[str, object] | None = None
        for start in range(0, total_size, self.upload_chunk_size):
            end = min(start + self.upload_chunk_size, total_size) - 1
            chunk = data[start : end + 1]
            last_response = self._request_json(
                urllib.request.Request(
                    upload_url,
                    data=chunk,
                    method="PUT",
                    headers={
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{total_size}",
                        "Content-Type": resolved_content_type,
                    },
                )
            )
        if last_response is None:
            raise OneDriveApiError("OneDrive upload did not send any content")
        return last_response

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        request = urllib.request.Request(
            f"{self.graph_endpoint}/me/drive/items/{urllib.parse.quote(file_id)}/content",
            method="GET",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise OneDriveApiError(
                f"OneDrive download failed: HTTP {exc.code}"
            ) from exc

    def delete_file(self, *, access_token: str, file_id: str) -> None:
        request = urllib.request.Request(
            f"{self.graph_endpoint}/me/drive/items/{urllib.parse.quote(file_id)}",
            method="DELETE",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30):
                return
        except urllib.error.HTTPError as exc:
            raise OneDriveApiError(f"OneDrive delete failed: HTTP {exc.code}") from exc

    def download_url(self, *, access_token: str, file_id: str) -> str:
        request = urllib.request.Request(
            f"{self.graph_endpoint}/me/drive/items/{urllib.parse.quote(file_id)}",
            method="GET",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        metadata = self._request_json(request)
        candidate = metadata.get("@microsoft.graph.downloadUrl")
        if not candidate:
            raise OneDriveApiError("OneDrive metadata did not include download URL")
        return str(candidate)

    def _create_upload_session(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
    ) -> dict[str, object]:
        quoted_name = urllib.parse.quote(name, safe="")
        if folder_id:
            url = (
                f"{self.graph_endpoint}/me/drive/items/{urllib.parse.quote(folder_id)}:"
                f"/{quoted_name}:/createUploadSession"
            )
        else:
            url = f"{self.graph_endpoint}/me/drive/root:/{quoted_name}:/createUploadSession"
        return self._request_json(
            urllib.request.Request(
                url,
                data=json.dumps(
                    {"item": {"@microsoft.graph.conflictBehavior": "fail"}}
                ).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
        )

    def _put_content(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str,
    ) -> dict[str, object]:
        quoted_name = urllib.parse.quote(name, safe="")
        if folder_id:
            url = (
                f"{self.graph_endpoint}/me/drive/items/{urllib.parse.quote(folder_id)}:"
                f"/{quoted_name}:/content"
            )
        else:
            url = f"{self.graph_endpoint}/me/drive/root:/{quoted_name}:/content"
        return self._request_json(
            urllib.request.Request(
                url,
                data=data,
                method="PUT",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": content_type,
                },
            )
        )

    def _post_form(self, url: str, payload: Mapping[str, str]) -> dict[str, object]:
        return self._request_json(
            urllib.request.Request(
                url,
                data=urllib.parse.urlencode(dict(payload)).encode("utf-8"),
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
            raise OneDriveApiError(
                f"OneDrive API request failed: HTTP {exc.code}: {body}"
            ) from exc
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise OneDriveApiError("OneDrive API response was not an object")
        return parsed

    def _authorization_endpoint(self, config: OneDriveOAuthConfig) -> str:
        return f"{self.authority_host}/{urllib.parse.quote(config.tenant)}/oauth2/v2.0/authorize"

    def _token_endpoint(self, config: OneDriveOAuthConfig) -> str:
        return f"{self.authority_host}/{urllib.parse.quote(config.tenant)}/oauth2/v2.0/token"


def normalize_onedrive_scopes(scopes: Sequence[str] | None) -> tuple[str, ...]:
    if scopes is None:
        return ONEDRIVE_DEFAULT_SCOPES
    normalized = tuple(scope.strip() for scope in scopes if scope.strip())
    return normalized or ONEDRIVE_DEFAULT_SCOPES
