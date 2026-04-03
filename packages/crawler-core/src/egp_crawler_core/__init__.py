"""Core crawler domain helpers extracted from the legacy crawler."""

from .canonical_id import build_project_aliases, generate_canonical_id
from .closure_rules import (
    check_consulting_timeout,
    check_stale_closure,
    check_winner_closure,
)
from .document_hasher import hash_file
from .project_lifecycle import transition_state

__all__ = [
    "build_project_aliases",
    "check_consulting_timeout",
    "check_stale_closure",
    "check_winner_closure",
    "generate_canonical_id",
    "hash_file",
    "transition_state",
]
