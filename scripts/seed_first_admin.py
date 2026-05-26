#!/usr/bin/env python3
"""Bootstrap script: create the first tenant + admin user on a fresh deploy.

Non-interactive, idempotent, production-safe. Refuses to create a second
owner/admin for a tenant that already has one (regardless of status).
Reads password only from ``--password-stdin`` or ``EGP_FIRST_ADMIN_PASSWORD``
env var — passing ``--password`` on argv is rejected (would leak via ps).

Typical operator invocation:

    EGP_FIRST_ADMIN_PASSWORD='strong-passphrase-2026' \\
    ./.venv/bin/python scripts/seed_first_admin.py \\
        --tenant-name "Acme Procurement" \\
        --tenant-slug acme-procurement \\
        --admin-email ops@acme.example \\
        --admin-full-name "Acme Ops" \\
        --database-url "$DATABASE_URL"

Exit codes:
    0 — created OR already-seeded (both safe for retry wrappers)
    2 — argparse / validation error (e.g. invalid email, missing password)

Output (stdout, JSON, on success or idempotent rerun):
    {"status": "created", "tenant_id": "...", "user_id": "...", ...}
    {"status": "already-seeded", "tenant_id": "...", "user_id": null, ...}

Output (stderr):
    Target preview before any write:
        "==> target host=... port=... dbname=... user=..."
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal, TextIO
from urllib.parse import urlparse

from sqlalchemy import text

from egp_db.connection import create_shared_engine
from egp_db.repositories.auth_repo import hash_password

_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
_PLAN_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_ALLOWED_ROLES: tuple[str, ...] = ("owner", "admin")


@dataclass(frozen=True, slots=True)
class SeedFirstAdminResult:
    status: Literal["created", "already-seeded"]
    tenant_id: str
    user_id: str | None
    tenant_slug: str
    admin_email: str | None
    admin_count: int


class AdminAlreadyExistsError(RuntimeError):
    """Raised when the target tenant already has any owner/admin user."""


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _validate_email(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized or not _EMAIL_PATTERN.match(normalized):
        raise ValueError(f"invalid email: {value!r}")
    return normalized


def _validate_slug(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or not _SLUG_PATTERN.match(normalized):
        raise ValueError(
            f"invalid slug: {value!r} (lowercase letters, digits, hyphens only)"
        )
    return normalized


def _validate_role(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in _ALLOWED_ROLES:
        raise ValueError(f"invalid role: {value!r} (must be one of {_ALLOWED_ROLES})")
    return normalized


def _validate_plan_code(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or not _PLAN_CODE_PATTERN.match(normalized):
        raise ValueError(
            f"invalid plan_code: {value!r} (lowercase letters, digits, underscores)"
        )
    return normalized


# ---------------------------------------------------------------------------
# Core helper
# ---------------------------------------------------------------------------


def seed_first_admin(
    *,
    database_url: str,
    tenant_name: str,
    tenant_slug: str,
    admin_email: str,
    admin_full_name: str,
    password: str,
    plan_code: str = "free",
    role: Literal["owner", "admin"] = "owner",
) -> SeedFirstAdminResult:
    """Create or reuse a tenant; create the first owner/admin if absent.

    Idempotent: a second invocation against a tenant that already has an
    owner/admin returns status="already-seeded" without mutating state.
    """
    slug = _validate_slug(tenant_slug)
    email = _validate_email(admin_email)
    role_validated = _validate_role(role)
    plan = _validate_plan_code(plan_code)
    name = str(tenant_name or "").strip()
    if not name:
        raise ValueError("tenant_name must be non-empty")
    full_name = str(admin_full_name or "").strip()
    if not full_name:
        raise ValueError("admin_full_name must be non-empty")

    password_hash = hash_password(password)

    engine = create_shared_engine(database_url)
    with engine.begin() as conn:
        # Advisory xact lock prevents two concurrent seeds racing.
        # Scoped to (action, slug) so different tenants don't serialize.
        conn.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtext('egp.seed_first_admin'), hashtext(:slug))"
            ),
            {"slug": slug},
        )

        # 1) Find or create tenant
        existing_tenant = conn.execute(
            text("SELECT id FROM tenants WHERE slug = :slug"),
            {"slug": slug},
        ).first()
        if existing_tenant is not None:
            tenant_id = str(existing_tenant[0])
        else:
            row = conn.execute(
                text(
                    "INSERT INTO tenants (name, slug, plan_code) "
                    "VALUES (:name, :slug, :plan_code) RETURNING id"
                ),
                {"name": name, "slug": slug, "plan_code": plan},
            ).first()
            assert row is not None
            tenant_id = str(row[0])

        # 2) Check for existing admin/owner (any status)
        admin_count_row = conn.execute(
            text(
                "SELECT COUNT(*) FROM users "
                "WHERE tenant_id = :tenant_id AND role IN ('owner', 'admin')"
            ),
            {"tenant_id": tenant_id},
        ).first()
        assert admin_count_row is not None
        admin_count = int(admin_count_row[0])

        if admin_count > 0:
            return SeedFirstAdminResult(
                status="already-seeded",
                tenant_id=tenant_id,
                user_id=None,
                tenant_slug=slug,
                admin_email=None,  # info-leak safety
                admin_count=admin_count,
            )

        # 3) Insert the first admin. UNIQUE(tenant_id, email) catches
        #    accidental email collision with a non-admin user.
        try:
            user_row = conn.execute(
                text(
                    """
                    INSERT INTO users (
                        tenant_id, email, full_name, role, status,
                        password_hash, email_verified_at, mfa_enabled
                    ) VALUES (
                        :tenant_id, :email, :full_name, :role, 'active',
                        :password_hash, NOW(), FALSE
                    ) RETURNING id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "email": email,
                    "full_name": full_name,
                    "role": role_validated,
                    "password_hash": password_hash,
                },
            ).first()
        except Exception as exc:  # noqa: BLE001
            # Translate UNIQUE violation into a clear ValueError so callers
            # can distinguish "tenant has non-admin with this email" from
            # generic DB errors.
            msg = str(exc).lower()
            if "unique" in msg or "duplicate key" in msg:
                raise ValueError(
                    f"email already used in tenant {slug!r} by a non-admin user; "
                    "use a different admin email"
                ) from exc
            raise
        assert user_row is not None
        user_id = str(user_row[0])

        return SeedFirstAdminResult(
            status="created",
            tenant_id=tenant_id,
            user_id=user_id,
            tenant_slug=slug,
            admin_email=email,
            admin_count=1,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _emit_target_preview(database_url: str, stream: TextIO) -> None:
    parsed = urlparse(database_url)
    host = parsed.hostname or "?"
    port = parsed.port or 5432
    dbname = (parsed.path or "").lstrip("/") or "?"
    user = parsed.username or "?"
    stream.write(f"==> target host={host} port={port} dbname={dbname} user={user}\n")
    stream.flush()


def _read_password(
    args: argparse.Namespace,
    env: Mapping[str, str],
    stdin: TextIO,
) -> str:
    if args.password_stdin:
        raw = stdin.read()
        # Strip exactly one trailing newline (preserve intentional whitespace).
        if raw.endswith("\r\n"):
            return raw[:-2]
        if raw.endswith("\n"):
            return raw[:-1]
        return raw
    env_password = env.get("EGP_FIRST_ADMIN_PASSWORD", "")
    if env_password:
        return env_password
    raise SystemExit(
        "error: password required — pass --password-stdin or set "
        "EGP_FIRST_ADMIN_PASSWORD env var\n"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed_first_admin.py",
        description=(
            "Create the first tenant + admin user on a fresh deployment. "
            "Non-interactive, idempotent, refuses to create a second admin."
        ),
    )
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-full-name", required=True)
    parser.add_argument("--plan-code", default="free")
    parser.add_argument("--role", default="owner", choices=_ALLOWED_ROLES)
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read password from stdin (strips trailing newline)",
    )
    # Sentinel to reject `--password` argv (would leak via ps + shell history)
    parser.add_argument(
        "--password",
        help=argparse.SUPPRESS,
        default=None,
    )
    return parser


def main(
    argv: list[str] | None = None,
    env: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    import os

    argv = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ if env is None else env)
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits 0 for --help / --version and 2 for parse errors.
        # Preserve the original code instead of collapsing 0 → 2.
        if exc.code is None:
            return 2
        return int(exc.code)

    if args.password is not None:
        stderr.write(
            "error: refusing --password argv flag (leaks via ps + shell "
            "history). Use --password-stdin or EGP_FIRST_ADMIN_PASSWORD env var.\n"
        )
        return 2

    # Validate before opening any connection
    try:
        email = _validate_email(args.admin_email)
        slug = _validate_slug(args.tenant_slug)
        role = _validate_role(args.role)
        plan = _validate_plan_code(args.plan_code)
    except ValueError as exc:
        stderr.write(f"error: {exc}\n")
        return 2

    try:
        password = _read_password(args, env, stdin)
    except SystemExit as exc:
        stderr.write(str(exc))
        return 2

    _emit_target_preview(args.database_url, stderr)

    try:
        result = seed_first_admin(
            database_url=args.database_url,
            tenant_name=args.tenant_name,
            tenant_slug=slug,
            admin_email=email,
            admin_full_name=args.admin_full_name,
            password=password,
            plan_code=plan,
            role=role,
        )
    except ValueError as exc:
        stderr.write(f"error: {exc}\n")
        return 2

    stdout.write(json.dumps(asdict(result), sort_keys=True) + "\n")
    stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
