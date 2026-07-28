"""U8a acceptance tests: notification parity for agent-sourced projects.

U7c shipped the standalone inbox processor with `ProjectIngestService` constructed
with **no** notification dispatcher (`crawler_agent_results.py:329`), so a project
first seen through an agent result envelope was persisted silently while the same
project seen through the ordinary API ingest path produced a `NEW_PROJECT`
notification. That was recorded as a deliberate, logged gap for U8 to close.

These tests run against a real ephemeral PostgreSQL cluster because what is under
test is the *composition of real collaborators* — the entitlement gate reads
billing subscriptions, the recipient resolver reads users, and webhook enqueue
writes a delivery row. A mocked dispatcher would assert what I believed those
collaborators do rather than what they actually do, and the defect being fixed
here is precisely a wiring defect.

Nothing is mocked. SMTP is simply left unconfigured, which is a supported
production configuration (`NotificationService` stores the in-app row and skips
email), so no fake sender is needed either.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import time
from uuid import uuid4

from psycopg import connect
import pytest

from egp_shared_types.enums import NotificationType, UserRole


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"

# `monthly_membership` grants notifications; an active `free_trial` deliberately
# does NOT (entitlement_service.py:205-209). That is a real product distinction,
# which is why the withheld case below needs no mock.
PLAN_WITH_NOTIFICATIONS = "monthly_membership"
PLAN_WITHOUT_NOTIFICATIONS = "free_trial"

DISCOVERABLE_STATUS = "ประกาศเชิญชวน"


@pytest.fixture(scope="module")
def migrated_database_url() -> str:
    from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available

    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for the U8a notification tests")

    from egp_db.migration_runner import apply_migrations

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_u8a_notifications")
        database_url = cluster.database_url("egp_u8a_notifications")
        apply_migrations(database_url=database_url, migrations_dir=MIGRATIONS_DIR)
        yield database_url


@pytest.fixture(autouse=True)
def _isolate(migrated_database_url: str):
    """Reset seeded rows between tests.

    The cluster is module-scoped and both the agent claimer and the inbox drain
    are global (each takes the oldest due row), so without this a test would
    routinely process another test's row and its assertions would be meaningless.
    Deleting tenants is enough — every table used here cascades from it.
    """

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM tenants")
        connection.commit()
    yield


def _seed_entitled_tenant(cursor, *, plan_code: str) -> tuple[str, str]:
    """Create a tenant with an ACTIVE subscription on `plan_code`.

    Returns (tenant_id, profile_id). The subscription is seeded as real rows
    rather than stubbed, so the entitlement gate under test is the production one.
    """

    tenant_id = str(uuid4())
    profile_id = str(uuid4())
    record_id = str(uuid4())
    today = date.today()

    cursor.execute(
        "INSERT INTO tenants (id, name, slug) VALUES (%s, 'U8a', %s)",
        (tenant_id, f"t-{tenant_id[:8]}"),
    )
    cursor.execute(
        "INSERT INTO crawl_profiles (id, tenant_id, name) VALUES (%s, %s, 'p')",
        (profile_id, tenant_id),
    )
    cursor.execute(
        """
        INSERT INTO billing_records
            (id, tenant_id, record_number, plan_code, status,
             billing_period_start, billing_period_end, currency, amount_due)
        VALUES (%s, %s, %s, %s, 'paid', %s, %s, 'THB', 0)
        """,
        (
            record_id,
            tenant_id,
            f"REC-{record_id[:8]}",
            plan_code,
            today - timedelta(days=1),
            today + timedelta(days=30),
        ),
    )
    cursor.execute(
        """
        INSERT INTO billing_subscriptions
            (id, tenant_id, billing_record_id, plan_code, status,
             billing_period_start, billing_period_end)
        VALUES (%s, %s, %s, %s, 'active', %s, %s)
        """,
        (
            str(uuid4()),
            tenant_id,
            record_id,
            plan_code,
            today - timedelta(days=1),
            today + timedelta(days=30),
        ),
    )
    return tenant_id, profile_id


def _seed_agent_job(cursor, *, tenant_id: str, profile_id: str) -> str:
    job_id = str(uuid4())
    cursor.execute(
        """
        INSERT INTO discovery_jobs
            (id, tenant_id, profile_id, profile_type, keyword,
             next_attempt_at, execution_backend)
        VALUES (%s, %s, %s, 'custom', 'ครุภัณฑ์',
                NOW() - INTERVAL '1 minute', 'agent')
        """,
        (job_id, tenant_id, profile_id),
    )
    return job_id


def _discovery_envelope(project_name: str) -> dict:
    return {
        "kind": "discovery",
        "payload": {
            "projects": [
                {
                    "keyword": "ครุภัณฑ์",
                    "project_name": project_name,
                    "organization_name": "กรมตัวอย่าง",
                    "source_status_text": DISCOVERABLE_STATUS,
                }
            ]
        },
    }


def _submit_result(repository, *, job_id: str, envelope: dict) -> None:
    """Claim `job_id` through the real agent claimer and submit `envelope`."""

    claim = None
    for _ in range(50):
        candidate = repository.claim_agent_job(agent_id="u8a-agent")
        if candidate is None:
            break
        if candidate.job_id == job_id:
            claim = candidate
            break
    assert claim is not None, "the seeded agent job was not claimable"
    repository.record_result_envelope(
        tenant_id=claim.tenant_id,
        job_id=claim.job_id,
        claim_token=claim.claim_token,
        idempotency_key=f"u8a-{job_id}",
        contract_version="v1",
        envelope=envelope,
    )


def _notifications_for(database_url: str, tenant_id: str) -> list[tuple[str, str]]:
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT notification_type, channel
                FROM notifications
                WHERE tenant_id = %s
                ORDER BY created_at
                """,
                (tenant_id,),
            )
            return [(row[0], row[1]) for row in cursor.fetchall()]


def _webhook_delivery_count(database_url: str, tenant_id: str) -> int:
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM webhook_deliveries WHERE tenant_id = %s",
                (tenant_id,),
            )
            return int(cursor.fetchone()[0])


def _project_count(database_url: str, tenant_id: str) -> int:
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM projects WHERE tenant_id = %s", (tenant_id,)
            )
            return int(cursor.fetchone()[0])


def _drain_once(database_url: str, tmp_path: Path) -> None:
    """Drive the processor exactly as production does — through its own builder.

    Constructing a processor by hand here would bypass the wiring under test.
    """

    from egp_api.executors.crawler_agent_results import (
        build_crawler_agent_inbox_runtime,
    )

    runtime = build_crawler_agent_inbox_runtime(database_url, artifact_root=tmp_path)
    outcome = runtime.processor.process_once()
    assert outcome.applied, f"the inbox row was not applied: {outcome}"


# ----------------------------------------------------------------------
# R3 — the gap U7c recorded
# ----------------------------------------------------------------------


def test_inbox_processor_dispatches_new_project_for_an_agent_sourced_project(
    migrated_database_url: str, tmp_path: Path
) -> None:
    from egp_db.repositories.crawler_agent_repo import create_crawler_agent_repository

    repository = create_crawler_agent_repository(database_url=migrated_database_url)
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, profile_id = _seed_entitled_tenant(
                cursor, plan_code=PLAN_WITH_NOTIFICATIONS
            )
            job_id = _seed_agent_job(cursor, tenant_id=tenant_id, profile_id=profile_id)
        connection.commit()

    _submit_result(
        repository, job_id=job_id, envelope=_discovery_envelope("โครงการใหม่ U8a")
    )
    _drain_once(migrated_database_url, tmp_path)

    assert _project_count(migrated_database_url, tenant_id) == 1
    assert _notifications_for(migrated_database_url, tenant_id) == [
        (NotificationType.NEW_PROJECT.value, "in_app")
    ]


# ----------------------------------------------------------------------
# R2 — the defect the review found: a dispatcher without the webhook service
# ----------------------------------------------------------------------


def test_inbox_processor_notification_enqueues_webhook_delivery(
    migrated_database_url: str, tmp_path: Path
) -> None:
    """A stack built without `webhook_delivery_service` passes the test above and
    fails this one — `NotificationDispatcher.webhook_delivery_service` defaults to
    None (`dispatcher.py:26`), so the omission is silent at every other layer."""

    from egp_db.repositories.crawler_agent_repo import create_crawler_agent_repository
    from egp_db.repositories.notification_repo import SqlNotificationRepository

    repository = create_crawler_agent_repository(database_url=migrated_database_url)
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, profile_id = _seed_entitled_tenant(
                cursor, plan_code=PLAN_WITH_NOTIFICATIONS
            )
            job_id = _seed_agent_job(cursor, tenant_id=tenant_id, profile_id=profile_id)
        connection.commit()

    SqlNotificationRepository(
        database_url=migrated_database_url
    ).create_webhook_subscription(
        tenant_id=tenant_id,
        name="u8a-hook",
        url="https://example.invalid/hook",
        notification_types=[NotificationType.NEW_PROJECT],
        signing_secret="u8a-secret",
    )

    _submit_result(
        repository, job_id=job_id, envelope=_discovery_envelope("โครงการเว็บฮุค")
    )
    _drain_once(migrated_database_url, tmp_path)

    assert _webhook_delivery_count(migrated_database_url, tenant_id) == 1


# ----------------------------------------------------------------------
# R4 — control: proves the GATED dispatcher was wired, not the raw one
# ----------------------------------------------------------------------


def test_inbox_processor_notification_is_withheld_without_the_entitlement(
    migrated_database_url: str, tmp_path: Path
) -> None:
    """Declared CONTROL: this passes before the change too (zero notifications
    either way). Its job is to distinguish a *gated* dispatcher from a raw one.
    Non-vacuity comes from the pair — with the entitlement satisfied the first
    test asserts one notification, and withheld this asserts none. No dispatcher
    fails the first test; a raw dispatcher fails this one.
    """

    from egp_db.repositories.crawler_agent_repo import create_crawler_agent_repository

    repository = create_crawler_agent_repository(database_url=migrated_database_url)
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, profile_id = _seed_entitled_tenant(
                cursor, plan_code=PLAN_WITHOUT_NOTIFICATIONS
            )
            job_id = _seed_agent_job(cursor, tenant_id=tenant_id, profile_id=profile_id)
        connection.commit()

    _submit_result(
        repository, job_id=job_id, envelope=_discovery_envelope("โครงการไม่มีสิทธิ์")
    )
    _drain_once(migrated_database_url, tmp_path)

    # The project is still ingested; only the notification is withheld.
    assert _project_count(migrated_database_url, tenant_id) == 1
    assert _notifications_for(migrated_database_url, tenant_id) == []


# ----------------------------------------------------------------------
# R1 — one construction path, two processes
# ----------------------------------------------------------------------


def test_api_and_inbox_processor_build_the_same_notification_stack(
    migrated_database_url: str, tmp_path: Path
) -> None:
    """Construction-path equivalence, stated plainly.

    Object identity is impossible across two processes, so this asserts the
    weaker-but-real property: both call sites resolve to the same builder, and the
    stack it returns is fully assembled (gated wrapper present, and the inner
    dispatcher holding a non-None webhook service).
    """

    import inspect

    from egp_api.bootstrap import notifications as notification_bootstrap
    from egp_api.bootstrap import services as service_bootstrap
    from egp_api.executors import crawler_agent_results
    from egp_api.services.entitlement_service import (
        EntitlementAwareNotificationDispatcher,
    )

    # Both production call sites must reference the shared builder by name.
    assert "build_notification_stack" in inspect.getsource(
        service_bootstrap.configure_services
    )
    assert "build_notification_stack" in inspect.getsource(
        crawler_agent_results.build_crawler_agent_inbox_runtime
    )

    from egp_db.repositories.billing_repo import create_billing_repository
    from egp_db.repositories.discovery_job_repo import create_discovery_job_repository
    from egp_db.repositories.notification_repo import SqlNotificationRepository
    from egp_db.repositories.profile_repo import create_profile_repository
    from egp_db.repositories.run_repo import create_run_repository
    from egp_db.repositories.tenant_entitlement_repo import (
        create_tenant_entitlement_repository,
    )

    stack = notification_bootstrap.build_notification_stack(
        notification_repository=SqlNotificationRepository(
            database_url=migrated_database_url
        ),
        billing_repository=create_billing_repository(
            database_url=migrated_database_url
        ),
        profile_repository=create_profile_repository(
            database_url=migrated_database_url
        ),
        run_repository=create_run_repository(database_url=migrated_database_url),
        discovery_job_repository=create_discovery_job_repository(
            database_url=migrated_database_url
        ),
        tenant_entitlement_repository=create_tenant_entitlement_repository(
            database_url=migrated_database_url
        ),
        smtp_config=None,
        email_sender=None,
    )

    assert isinstance(stack.gated_dispatcher, EntitlementAwareNotificationDispatcher)
    assert stack.notification_dispatcher.webhook_delivery_service is not None


# ----------------------------------------------------------------------
# R6 — no silent degradation back to the U7c behaviour
# ----------------------------------------------------------------------


def test_inbox_runtime_never_builds_an_ingest_service_without_a_dispatcher(
    migrated_database_url: str, tmp_path: Path
) -> None:
    """The U7c failure mode was silence, so this pins the absence of silence.

    A runtime whose `ProjectIngestService` has no dispatcher is exactly the
    behaviour being removed; it must not be reachable by any configuration,
    including an unconfigured SMTP setup (which is a supported production state
    and must NOT downgrade notifications to nothing).
    """

    from egp_api.executors.crawler_agent_results import (
        build_crawler_agent_inbox_runtime,
    )

    runtime = build_crawler_agent_inbox_runtime(
        migrated_database_url, artifact_root=tmp_path
    )
    ingest_service = runtime.processor._project_ingest_service
    assert getattr(ingest_service, "_notification_dispatcher", None) is not None


# ----------------------------------------------------------------------
# recipients: the email channel must still resolve tenant-scoped users
# ----------------------------------------------------------------------


def test_inbox_executor_compose_services_pass_the_smtp_configuration() -> None:
    """Wiring the dispatcher is only half the fix; the container must receive the
    configuration it now reads.

    Compose does **not** pass the env file wholesale — every variable a process
    reads must be enumerated per service (U7c finding C6). If these are absent the
    in-app row and webhook delivery still succeed and only *email* disappears,
    silently. That is the same shape of defect U8a exists to remove, so it gets an
    oracle rather than a comment.

    The existing compose-topology test asserts a fixed list of variables and would
    not catch this; it is deliberately left byte-identical rather than edited, and
    the new requirement is asserted here instead.
    """

    import yaml

    required = {
        "EGP_SMTP_HOST",
        "EGP_SMTP_PORT",
        "EGP_SMTP_USERNAME",
        "EGP_SMTP_PASSWORD",
        "EGP_SMTP_FROM",
        "EGP_SMTP_USE_TLS",
    }
    for compose_name in ("docker-compose.yml", "docker-compose-localdev.yml"):
        compose = yaml.safe_load((REPO_ROOT / compose_name).read_text())
        environment = compose["services"]["crawler-agent-inbox-executor"][
            "environment"
        ]
        missing = required - set(environment)
        assert not missing, f"{compose_name}: {sorted(missing)} missing from the executor"


def test_agent_sourced_notification_emails_only_the_owning_tenants_recipients(
    migrated_database_url: str,
) -> None:
    """Recipient isolation, asserted on the ADDRESSES rather than on row counts.

    An earlier version of this test left SMTP unconfigured and only counted
    tenant-scoped in-app rows — which would have passed even if the resolver had
    returned another tenant's address and production had emailed it. In-app rows
    simply do not carry the recipient list.

    So this drives the shared stack with a capturing email sender and asserts the
    exact address set. The sender is the one injected double in this file, and it
    is injected because observing real SMTP delivery is otherwise unreachable.
    """

    from egp_api.bootstrap.notifications import build_notification_stack
    from egp_db.repositories.billing_repo import create_billing_repository
    from egp_db.repositories.notification_repo import SqlNotificationRepository
    from egp_db.repositories.profile_repo import create_profile_repository

    notification_repository = SqlNotificationRepository(
        database_url=migrated_database_url
    )
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, _ = _seed_entitled_tenant(
                cursor, plan_code=PLAN_WITH_NOTIFICATIONS
            )
            other_tenant_id, _ = _seed_entitled_tenant(
                cursor, plan_code=PLAN_WITH_NOTIFICATIONS
            )
        connection.commit()

    notification_repository.create_user(
        tenant_id=tenant_id, email="owner@example.com", role=UserRole.OWNER
    )
    notification_repository.create_user(
        tenant_id=other_tenant_id, email="intruder@example.com", role=UserRole.OWNER
    )

    delivered: list[str] = []
    stack = build_notification_stack(
        notification_repository=notification_repository,
        billing_repository=create_billing_repository(
            database_url=migrated_database_url
        ),
        profile_repository=create_profile_repository(
            database_url=migrated_database_url
        ),
        smtp_config=None,
        email_sender=lambda *, to, subject, body: delivered.append(to),
    )
    stack.gated_dispatcher.dispatch(
        tenant_id=tenant_id,
        notification_type=NotificationType.NEW_PROJECT,
        # No project_id: `notifications.project_id` carries a real foreign key, and
        # this test is about recipient resolution, not about a project row.
        project_id=None,
        template_vars={"project_name": "โครงการผู้รับ", "organization": "กรมตัวอย่าง"},
    )

    assert delivered == ["owner@example.com"]
    assert _notifications_for(migrated_database_url, other_tenant_id) == []


def test_a_dispatch_failure_after_project_commit_currently_loses_the_notification(
    migrated_database_url: str,
) -> None:
    """Pins a KNOWN GAP, deliberately asserting the defective behaviour.

    `ingest_discovered_project` dispatches only when the pre-upsert lookup found
    no project (`project_ingest.py:68,79`), and the project row commits *before*
    the dispatch. So a dispatch failure is not retried into eventual success: the
    retry finds the project already exists, skips the dispatch, and marks the
    inbox row `applied`. The notification is lost silently.

    This is inherited from `ProjectIngestService` and is shared with the API
    ingest path; U8a does not introduce it, and closing it needs the effect
    ledger / transactional outbox that is scoped as separate work.

    Asserting the real behaviour beats an `xfail`: this test fails loudly if the
    behaviour changes in either direction, and it **must be inverted** by the work
    that closes the gap.

    The raising dispatcher is a double injected to make an otherwise unreachable
    failure reachable — the only such use in this file besides the email sender.
    """

    from egp_api.executors.crawler_agent_results import CrawlerAgentInboxProcessor
    from egp_db.repositories.crawler_agent_repo import create_crawler_agent_repository
    from egp_db.repositories.project_repo import create_project_repository
    from egp_domain.project_ingest import ProjectIngestService

    repository = create_crawler_agent_repository(database_url=migrated_database_url)
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, profile_id = _seed_entitled_tenant(
                cursor, plan_code=PLAN_WITH_NOTIFICATIONS
            )
            job_id = _seed_agent_job(cursor, tenant_id=tenant_id, profile_id=profile_id)
        connection.commit()

    _submit_result(
        repository, job_id=job_id, envelope=_discovery_envelope("โครงการสูญหาย")
    )

    class _FailOnceDispatcher:
        def __init__(self) -> None:
            self.calls = 0

        def dispatch(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated notification backend outage")
            return None

    dispatcher = _FailOnceDispatcher()
    processor = CrawlerAgentInboxProcessor(
        repository=repository,
        project_ingest_service=ProjectIngestService(
            create_project_repository(database_url=migrated_database_url),
            notification_dispatcher=dispatcher,
        ),
        backoff_seconds=0.0,
    )

    first = processor.process_once()
    assert first.retried, f"expected a transient retry, got {first}"

    # `mark_result_retry` floors the backoff at 10ms, so the row is briefly not
    # due. Wait past that rather than racing it.
    time.sleep(0.05)
    second = processor.process_once()
    assert second.applied, f"expected the retry to apply, got {second}"

    # The project was persisted on the FIRST attempt and survives.
    assert _project_count(migrated_database_url, tenant_id) == 1
    # Dispatch was attempted exactly once — the retry skipped it because the
    # project was no longer new. This is the loss window.
    assert dispatcher.calls == 1
    assert _notifications_for(migrated_database_url, tenant_id) == []
