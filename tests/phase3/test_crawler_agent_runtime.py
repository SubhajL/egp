"""U8f acceptance tests: the executable agent runtime and the shadow producer.

Two things turn U8 from a library into a running system:

* `agent_runtime` — claim over HTTPS, crawl locally, renew while the browser
  works, submit the result. This is what makes `CrawlerAgentApiClient` an agent.
* `agent_shadow` — the dual-report producer, which had no implementation when the
  shadow *contract* landed.

The browser is injected in every test here. That is not a shortcut around
integration: the crawl itself is covered by the discovery workflow's own suite, and
what these tests pin is the loop's control flow — lease renewal, failure
classification, and the rule that an observation must never fail a real crawl.
"""

from __future__ import annotations

import pytest


class _FakeClaim:
    contract_version = "v1"
    job_id = "job-1"
    tenant_id = "11111111-1111-1111-1111-111111111111"
    profile_id = "profile-1"
    profile_type = "custom"
    keyword = "ครุภัณฑ์"
    trigger_type = "manual"
    live = True
    recrawl_request_id = None
    claim_token = "token-1"
    lease_expires_at = "2026-01-01T00:00:00+00:00"
    attempt_count = 0


class _FakeClient:
    def __init__(self, *, claims=None, renew_error=None, submit_error=None) -> None:
        self._claims = list(claims if claims is not None else [_FakeClaim()])
        self._renew_error = renew_error
        self._submit_error = submit_error
        self.submitted: list[dict] = []
        self.renewals = 0

    def claim(self, *, agent_id, lease_seconds=300.0):
        return self._claims.pop(0) if self._claims else None

    def renew(self, *, claim, lease_seconds=300.0):
        self.renewals += 1
        if self._renew_error is not None:
            raise self._renew_error
        return claim

    def submit_result(self, *, claim, idempotency_key, envelope):
        if self._submit_error is not None:
            raise self._submit_error
        self.submitted.append(
            {"claim": claim, "idempotency_key": idempotency_key, "envelope": envelope}
        )
        return None


def _envelope_executor(claim):
    return {"kind": "discovery", "payload": {"projects": []}}


# ----------------------------------------------------------------------
# the loop
# ----------------------------------------------------------------------


def test_the_runtime_claims_crawls_and_submits() -> None:
    from egp_worker.agent_runtime import run_once

    client = _FakeClient()
    assert (
        run_once(client=client, executor=_envelope_executor, agent_id="canary")
        == "applied"
    )
    assert len(client.submitted) == 1
    # Stable per claim attempt, so a retried delivery is a replay not a second result.
    assert client.submitted[0]["idempotency_key"] == "agent:job-1:token-1"


def test_the_runtime_reports_idle_when_nothing_is_due() -> None:
    """Control: a loop that always claimed would pass the test above and fail here."""

    from egp_worker.agent_runtime import run_once

    client = _FakeClient(claims=[])
    assert (
        run_once(client=client, executor=_envelope_executor, agent_id="canary")
        == "idle"
    )
    assert client.submitted == []


def test_a_failed_crawl_submits_no_result() -> None:
    """The job's lease then expires and it becomes claimable again — the existing
    at-least-once behaviour. Submitting anything here would record a result for a
    crawl that did not happen."""

    from egp_worker.agent_runtime import run_once

    def _explode(claim):
        raise RuntimeError("browser died")

    client = _FakeClient()
    assert (
        run_once(client=client, executor=_explode, agent_id="canary") == "crawl_failed"
    )
    assert client.submitted == []


def test_a_lost_lease_during_the_crawl_abandons_the_result() -> None:
    """A 409 during renewal means someone else owns the job. Continuing would burn
    e-GP traffic on a result the API will refuse."""

    from egp_worker.agent_client import AgentClaimRejectedError
    from egp_worker.agent_runtime import run_once

    client = _FakeClient(renew_error=AgentClaimRejectedError("stale"))

    def _slow(claim):
        import time

        time.sleep(0.25)
        return {"kind": "discovery", "payload": {"projects": []}}

    outcome = run_once(
        client=client,
        executor=_slow,
        agent_id="canary",
        renew_interval_seconds=0.05,
    )
    assert outcome == "lease_lost"
    assert client.submitted == []


def test_the_runtime_renews_the_lease_while_the_crawl_runs() -> None:
    """A discovery crawl outlasts a claim lease, so without renewal the job would
    be reclaimed mid-crawl."""

    from egp_worker.agent_runtime import run_once

    client = _FakeClient()

    def _slow(claim):
        import time

        time.sleep(0.3)
        return {"kind": "discovery", "payload": {"projects": []}}

    assert (
        run_once(
            client=client,
            executor=_slow,
            agent_id="canary",
            renew_interval_seconds=0.05,
        )
        == "applied"
    )
    assert client.renewals >= 2


def test_the_loop_stops_on_a_disabled_protocol_and_on_auth_failure() -> None:
    """Neither is retryable, and hammering a switched-off endpoint is exactly what
    the typed errors exist to prevent."""

    from egp_worker.agent_client import AgentAuthError, AgentProtocolDisabledError
    from egp_worker.agent_runtime import run_loop

    for error in (AgentProtocolDisabledError("off"), AgentAuthError("bad token")):

        class _Refuses:
            def claim(self, *, agent_id, lease_seconds=300.0):
                raise error

        counts = run_loop(
            client=_Refuses(),
            executor=_envelope_executor,
            agent_id="canary",
            max_iterations=10,
            sleeper=lambda _s: None,
        )
        assert counts == {"stopped": 1}


def test_the_loop_backs_off_and_continues_after_a_transport_error() -> None:
    """The control plane being briefly unwell must not stop the crawler — the
    opposite response to auth/disabled, which is the point of the distinction."""

    from egp_worker.agent_client import AgentTransportError
    from egp_worker.agent_runtime import run_loop

    class _FlakyThenIdle:
        def __init__(self) -> None:
            self.calls = 0

        def claim(self, *, agent_id, lease_seconds=300.0):
            self.calls += 1
            if self.calls == 1:
                raise AgentTransportError("connection reset")
            return None

    slept: list[float] = []
    counts = run_loop(
        client=_FlakyThenIdle(),
        executor=_envelope_executor,
        agent_id="canary",
        max_iterations=2,
        sleeper=slept.append,
    )
    assert counts["transport_error"] == 1
    assert counts["idle"] == 1
    assert slept, "a transport error must back off before retrying"


def test_main_reports_a_configuration_error_instead_of_crashing() -> None:
    from egp_worker.agent_runtime import main

    assert main(["--once"], client=None, executor=_envelope_executor) in (0, 2)


# ----------------------------------------------------------------------
# the shadow producer
# ----------------------------------------------------------------------


class _Project:
    def __init__(self, name: str) -> None:
        self.project_number = None
        self.project_name = name
        self.organization_name = "กรมตัวอย่าง"
        self.proposal_submission_date = None
        self.budget_amount = None
        self.source_status_text = "ประกาศเชิญชวน"


def test_the_shadow_envelope_carries_the_run_id_on_every_entry() -> None:
    """`run_id` is what binds the envelope to the durable evidence the comparison
    reads. Without it the processor can only answer `unavailable`."""

    from egp_worker.agent_shadow import build_shadow_envelope

    envelope = build_shadow_envelope(
        run_id="run-1", keyword="ก", projects=[_Project("ก"), _Project("ข")]
    )
    assert envelope["kind"] == "discovery"
    entries = envelope["payload"]["projects"]
    assert len(entries) == 2
    assert {entry["run_id"] for entry in entries} == {"run-1"}
    assert {entry["project_name"] for entry in entries} == {"ก", "ข"}


def test_the_shadow_envelope_matches_what_the_comparison_expects() -> None:
    """End-to-end on the identity contract: the identities the processor derives
    from this envelope must equal those derived from the same projects. A field
    dropped here would silently produce permanent `mismatch` verdicts."""

    from egp_crawler_core.canonical_id import generate_canonical_id
    from egp_worker.agent_shadow import build_shadow_envelope

    projects = [_Project("ก"), _Project("ข")]
    envelope = build_shadow_envelope(run_id="run-1", keyword="ก", projects=projects)

    from_envelope = {
        generate_canonical_id(
            project_number=entry.get("project_number"),
            organization_name=entry.get("organization_name"),
            project_name=entry.get("project_name"),
            proposal_submission_date=entry.get("proposal_submission_date"),
            budget_amount=entry.get("budget_amount"),
        )
        for entry in envelope["payload"]["projects"]
    }
    from_projects = {
        generate_canonical_id(
            project_number=project.project_number,
            organization_name=project.organization_name,
            project_name=project.project_name,
            proposal_submission_date=project.proposal_submission_date,
            budget_amount=project.budget_amount,
        )
        for project in projects
    }
    assert from_envelope == from_projects


def test_a_shadow_report_failure_never_raises() -> None:
    """The crawl it observes has already succeeded. A parity probe that can fail a
    production crawl is worse than no parity probe."""

    from egp_worker.agent_shadow import report_shadow_result

    class _Broken:
        def submit_result(self, **kwargs):
            raise RuntimeError("control plane down")

    assert (
        report_shadow_result(
            job_id="job-1",
            tenant_id="t",
            claim_token="token-1",
            run_id="run-1",
            keyword="ก",
            projects=[_Project("ก")],
            client=_Broken(),
        )
        is False
    )


def test_a_shadow_report_uses_a_stable_idempotency_key() -> None:
    from egp_worker.agent_shadow import report_shadow_result

    class _Recording:
        def __init__(self) -> None:
            self.keys: list[str] = []

        def submit_result(self, *, claim, idempotency_key, envelope):
            self.keys.append(idempotency_key)

    client = _Recording()
    for _ in range(2):
        report_shadow_result(
            job_id="job-1",
            tenant_id="t",
            claim_token="token-1",
            run_id="run-1",
            keyword="ก",
            projects=[_Project("ก")],
            client=client,
        )
    assert client.keys == ["shadow:job-1:run-1"] * 2


# ----------------------------------------------------------------------
# the claim token actually reaches the child
# ----------------------------------------------------------------------


def test_the_dispatch_request_carries_the_claim_token() -> None:
    """The child cannot dual-report without it, and the parent cannot build the
    envelope at all (dispatch() returns None and the decoded result has no project
    bodies)."""

    from egp_api.services.discovery_dispatch import DiscoveryDispatchRequest

    request = DiscoveryDispatchRequest(
        tenant_id="t",
        profile_id="p",
        profile_type="custom",
        keyword="ก",
        claim_token="token-1",
    )
    assert request.claim_token == "token-1"


def test_shadow_reporting_is_off_unless_explicitly_enabled(monkeypatch) -> None:
    """Default-off: enabling shadow must be a deliberate operator action, not a
    side effect of deploying."""

    from egp_worker.main import _maybe_report_shadow_parity

    monkeypatch.delenv("EGP_CRAWLER_AGENT_SHADOW_REPORTING", raising=False)

    class _Boom:
        @property
        def run(self):  # pragma: no cover - must never be reached
            raise AssertionError("shadow reporting ran while disabled")

    # No exception: the guard returns before touching the result at all.
    _maybe_report_shadow_parity(
        {"agent_job_id": "job-1", "agent_claim_token": "token-1"}, _Boom()
    )


def test_shadow_reporting_is_skipped_without_claim_context(monkeypatch) -> None:
    """A job dispatched without agent context (e.g. an older parent) must not try
    to report — there is no claim to report under."""

    from egp_worker.main import _maybe_report_shadow_parity

    monkeypatch.setenv("EGP_CRAWLER_AGENT_SHADOW_REPORTING", "true")

    class _Boom:
        @property
        def run(self):  # pragma: no cover - must never be reached
            raise AssertionError("shadow reporting ran without a claim")

    _maybe_report_shadow_parity({}, _Boom())


@pytest.mark.parametrize("flag", ["1", "true", "yes", "on"])
def test_shadow_reporting_accepts_the_documented_truthy_flags(
    monkeypatch, flag: str
) -> None:
    from egp_worker.main import _maybe_report_shadow_parity

    monkeypatch.setenv("EGP_CRAWLER_AGENT_SHADOW_REPORTING", flag)
    calls: list[dict] = []
    monkeypatch.setattr(
        "egp_worker.agent_shadow.report_shadow_result",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    class _Result:
        class run:
            class run:
                id = "run-1"

        projects: list = []

    _maybe_report_shadow_parity(
        {
            "agent_job_id": "job-1",
            "agent_claim_token": "token-1",
            "tenant_id": "t",
            "keyword": "ก",
        },
        _Result(),
    )
    assert len(calls) == 1
