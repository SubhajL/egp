"""Drift checks for the SOC incident-response runbook."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK_PATH = REPO_ROOT / "docs" / "SOC_INCIDENT_RESPONSE.md"


def _runbook_text() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def test_soc_incident_response_runbook_exists() -> None:
    assert RUNBOOK_PATH.exists()


def test_soc_runbook_links_existing_operational_runbooks() -> None:
    text = _runbook_text()
    links = {
        "docs/LIGHTSAIL_LOW_COST_LAUNCH.md",
        "docs/REMOTE_LOCAL_CRAWLER.md",
        "docs/OBSERVABILITY.md",
        "docs/BACKUP_AND_RESTORE.md",
        "docs/SECRET_ROTATION.md",
        "docs/STRIPE_DEPLOYMENT.md",
        "docs/LINE_MANUAL_PROMPTPAY.md",
        "docs/VERCEL_DEPLOYMENT.md",
    }
    for link in links:
        assert link in text
        assert (REPO_ROOT / link).exists()


def test_soc_runbook_covers_targeted_document_backfill_validation() -> None:
    text = _runbook_text()
    required_terms = [
        "69039416683",
        "document_backfill_enqueue",
        "scripts/run_remote_crawl.sh crawl",
        "head_object",
        "/v1/documents/",
        "Content-Length",
        "R2",
    ]
    for term in required_terms:
        assert term in text


def test_soc_runbook_has_incident_response_basics() -> None:
    text = _runbook_text()
    expected_headings = [
        "## Severity",
        "## First 15 minutes",
        "## Incident records",
        "## Escalation matrix",
        "## Recovery playbooks",
    ]
    for heading in expected_headings:
        assert heading in text
    assert re.search(r"incident commander", text, flags=re.IGNORECASE)
