"""Release declarations for shared artifact parsers and audited minimum versions."""

from __future__ import annotations

from pathlib import Path
import tomllib

from packaging.version import Version
import pytest

ROOT = Path(__file__).resolve().parents[2]
PARSERS = [("pypdf", "6.14.2"), ("defusedxml", "0.7.1")]
SECURITY_MINIMUMS = [
    ("certifi", "2026.10.18"),
    ("multidict", "6.9.1"),
    ("pyjwt", "2.15.0"),
    ("urllib3", "2.8.0"),
]


@pytest.mark.parametrize("name,version", PARSERS)
def test_validator_parser_is_an_exact_root_runtime_dependency(
    name: str, version: str
) -> None:
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert f"{name}=={version}" in manifest["project"]["dependencies"], (
        "parser must be directly declared by the owning shared distribution"
    )


@pytest.mark.parametrize("name,version", PARSERS)
def test_validator_parser_has_exact_release_lock_record(
    name: str, version: str
) -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    matches = [record for record in lock["package"] if record["name"] == name]
    assert len(matches) == 1
    assert matches[0]["version"] == version


def test_release_lock_root_metadata_declares_both_parsers() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    root = next(
        record for record in lock["package"] if record["name"] == "egp-monorepo"
    )
    requirements = {
        (record["name"], record.get("specifier"))
        for record in root["metadata"]["requires-dist"]
    }
    assert {(name, f"=={version}") for name, version in PARSERS} <= requirements


@pytest.mark.parametrize("name,minimum", SECURITY_MINIMUMS)
def test_release_lock_meets_baseline_security_minimum(name: str, minimum: str) -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    matches = [record for record in lock["package"] if record["name"] == name]
    assert len(matches) == 1
    assert Version(matches[0]["version"]) >= Version(minimum)
