"""Worker entrypoint package."""

from __future__ import annotations

from .workflows.close_check import run_close_check_workflow
from .workflows.discover import run_discover_workflow
from .workflows.document_ingest import ingest_document_artifact
from .workflows.timeout_sweep import evaluate_timeout_transition


def main() -> None:
    print("e-GP Crawler Worker starting...")
    # Keep import-time references to workflow modules so runtime wiring is real.
    _ = (
        evaluate_timeout_transition,
        ingest_document_artifact,
        run_discover_workflow,
        run_close_check_workflow,
    )
