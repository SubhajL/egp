"""Drift tests for the PR-D Vercel deployment config.

Three concerns:

1. ``apps/web/vercel.json`` parses, declares the Next.js framework + Singapore
   region, sets the documented build/install commands, and ships the agreed
   security headers.
2. The Docker Compose ``web`` service is gated behind ``profiles:
   ["single-host"]`` so the default Vercel-mode ``docker compose up -d``
   doesn't start it. Validated by parsing the YAML (no Docker daemon
   required); a second test optionally runs ``docker compose config`` if
   the binary is on PATH.
3. Every ``NEXT_PUBLIC_*`` env var referenced in ``apps/web/src/`` is
   documented either in the production env template (PR-B) or in the new
   Vercel runbook.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
VERCEL_JSON_PATH = REPO_ROOT / "apps" / "web" / "vercel.json"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
ENV_TEMPLATE_PATH = REPO_ROOT / "deploy" / ".env.production.example"
VERCEL_DOC_PATH = REPO_ROOT / "docs" / "VERCEL_DEPLOYMENT.md"
WEB_SRC_DIR = REPO_ROOT / "apps" / "web" / "src"
WEB_PACKAGE_JSON_PATH = REPO_ROOT / "apps" / "web" / "package.json"

REQUIRED_SECURITY_HEADERS = frozenset(
    {
        "Strict-Transport-Security",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    }
)


# ---------------------------------------------------------------------------
# vercel.json
# ---------------------------------------------------------------------------


def _load_vercel_json() -> dict[str, object]:
    return json.loads(VERCEL_JSON_PATH.read_text(encoding="utf-8"))


def test_vercel_json_is_valid_json_and_has_required_fields() -> None:
    assert VERCEL_JSON_PATH.exists(), f"missing {VERCEL_JSON_PATH}"
    config = _load_vercel_json()
    assert config.get("framework") == "nextjs"
    assert isinstance(config.get("buildCommand"), str)
    assert isinstance(config.get("installCommand"), str)
    assert isinstance(config.get("outputDirectory"), str)


def test_vercel_json_framework_is_nextjs_and_region_is_singapore() -> None:
    config = _load_vercel_json()
    assert config["framework"] == "nextjs"
    regions = config.get("regions")
    assert isinstance(regions, list)
    assert "sin1" in regions, f"expected sin1 in regions, got {regions}"


def test_vercel_json_build_command_aligns_with_package_json() -> None:
    config = _load_vercel_json()
    package = json.loads(WEB_PACKAGE_JSON_PATH.read_text(encoding="utf-8"))
    pkg_build = package["scripts"]["build"]
    # Either match the package.json script verbatim or wrap it via npm.
    assert config["buildCommand"] in (pkg_build, "npm run build"), (
        f"vercel buildCommand {config['buildCommand']!r} does not align with "
        f"package.json build {pkg_build!r}"
    )


def test_vercel_json_install_command_is_deterministic() -> None:
    config = _load_vercel_json()
    # `npm ci` is the deterministic / reproducible install.
    assert config["installCommand"] == "npm ci"


def test_vercel_json_has_required_security_headers() -> None:
    config = _load_vercel_json()
    headers_blocks = config.get("headers")
    assert isinstance(headers_blocks, list) and headers_blocks, (
        "expected at least one headers block"
    )
    found: set[str] = set()
    for block in headers_blocks:
        for header in block.get("headers", []):
            found.add(header.get("key"))
    missing = REQUIRED_SECURITY_HEADERS - found
    assert missing == set(), (
        f"vercel.json is missing required security headers: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# docker-compose.yml
# ---------------------------------------------------------------------------


def _load_compose() -> dict[str, object]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_compose_web_service_has_single_host_profile() -> None:
    compose = _load_compose()
    services = compose["services"]
    web = services.get("web")
    assert web is not None, "expected services.web in docker-compose.yml"
    profiles = web.get("profiles")
    assert profiles == ["single-host"], (
        f"expected services.web.profiles == ['single-host'], got {profiles!r}"
    )


def test_compose_caddy_does_not_hard_depend_on_web() -> None:
    """Caddy MUST NOT have a hard dependency on the profiled-out web
    service, else `docker compose config` fails in default Vercel mode.
    """
    compose = _load_compose()
    caddy = compose["services"]["caddy"]
    depends = caddy.get("depends_on") or {}
    if isinstance(depends, list):
        assert "web" not in depends
    else:
        assert "web" not in depends, (
            f"caddy.depends_on still references web: {depends!r}"
        )


def test_compose_default_up_excludes_web_and_validates() -> None:
    """Optional: requires `docker compose` on PATH. Validates that the
    Vercel-mode (default) Compose graph is internally consistent and
    DOES NOT include the web service.
    """
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ENV_TEMPLATE_PATH),
            "-f",
            str(COMPOSE_PATH),
            "config",
            "--services",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"docker compose config failed: {completed.stderr}"
    )
    services = set(completed.stdout.strip().splitlines())
    assert "web" not in services, (
        f"default Compose graph must exclude profiled-out web; got {services}"
    )


def test_compose_single_host_profile_includes_web() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ENV_TEMPLATE_PATH),
            "-f",
            str(COMPOSE_PATH),
            "--profile",
            "single-host",
            "config",
            "--services",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"docker compose config (single-host) failed: {completed.stderr}"
    )
    services = set(completed.stdout.strip().splitlines())
    assert "web" in services, f"--profile single-host must include web; got {services}"


# ---------------------------------------------------------------------------
# NEXT_PUBLIC_* documentation coverage
# ---------------------------------------------------------------------------


_NEXT_PUBLIC_REGEX = re.compile(r"NEXT_PUBLIC_[A-Z][A-Z0-9_]*")


def _collect_next_public_vars(src_dir: Path) -> set[str]:
    found: set[str] = set()
    for path in src_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in _NEXT_PUBLIC_REGEX.findall(text):
            found.add(match)
    return found


def test_vercel_doc_warns_against_loose_cors_regex() -> None:
    """The runbook MUST flag the security implication of a broad
    `^https://[a-z0-9-]+\\.vercel\\.app$` regex, because the API
    reflects the origin with Access-Control-Allow-Credentials=true.
    A loose regex paired with cross-site cookies would let any
    vercel.app subdomain hit the authenticated API.
    """
    doc_text = VERCEL_DOC_PATH.read_text(encoding="utf-8")
    assert "DO NOT use" in doc_text, (
        "runbook must explicitly warn against the loose vercel.app regex"
    )
    assert "scope" in doc_text.lower(), (
        "runbook must explain how to scope the regex by project + team"
    )


def test_vercel_doc_documents_cross_origin_cookie_requirements() -> None:
    """Cross-origin cookie flow from app.example.com to api.example.com
    requires BOTH EGP_SESSION_COOKIE_SECURE=true AND
    EGP_SESSION_COOKIE_SAMESITE=none. The env template defaults SAMESITE
    to 'lax' (correct for single-host); the runbook MUST tell operators
    to override it for Vercel-mode launches.
    """
    doc_text = VERCEL_DOC_PATH.read_text(encoding="utf-8")
    assert "EGP_SESSION_COOKIE_SAMESITE=none" in doc_text, (
        "runbook must document setting SAMESITE=none for Vercel-mode cookies"
    )
    assert "EGP_SESSION_COOKIE_SECURE=true" in doc_text, (
        "runbook must document SECURE=true alongside SAMESITE=none"
    )


def test_required_next_public_vars_in_vercel_doc_or_template() -> None:
    referenced = _collect_next_public_vars(WEB_SRC_DIR)
    assert referenced, "expected to find at least one NEXT_PUBLIC_* var in apps/web/src"
    template_text = ENV_TEMPLATE_PATH.read_text(encoding="utf-8")
    doc_text = VERCEL_DOC_PATH.read_text(encoding="utf-8")
    missing: list[str] = []
    for name in sorted(referenced):
        if name in template_text or name in doc_text:
            continue
        missing.append(name)
    assert missing == [], (
        "the following NEXT_PUBLIC_* vars are referenced by apps/web/src but "
        f"appear in neither {ENV_TEMPLATE_PATH.relative_to(REPO_ROOT)} nor "
        f"{VERCEL_DOC_PATH.relative_to(REPO_ROOT)}: {missing}"
    )
