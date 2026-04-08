"""Core crawler domain helpers extracted from the legacy crawler."""

from .canonical_id import build_project_aliases, generate_canonical_id
from .closure_rules import (
    check_consulting_timeout,
    check_stale_closure,
    check_winner_closure,
)
from .discovery_authorization import (
    build_discovery_authorization_snapshot,
    DiscoveryAuthorizationError,
    DiscoveryAuthorizationSnapshot,
    normalize_keyword,
    require_discovery_authorization,
    SubscriptionLike,
)
from .document_hasher import hash_file
from .project_lifecycle import transition_state

__all__ = [
    "build_project_aliases",
    "check_consulting_timeout",
    "check_stale_closure",
    "check_winner_closure",
    "build_discovery_authorization_snapshot",
    "DiscoveryAuthorizationError",
    "DiscoveryAuthorizationSnapshot",
    "generate_canonical_id",
    "hash_file",
    "normalize_keyword",
    "require_discovery_authorization",
    "SubscriptionLike",
    "transition_state",
]
