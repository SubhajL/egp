"""Drift test: keep `deploy/.env.production.example` in sync with code.

This test scans the runtime Python sources for `os.getenv("EGP_*")` and
`os.environ.get("EGP_*")` references using the AST (not regex, so docstrings
and comments cannot create false positives). It fails when:

- the template is missing an env var the runtime reads,
- the template lists an env var nothing in the runtime references,
- a key appears more than once in the template, or
- a template value looks like a real committed secret.

Two explicit allowlists handle legitimate gaps:

- ``TEMPLATE_ONLY_VARS`` — vars read via a passed Mapping (e.g. PR-A's
  ``build_target_from_env(env)``) that AST inspection cannot see directly but
  the operator still must set in production.
- ``SOURCE_ONLY_VARS`` — dev/test-only vars that are intentionally NOT in
  the production template (local dev seed helpers, etc.).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = REPO_ROOT / "deploy" / ".env.production.example"

ENV_READ_FUNCTIONS = {"getenv", "environ.get"}

# Vars read via Mapping-style indirection (PR-A's build_target_from_env)
# or only referenced as constants — AST scan can't see them, but they MUST
# appear in the production template so the operator sets them.
TEMPLATE_ONLY_VARS: frozenset[str] = frozenset(
    {
        # PR-A backup target — read from passed Mapping argument
        "EGP_BACKUP_TARGET",
        "EGP_BACKUP_LOCAL_CACHE_DIR",
        "EGP_BACKUP_LOCAL_RETENTION_DAYS",
        "EGP_BACKUP_LOCAL_KEEP_MIN",
        "EGP_BACKUP_REMOTE_RETENTION_DAYS",
        "EGP_BACKUP_REMOTE_KEEP_MIN",
        "EGP_BACKUP_R2_ACCOUNT_ID",
        "EGP_BACKUP_R2_ACCESS_KEY_ID",
        "EGP_BACKUP_R2_SECRET_ACCESS_KEY",
        "EGP_BACKUP_R2_BUCKET",
        "EGP_BACKUP_R2_OBJECT_PREFIX",
        # rclone artifact-mirror script reads these via bash `: ${VAR:?}`
        "EGP_ARTIFACT_BACKUP_SRC_REMOTE",
        "EGP_ARTIFACT_BACKUP_DEST_REMOTE",
        # monitoring overlay (PR-E) — referenced via ${VAR:?} in
        # docker-compose.monitoring.yml; not read by any Python runtime
        "EGP_GRAFANA_ADMIN_PASSWORD",
        # docker-compose-only vars (referenced via ${VAR:?} in docker-compose.yml)
        "EGP_API_DOMAIN",
        "EGP_APP_DOMAIN",
        "EGP_POSTGRES_DB",
        "EGP_POSTGRES_USER",
        "EGP_POSTGRES_PASSWORD",
        # Resend email provider (alternative to SMTP) — wired via compose only
        "EGP_RESEND_API_KEY",
        "EGP_RESEND_FROM",
        # gost proxy-relay upstream URL — referenced only in docker-compose.yml
        # (proxy-relay service command), not read by Python.
        "EGP_PROXY_UPSTREAM_URL",
    }
)

# Vars referenced only by dev/test helpers; intentionally NOT in prod template.
SOURCE_ONLY_VARS: frozenset[str] = frozenset(
    {
        "EGP_LOCAL_DEV_OWNER_EMAIL",
        "EGP_LOCAL_DEV_OWNER_NAME",
        "EGP_LOCAL_DEV_OWNER_PASSWORD",
        "EGP_LOCAL_DEV_TENANT_NAME",
        "EGP_LOCAL_DEV_TENANT_SLUG",
        "EGP_DEV_USE_ENV_LOCAL_RUNTIME",
        "EGP_PYTHON_BIN",  # used only by scripts/pg_backup.sh as a venv override
        # One-shot bootstrap secret consumed by scripts/seed_first_admin.py;
        # the operator passes it once on the command line then never again,
        # so it does NOT belong in the persistent production env file.
        "EGP_FIRST_ADMIN_PASSWORD",
    }
)

# Required non-EGP_* platform vars the operator must set in production.
REQUIRED_PLATFORM_VARS: frozenset[str] = frozenset(
    {
        "DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_STORAGE_BUCKET",
    }
)

# Launch-critical secrets that MUST appear in the Required section
# (per coding-logs/2026-05-26-09-21-17 launch-readiness PR-B spec).
LAUNCH_CRITICAL_SECRETS: frozenset[str] = frozenset(
    {
        "EGP_JWT_SECRET",
        "EGP_PAYMENT_CALLBACK_SECRET",
        "EGP_INTERNAL_WORKER_TOKEN",
    }
)

KNOWN_SECTION_LABELS: frozenset[str] = frozenset(
    {"required", "recommended", "optional"}
)

# Heuristics for "value looks like a real committed secret"
KNOWN_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^sk_(live|test)_[A-Za-z0-9]{20,}$"),  # Stripe-like
    re.compile(r"^op[ks]_(live|test)_[A-Za-z0-9]{20,}$"),  # OPN-like
    re.compile(r"^xoxb-\d{10,}-[A-Za-z0-9-]+$"),  # Slack bot
    re.compile(r"^[A-Fa-f0-9]{40,}$"),  # raw hex >= 40 chars
)

SOURCE_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        "tests",
        "docs",
        "coding-logs",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".next",
        "artifacts",
        "egp-dev-logs",
    }
)

# Legacy crawler script + its tests + mode-c stubs are not part of the
# runtime surface the prod template must cover.
SOURCE_EXCLUDE_FILES: frozenset[str] = frozenset(
    {"egp_crawler.py", "test_egp_crawler.py"}
)
SOURCE_EXCLUDE_PATH_PREFIXES: tuple[str, ...] = ("scripts/mode_c/",)


@dataclass(frozen=True, slots=True)
class TemplateEntry:
    name: str
    placeholder: str
    section: str
    line_number: int


def _parse_env_template(path: Path) -> dict[str, TemplateEntry]:
    """Parse a dotenv-style template into ``name → TemplateEntry``.

    Section is determined by the most recent ``# Section: <label>`` header.
    Raises ``ValueError`` if the file is structurally malformed.
    """
    if not path.exists():
        raise FileNotFoundError(f"template not found: {path}")
    entries: dict[str, TemplateEntry] = {}
    current_section = "unknown"
    section_header = re.compile(r"^#\s*Section:\s*(\w+)", re.IGNORECASE)
    kv_line = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            header = section_header.match(stripped)
            if header:
                current_section = header.group(1).lower()
            continue
        match = kv_line.match(stripped)
        if match is None:
            raise ValueError(
                f"{path}:{line_number}: not a valid KEY=value line: {raw!r}"
            )
        name, placeholder = match.group(1), match.group(2)
        if name in entries:
            # caller can detect via _collect_duplicate_template_keys;
            # keep first, but the dedicated duplicate test still flags it
            continue
        entries[name] = TemplateEntry(
            name=name,
            placeholder=placeholder,
            section=current_section,
            line_number=line_number,
        )
    return entries


def _collect_duplicate_template_keys(path: Path) -> set[str]:
    """Return names that appear on more than one KEY=value line."""
    seen: dict[str, int] = {}
    duplicates: set[str] = set()
    kv_line = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=")
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = kv_line.match(stripped)
        if match is None:
            continue
        name = match.group(1)
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            duplicates.add(name)
    return duplicates


def _iter_runtime_python_sources(repo_root: Path) -> Iterator[Path]:
    """Yield .py files that constitute the runtime surface (api + worker + packages).

    Excludes tests, docs, coding-logs, generated/build dirs, legacy crawler,
    and mode_c stubs.
    """
    for path in repo_root.rglob("*.py"):
        try:
            rel = path.relative_to(repo_root)
        except ValueError:
            continue
        parts = rel.parts
        if any(part in SOURCE_EXCLUDE_DIRS for part in parts):
            continue
        if rel.name in SOURCE_EXCLUDE_FILES:
            continue
        rel_str = str(rel).replace("\\", "/")
        if any(rel_str.startswith(p) for p in SOURCE_EXCLUDE_PATH_PREFIXES):
            continue
        yield path


def _literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_env_read_call(call: ast.Call) -> bool:
    """Return True if ``call`` is ``os.getenv(...)`` or ``os.environ.get(...)``."""
    func = call.func
    if isinstance(func, ast.Attribute):
        if (
            func.attr == "getenv"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        ):
            return True
        if func.attr == "get" and isinstance(func.value, ast.Attribute):
            inner = func.value
            if (
                inner.attr == "environ"
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "os"
            ):
                return True
    return False


_EGP_VAR_NAME = re.compile(r"^EGP_[A-Z][A-Z0-9_]*$")


def _collect_egp_env_refs(repo_root: Path) -> set[str]:
    """AST-walk runtime sources and collect literal ``EGP_*`` env var names.

    Captures three patterns:
      * Direct: ``os.getenv("EGP_*")``, ``os.environ.get("EGP_*")``,
        ``os.environ["EGP_*"]``
      * Helper-wrapped: any ``ast.Call`` whose positional or keyword args
        include a string literal matching ``^EGP_[A-Z][A-Z0-9_]*$`` (catches
        ``_int_from_env(source, "EGP_EGP_RPS", ...)``,
        ``_get_positive_int_env(name="EGP_BROWSER_CDP_PORT_BASE", ...)``).
    """
    found: set[str] = set()
    for path in _iter_runtime_python_sources(repo_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            # tolerate syntactically broken files; they're either deliberately
            # template-y or pre-merge state — drift test is not a syntax linter.
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Direct env-read calls
                if _is_env_read_call(node) and node.args:
                    literal = _literal_str(node.args[0])
                    if literal and literal.startswith("EGP_"):
                        found.add(literal)
                # Helper-wrapped: any string literal that LOOKS like an
                # EGP_ env-var name passed as a Call arg or kwarg.
                for child in node.args:
                    literal = _literal_str(child)
                    if literal and _EGP_VAR_NAME.match(literal):
                        found.add(literal)
                for keyword in node.keywords:
                    literal = _literal_str(keyword.value)
                    if literal and _EGP_VAR_NAME.match(literal):
                        found.add(literal)
            elif isinstance(node, ast.Subscript):
                value = node.value
                if (
                    isinstance(value, ast.Attribute)
                    and value.attr == "environ"
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "os"
                ):
                    slice_node = node.slice
                    literal = _literal_str(slice_node)
                    if literal and literal.startswith("EGP_"):
                        found.add(literal)
    return found


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_env_template_file_exists_and_parses() -> None:
    assert TEMPLATE_PATH.exists(), (
        f"expected production env template at {TEMPLATE_PATH.relative_to(REPO_ROOT)}"
    )
    entries = _parse_env_template(TEMPLATE_PATH)
    assert entries, "template must contain at least one KEY=value entry"


def test_env_template_has_no_duplicate_keys() -> None:
    duplicates = _collect_duplicate_template_keys(TEMPLATE_PATH)
    assert duplicates == set(), f"duplicate keys in template: {sorted(duplicates)}"


def test_env_template_tracks_runtime_egp_vars() -> None:
    """Every EGP_* var read by runtime code must appear in the template
    (or be explicitly listed in SOURCE_ONLY_VARS).
    """
    template = _parse_env_template(TEMPLATE_PATH)
    code_vars = _collect_egp_env_refs(REPO_ROOT)
    template_vars = {name for name in template if name.startswith("EGP_")}
    missing_from_template = code_vars - template_vars - SOURCE_ONLY_VARS
    assert missing_from_template == set(), (
        "EGP_* vars referenced by runtime code but missing from "
        f"deploy/.env.production.example: {sorted(missing_from_template)}\n"
        "Either add them to the template, or (if dev/test-only) extend "
        "SOURCE_ONLY_VARS in tests/operations/test_env_template.py."
    )


def test_every_template_egp_var_is_referenced_by_code_or_allowlisted() -> None:
    template = _parse_env_template(TEMPLATE_PATH)
    code_vars = _collect_egp_env_refs(REPO_ROOT)
    template_egp = {name for name in template if name.startswith("EGP_")}
    orphaned = template_egp - code_vars - TEMPLATE_ONLY_VARS
    assert orphaned == set(), (
        "EGP_* vars in template but not referenced by runtime code "
        f"(and not in TEMPLATE_ONLY_VARS allowlist): {sorted(orphaned)}\n"
        "Either remove from template, or add to TEMPLATE_ONLY_VARS "
        "with a comment explaining the indirection."
    )


def test_env_template_includes_required_platform_vars() -> None:
    template = _parse_env_template(TEMPLATE_PATH)
    missing = REQUIRED_PLATFORM_VARS - set(template.keys())
    assert missing == set(), (
        f"non-EGP_* platform vars missing from template: {sorted(missing)}"
    )


def test_required_section_includes_launch_critical_secrets() -> None:
    template = _parse_env_template(TEMPLATE_PATH)
    for var in LAUNCH_CRITICAL_SECRETS:
        assert var in template, f"{var} missing from template"
        assert template[var].section == "required", (
            f"{var} should be in the Required section, "
            f"found in {template[var].section!r}"
        )


def test_pr_a_backup_vars_appear_in_template() -> None:
    template = _parse_env_template(TEMPLATE_PATH)
    pr_a_required = {
        "EGP_BACKUP_TARGET",
        "EGP_BACKUP_LOCAL_CACHE_DIR",
        "EGP_BACKUP_R2_ACCOUNT_ID",
        "EGP_BACKUP_R2_ACCESS_KEY_ID",
        "EGP_BACKUP_R2_SECRET_ACCESS_KEY",
        "EGP_BACKUP_R2_BUCKET",
    }
    missing = pr_a_required - set(template.keys())
    assert missing == set(), (
        f"PR-A backup vars missing from template: {sorted(missing)}"
    )


def test_rate_limiter_vars_appear_in_template() -> None:
    template = _parse_env_template(TEMPLATE_PATH)
    rate_limiter_vars = {
        "EGP_EGP_RPS",
        "EGP_EGP_BURST",
        "EGP_EGP_CIRCUIT_429_THRESHOLD",
        "EGP_EGP_CIRCUIT_RESET_SECONDS",
    }
    missing = rate_limiter_vars - set(template.keys())
    assert missing == set(), (
        f"rate-limiter vars (PR-06) missing from template: {sorted(missing)}"
    )


def test_env_template_has_known_section_labels() -> None:
    template = _parse_env_template(TEMPLATE_PATH)
    labels_used = {entry.section for entry in template.values()}
    unknown = labels_used - KNOWN_SECTION_LABELS
    assert unknown == set(), (
        f"unknown section labels in template: {sorted(unknown)}; "
        f"expected one of {sorted(KNOWN_SECTION_LABELS)}"
    )


@pytest.mark.parametrize(
    "pattern_index,pattern", list(enumerate(KNOWN_SECRET_PATTERNS))
)
def test_env_template_uses_safe_placeholder_values(
    pattern_index: int, pattern: re.Pattern[str]
) -> None:
    template = _parse_env_template(TEMPLATE_PATH)
    suspicious: list[tuple[str, str]] = []
    for entry in template.values():
        value = entry.placeholder.strip().strip("'\"")
        if pattern.match(value):
            suspicious.append((entry.name, value[:8] + "..."))
    assert suspicious == [], (
        f"template values look like real secrets matching pattern #{pattern_index}: "
        f"{suspicious}. Replace with CHANGE_ME_* placeholders."
    )


def test_env_template_covers_all_compose_required_vars() -> None:
    """Every ``${VAR}``/``${VAR:?}``/``${VAR:-default}`` interpolation in
    ``docker-compose.yml`` must resolve from the template, otherwise
    ``docker compose --env-file deploy/.env.production.example config -q`` fails.
    """
    compose_path = REPO_ROOT / "docker-compose.yml"
    if not compose_path.exists():
        pytest.skip("docker-compose.yml not present")
    compose_text = compose_path.read_text(encoding="utf-8")
    referenced = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)", compose_text))
    template = _parse_env_template(TEMPLATE_PATH)
    missing = referenced - set(template.keys())
    assert missing == set(), (
        "docker-compose.yml interpolates these vars but the template doesn't "
        f"declare them: {sorted(missing)}. "
        "Add them to deploy/.env.production.example so "
        "`docker compose --env-file ... config -q` does not fail at deploy time."
    )


def test_env_template_is_compose_env_compatible() -> None:
    """Compose `--env-file` and systemd `EnvironmentFile=` parse strict
    KEY=value with no shell substitution. Verify no `$(...)` or `${...}`
    appears in values (comments are allowed).
    """
    bad_lines: list[tuple[int, str]] = []
    for line_number, raw in enumerate(
        TEMPLATE_PATH.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # split into value + inline comment
        if "=" not in stripped:
            continue
        _, value_with_comment = stripped.split("=", 1)
        # peel off any trailing " # comment"
        value = re.split(r"\s+#", value_with_comment, maxsplit=1)[0]
        if "$(" in value or "${" in value:
            bad_lines.append((line_number, raw))
    assert bad_lines == [], (
        f"template has shell substitution in values (incompatible with "
        f"docker-compose --env-file and systemd EnvironmentFile=): {bad_lines}"
    )
