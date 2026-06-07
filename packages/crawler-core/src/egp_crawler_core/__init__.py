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
    EffectiveDiscoveryEntitlement,
    normalize_keyword,
    require_discovery_authorization,
    resolve_effective_discovery_entitlement,
    SubscriptionLike,
)
from .document_hasher import hash_file
from .invitation_rules import is_invitation_stage_status
from .profile_lock import (
    acquire_profile_lock,
    PROFILE_LOCK_FILENAME,
    ProfileLockedError,
    release_profile_lock,
)
from .project_lifecycle import transition_state
from .rate_limiter import (
    CircuitOpenError,
    exponential_backoff_delay,
    FileLockRateLimiter,
    get_default_rate_limiter,
    RateLimiterConfig,
    reset_default_rate_limiter_for_tests,
)

__all__ = [
    "acquire_profile_lock",
    "build_project_aliases",
    "CircuitOpenError",
    "check_consulting_timeout",
    "check_stale_closure",
    "check_winner_closure",
    "build_discovery_authorization_snapshot",
    "DiscoveryAuthorizationError",
    "DiscoveryAuthorizationSnapshot",
    "EffectiveDiscoveryEntitlement",
    "exponential_backoff_delay",
    "FileLockRateLimiter",
    "generate_canonical_id",
    "get_default_rate_limiter",
    "hash_file",
    "is_invitation_stage_status",
    "normalize_keyword",
    "PROFILE_LOCK_FILENAME",
    "ProfileLockedError",
    "RateLimiterConfig",
    "release_profile_lock",
    "require_discovery_authorization",
    "reset_default_rate_limiter_for_tests",
    "resolve_effective_discovery_entitlement",
    "SubscriptionLike",
    "transition_state",
]
