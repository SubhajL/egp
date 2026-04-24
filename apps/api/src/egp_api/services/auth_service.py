"""Password login, recovery, verification, and MFA orchestration."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import struct
import time
from dataclasses import dataclass
from secrets import token_bytes
from urllib.parse import quote

from egp_api.auth import AuthContext
from egp_db.repositories.admin_repo import SqlAdminRepository, TenantRecord
from egp_db.repositories.auth_repo import (
    LoginUserRecord,
    SqlAuthRepository,
    hash_password,
    verify_password,
)
from egp_db.repositories.notification_repo import SqlNotificationRepository
from egp_notifications.service import NotificationService
from egp_shared_types.enums import BillingRecordStatus, UserRole


@dataclass(frozen=True, slots=True)
class AuthenticatedUserView:
    id: str | None
    subject: str
    email: str | None
    full_name: str | None
    role: str | None
    status: str | None
    email_verified: bool
    email_verified_at: str | None
    mfa_enabled: bool


@dataclass(frozen=True, slots=True)
class CurrentSessionView:
    user: AuthenticatedUserView
    tenant: TenantRecord
    requires_billing_update: bool


@dataclass(frozen=True, slots=True)
class LoginResult:
    session_token: str
    current: CurrentSessionView


class WorkspaceSlugRequiredError(PermissionError):
    """Raised when valid credentials map to multiple workspaces."""


class AuthService:
    def __init__(
        self,
        repository: SqlAuthRepository,
        admin_repository: SqlAdminRepository,
        *,
        session_max_age_seconds: int,
        notification_service: NotificationService | None = None,
        notification_repository: SqlNotificationRepository | None = None,
        billing_service=None,  # BillingService — avoid circular import
        web_base_url: str = "http://localhost:3000",
    ) -> None:
        self._repository = repository
        self._admin_repository = admin_repository
        self._session_max_age_seconds = max(60, int(session_max_age_seconds))
        self._notification_service = notification_service
        self._notification_repository = notification_repository
        self._billing_service = billing_service
        self._web_base_url = web_base_url.rstrip("/")

    def login(
        self,
        *,
        tenant_slug: str | None,
        email: str,
        password: str,
        mfa_code: str | None = None,
    ) -> LoginResult:
        normalized_tenant_slug = str(tenant_slug or "").strip()
        if normalized_tenant_slug:
            user = self._repository.find_login_user(tenant_slug=normalized_tenant_slug, email=email)
        else:
            candidates = self._repository.list_login_users_by_email(email=email)
            if not candidates:
                raise PermissionError("registration required")
            if len(candidates) == 1:
                user = candidates[0]
            else:
                matching_candidates = [
                    candidate
                    for candidate in candidates
                    if verify_password(password, candidate.password_hash)
                ]
                if not matching_candidates:
                    raise PermissionError("invalid credentials")
                if len(matching_candidates) > 1:
                    raise WorkspaceSlugRequiredError("workspace slug required")
                user = matching_candidates[0]
        if user is None:
            raise PermissionError("invalid credentials")
        if not user.tenant_is_active or user.status != "active":
            raise PermissionError("account is not active")
        if not verify_password(password, user.password_hash):
            raise PermissionError("invalid credentials")
        if user.mfa_enabled:
            if not str(mfa_code or "").strip():
                raise PermissionError("mfa code required")
            if not _verify_totp_code(user.mfa_secret, str(mfa_code)):
                raise PermissionError("invalid mfa code")
        session_token = self._repository.create_session(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            expires_in_seconds=self._session_max_age_seconds,
        )
        return LoginResult(
            session_token=session_token,
            current=self._build_current_view(_auth_context_from_user(user)),
        )

    def register(
        self,
        *,
        company_name: str,
        email: str,
        password: str,
    ) -> LoginResult:
        """Self-service registration: create tenant + owner user + free trial + session."""
        if self._notification_repository is None:
            raise RuntimeError("notification_repository is required for registration")
        if self._billing_service is None:
            raise RuntimeError("billing_service is required for registration")

        # Derive and deduplicate tenant slug
        slug = _slugify(company_name)
        if not slug:
            slug = "tenant"
        base_slug = slug
        counter = 1
        while self._admin_repository.get_tenant_by_slug(slug=slug) is not None:
            slug = f"{base_slug}-{counter}"
            counter += 1

        # Check if this email is already registered (across any tenant)
        normalized_email = str(email).strip().lower()
        if self._repository.find_login_user_by_email(email=normalized_email) is not None:
            raise ValueError(f"email already registered: {normalized_email}")

        # Create tenant with free_trial plan
        tenant = self._admin_repository.create_tenant(
            name=company_name.strip(),
            slug=slug,
            plan_code="free_trial",
        )

        # Create owner user with hashed password and email pre-verified
        from datetime import UTC, datetime

        now_iso = datetime.now(UTC).isoformat()
        created = self._notification_repository.create_user(
            tenant_id=tenant.id,
            email=normalized_email,
            role=UserRole.OWNER,
            status="active",
            password_hash=hash_password(password),
            email_verified_at=now_iso,
        )

        # Activate free trial subscription
        self._billing_service.start_free_trial(
            tenant_id=tenant.id,
            actor_subject="self-registration",
        )

        # Issue session
        session_token = self._repository.create_session(
            tenant_id=tenant.id,
            user_id=created["id"],
            expires_in_seconds=self._session_max_age_seconds,
        )
        user = self._repository.find_login_user(tenant_slug=slug, email=normalized_email)
        if user is None:
            raise RuntimeError("user not found after creation")
        return LoginResult(
            session_token=session_token,
            current=self._build_current_view(_auth_context_from_user(user)),
        )

    def revoke_session(self, *, session_token: str | None) -> bool:
        if not session_token:
            return False
        return self._repository.revoke_session(session_token=session_token)

    def authenticate_session(self, session_token: str) -> AuthContext | None:
        user = self._repository.get_session_user(session_token=session_token)
        if user is None or not user.tenant_is_active or user.status != "active":
            return None
        return _auth_context_from_user(user)

    def describe_current(self, auth_context: AuthContext) -> CurrentSessionView:
        return self._build_current_view(auth_context)

    def issue_user_invite(self, *, tenant_id: str, user_id: str) -> str:
        user = self._require_user(tenant_id, user_id)
        token = self._repository.create_account_action_token(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            purpose="invite",
            delivery_email=user.email,
            expires_in_seconds=72 * 3600,
        )
        self._send_email_or_raise(
            to=user.email,
            subject="คำเชิญเข้าสู่ระบบ e-GP Intelligence",
            body=(
                f"คุณได้รับคำเชิญให้เข้าใช้งาน e-GP Intelligence\n\n"
                f"ลิงก์ตั้งรหัสผ่าน: {self._link('/invite', token)}\n\n"
                "ลิงก์นี้ใช้ได้ครั้งเดียวและจะหมดอายุภายใน 72 ชั่วโมง"
            ),
        )
        return user.email

    def accept_invite(self, *, token: str, password: str) -> LoginResult:
        user = self._repository.consume_account_action_token(token=token, purpose="invite")
        if user is None:
            raise PermissionError("invalid or expired invite token")
        if not user.tenant_is_active or user.status != "active":
            raise PermissionError("account is not active")
        self._repository.update_password(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            password_hash=hash_password(password),
        )
        self._repository.mark_email_verified(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
        )
        refreshed = self._require_user(user.tenant_id, user.user_id)
        session_token = self._repository.create_session(
            tenant_id=refreshed.tenant_id,
            user_id=refreshed.user_id,
            expires_in_seconds=self._session_max_age_seconds,
        )
        return LoginResult(
            session_token=session_token,
            current=self._build_current_view(_auth_context_from_user(refreshed)),
        )

    def request_password_reset(self, *, tenant_slug: str, email: str) -> None:
        user = self._repository.find_login_user(tenant_slug=tenant_slug, email=email)
        if user is None or not user.tenant_is_active or user.status != "active" or not user.email:
            return
        token = self._repository.create_account_action_token(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            purpose="password_reset",
            delivery_email=user.email,
            expires_in_seconds=2 * 3600,
        )
        self._send_email_if_configured(
            to=user.email,
            subject="รีเซ็ตรหัสผ่าน e-GP Intelligence",
            body=(
                f"เราได้รับคำขอรีเซ็ตรหัสผ่านของคุณ\n\n"
                f"ลิงก์รีเซ็ตรหัสผ่าน: {self._link('/reset-password', token)}\n\n"
                "หากคุณไม่ได้ร้องขอ โปรดเพิกเฉยอีเมลฉบับนี้"
            ),
        )

    def reset_password(self, *, token: str, password: str) -> None:
        user = self._repository.consume_account_action_token(
            token=token,
            purpose="password_reset",
        )
        if user is None:
            raise PermissionError("invalid or expired password reset token")
        if not user.tenant_is_active or user.status != "active":
            raise PermissionError("account is not active")
        self._repository.update_password(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            password_hash=hash_password(password),
        )
        self._repository.revoke_all_sessions_for_user(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
        )

    def send_email_verification(self, auth_context: AuthContext) -> None:
        user = self._require_user(
            auth_context.tenant_id, auth_context.user_id or auth_context.subject
        )
        if user.email_verified_at is not None:
            return
        token = self._repository.create_account_action_token(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            purpose="email_verification",
            delivery_email=user.email,
            expires_in_seconds=24 * 3600,
        )
        self._send_email_or_raise(
            to=user.email,
            subject="ยืนยันอีเมล e-GP Intelligence",
            body=(
                f"กรุณายืนยันอีเมลของคุณเพื่อรักษาความปลอดภัยของบัญชี\n\n"
                f"ลิงก์ยืนยันอีเมล: {self._link('/verify-email', token)}"
            ),
        )

    def verify_email(self, *, token: str) -> bool:
        user = self._repository.consume_account_action_token(
            token=token,
            purpose="email_verification",
        )
        if user is None:
            raise PermissionError("invalid or expired email verification token")
        self._repository.mark_email_verified(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
        )
        return True

    def setup_mfa(self, auth_context: AuthContext) -> tuple[str, str]:
        user = self._require_user(
            auth_context.tenant_id, auth_context.user_id or auth_context.subject
        )
        secret = _generate_totp_secret()
        self._repository.set_mfa_secret(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            secret=secret,
        )
        return secret, _otpauth_uri(email=user.email, secret=secret)

    def enable_mfa(self, auth_context: AuthContext, *, code: str) -> bool:
        user = self._require_user(
            auth_context.tenant_id, auth_context.user_id or auth_context.subject
        )
        if not _verify_totp_code(user.mfa_secret, code):
            raise PermissionError("invalid mfa code")
        self._repository.set_mfa_enabled(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            enabled=True,
        )
        return True

    def disable_mfa(self, auth_context: AuthContext, *, code: str) -> bool:
        user = self._require_user(
            auth_context.tenant_id, auth_context.user_id or auth_context.subject
        )
        if not user.mfa_enabled:
            return False
        if not _verify_totp_code(user.mfa_secret, code):
            raise PermissionError("invalid mfa code")
        self._repository.set_mfa_enabled(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            enabled=False,
        )
        self._repository.set_mfa_secret(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            secret=None,
        )
        return False

    def _build_current_view(self, auth_context: AuthContext) -> CurrentSessionView:
        tenant = self._admin_repository.get_tenant(tenant_id=auth_context.tenant_id)
        if tenant is None:
            raise KeyError(auth_context.tenant_id)
        email_verified_at = auth_context.email_verified_at or _string_claim(
            auth_context.claims,
            "email_verified_at",
        )
        return CurrentSessionView(
            user=AuthenticatedUserView(
                id=auth_context.user_id,
                subject=auth_context.subject,
                email=auth_context.email or _string_claim(auth_context.claims, "email"),
                full_name=auth_context.full_name or _string_claim(auth_context.claims, "full_name"),
                role=auth_context.role or _string_claim(auth_context.claims, "role"),
                status=auth_context.status,
                email_verified=email_verified_at is not None,
                email_verified_at=email_verified_at,
                mfa_enabled=bool(
                    auth_context.mfa_enabled or auth_context.claims.get("mfa_enabled")
                ),
            ),
            tenant=tenant,
            requires_billing_update=self._requires_billing_update(auth_context.tenant_id),
        )

    def _requires_billing_update(self, tenant_id: str) -> bool:
        if self._billing_service is None:
            return False
        snapshot = self._billing_service.list_snapshot(tenant_id=tenant_id, limit=50, offset=0)
        return any(
            str(item.record.status) == BillingRecordStatus.OVERDUE.value for item in snapshot.items
        )

    def _require_user(self, tenant_id: str, user_id: str) -> LoginUserRecord:
        user = self._repository.get_user_by_id(tenant_id=tenant_id, user_id=user_id)
        if user is None:
            raise KeyError(user_id)
        if not user.tenant_is_active or user.status != "active":
            raise PermissionError("account is not active")
        return user

    def _send_email_or_raise(self, *, to: str, subject: str, body: str) -> None:
        sent = self._send_email_if_configured(to=to, subject=subject, body=body)
        if not sent:
            raise RuntimeError("email delivery is not configured")

    def _send_email_if_configured(self, *, to: str, subject: str, body: str) -> bool:
        if self._notification_service is None:
            return False
        return self._notification_service.send_email_message(
            to=to,
            subject=subject,
            body=body,
        )

    def _link(self, path: str, token: str) -> str:
        return f"{self._web_base_url}{path}?token={quote(token)}"


def _string_claim(claims: dict[str, object], key: str) -> str | None:
    value = claims.get(key)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _auth_context_from_user(user: LoginUserRecord) -> AuthContext:
    return AuthContext(
        tenant_id=user.tenant_id,
        subject=user.user_id,
        claims={
            "sub": user.user_id,
            "tenant_id": user.tenant_id,
            "role": user.role,
            "email": user.email,
            "full_name": user.full_name,
            "email_verified_at": user.email_verified_at,
            "mfa_enabled": user.mfa_enabled,
        },
        user_id=user.user_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        status=user.status,
        email_verified_at=user.email_verified_at,
        mfa_enabled=user.mfa_enabled,
        tenant_slug=user.tenant_slug,
        tenant_name=user.tenant_name,
        tenant_plan_code=user.tenant_plan_code,
    )


def _generate_totp_secret() -> str:
    return base64.b32encode(token_bytes(20)).decode("ascii").rstrip("=")


def _decode_totp_secret(secret: str | None) -> bytes | None:
    if secret is None:
        return None
    normalized = secret.strip().upper()
    if not normalized:
        return None
    padding = "=" * (-len(normalized) % 8)
    return base64.b32decode(f"{normalized}{padding}", casefold=True)


def _totp_code(secret: str | None, counter: int) -> str | None:
    key = _decode_totp_secret(secret)
    if key is None:
        return None
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"


def _verify_totp_code(secret: str | None, code: str, *, window: int = 1) -> bool:
    normalized = str(code).strip()
    if len(normalized) != 6 or not normalized.isdigit():
        return False
    counter = int(time.time()) // 30
    for offset in range(-window, window + 1):
        candidate = _totp_code(secret, counter + offset)
        if candidate is not None and hmac.compare_digest(candidate, normalized):
            return True
    return False


def _otpauth_uri(*, email: str, secret: str) -> str:
    return (
        "otpauth://totp/"
        f"{quote('e-GP Intelligence')}:{quote(email)}"
        f"?secret={quote(secret)}&issuer={quote('e-GP Intelligence')}"
    )


def _slugify(text: str) -> str:
    """Convert a free-form company name to a lowercase URL-safe slug.

    Non-ASCII characters are stripped (Thai company names will produce a slug
    derived only from the ASCII parts; if nothing ASCII remains the caller
    must fall back to a default).
    """
    normalized = str(text).strip().lower()
    # Replace common separators with a hyphen
    normalized = re.sub(r"[\s_/\\]+", "-", normalized)
    # Keep only ASCII letters, digits, and hyphens
    normalized = re.sub(r"[^a-z0-9\-]", "", normalized)
    # Collapse multiple hyphens
    normalized = re.sub(r"-{2,}", "-", normalized)
    # Strip leading/trailing hyphens
    return normalized.strip("-")
