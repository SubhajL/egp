"""Regression: every service must receive the env vars it actually reads.

Found by deploying to production. `EGP_CRAWLER_AGENT_PROTOCOL` was enumerated for
`crawler-agent-inbox-executor` but **not** for `api` — and the API is the service
that serves the V1 agent endpoints and derives `delivery_mode` from that flag.

Compose does not pass the env file wholesale (U7c finding C6), so the API always
read `off`: the endpoints would 404 forever and shadow could never be enabled, no
matter what `/etc/egp/egp.env` said. Setting the variable on the host looked like
it worked and changed nothing.

This asserts the pairing directly rather than trusting a per-service checklist,
because the checklist is what missed it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ("docker-compose.yml", "docker-compose-localdev.yml")

# (variable, services that READ it at runtime)
REQUIRED_BY_SERVICE = (
    ("EGP_CRAWLER_AGENT_PROTOCOL", ("api", "crawler-agent-inbox-executor")),
    ("EGP_CRAWLER_AGENT_INBOX_STALE_AFTER_SECONDS", ("api",)),
    ("EGP_CRAWLER_AGENT_INBOX_PROCESSOR_ID", ("crawler-agent-inbox-executor",)),
)


@pytest.mark.parametrize("compose_name", COMPOSE_FILES)
@pytest.mark.parametrize(("variable", "services"), REQUIRED_BY_SERVICE)
def test_each_service_receives_the_crawler_agent_vars_it_reads(
    compose_name: str, variable: str, services: tuple[str, ...]
) -> None:
    compose = yaml.safe_load((REPO_ROOT / compose_name).read_text(encoding="utf-8"))
    for service in services:
        environment = compose["services"][service].get("environment", {})
        assert variable in environment, (
            f"{compose_name}: {service} reads {variable} but compose does not "
            "pass it — compose does not forward the env file wholesale"
        )
