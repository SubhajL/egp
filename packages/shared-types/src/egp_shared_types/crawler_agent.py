"""V1 crawler-agent wire contract.

This is a cross-process contract: the API serves it, and a crawler agent (U8) and
the inbox processor (U7c) consume it. `packages/shared-types/AGENTS.md` requires
these shapes to live here rather than being restated in routes and executors.

Canonicalisation matters. The envelope SHA-256 is what distinguishes an identical
delivery replay (return the original inbox row) from a conflicting one (409), so
both the API and any future producer must hash the *same* bytes for the same
logical payload. `canonical_envelope_sha256` is the single definition of that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any


CRAWLER_AGENT_CONTRACT_VERSION = "v1"

# Result envelope kinds. U7c can apply `discovery` envelopes because they are pure
# data. `document` is deliberately NOT supported yet: document ingestion requires
# the actual file bytes and scoped artifact upload is U9, so an agent-supplied
# document descriptor cannot be applied faithfully. The processor rejects it with
# a typed error rather than half-applying it.
AGENT_RESULT_KIND_DISCOVERY = "discovery"
AGENT_RESULT_KIND_STATUS = "status"
AGENT_RESULT_KIND_DOCUMENT = "document"

SUPPORTED_AGENT_RESULT_KINDS: frozenset[str] = frozenset(
    {AGENT_RESULT_KIND_DISCOVERY, AGENT_RESULT_KIND_STATUS}
)
KNOWN_AGENT_RESULT_KINDS: frozenset[str] = SUPPORTED_AGENT_RESULT_KINDS | {
    AGENT_RESULT_KIND_DOCUMENT
}


def canonical_envelope_json(envelope: dict[str, Any]) -> str:
    """Render an envelope to its canonical JSON form.

    Sorted keys and no insignificant whitespace, so two structurally identical
    envelopes always produce identical bytes regardless of how the producer
    serialised them.
    """

    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str)


def canonical_envelope_sha256(envelope: dict[str, Any]) -> str:
    """SHA-256 of the canonical envelope form. The delivery-identity fingerprint."""

    return hashlib.sha256(canonical_envelope_json(envelope).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentClaim:
    """What an agent needs to actually perform a claimed discovery job.

    `tenant_id` is DERIVED from the claimed row, never accepted from the caller —
    `/internal/worker/*` authenticates with one global token that carries no
    tenant identity, so the claimed job is the only trustworthy source of tenancy.
    """

    contract_version: str
    job_id: str
    tenant_id: str
    profile_id: str
    profile_type: str
    keyword: str
    trigger_type: str
    live: bool
    recrawl_request_id: str | None
    claim_token: str
    lease_expires_at: str
    attempt_count: int


@dataclass(frozen=True)
class InboxSubmission:
    """Outcome of submitting a result envelope."""

    result_id: str
    job_id: str
    tenant_id: str
    inbox_status: str
    replayed: bool
    received_at: str


@dataclass(frozen=True)
class AgentResultEnvelope:
    """The V1 result body an agent submits for a claimed job."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)

    def is_supported(self) -> bool:
        return self.kind in SUPPORTED_AGENT_RESULT_KINDS
