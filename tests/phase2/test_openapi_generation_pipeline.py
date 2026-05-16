from __future__ import annotations

import json
from pathlib import Path

from scripts.export_openapi_schema import build_openapi_schema, write_openapi_schema


def test_build_openapi_schema_uses_the_packaged_api_contract() -> None:
    schema = build_openapi_schema()

    assert schema["openapi"] == "3.1.0"
    assert schema["info"]["title"] == "e-GP Intelligence Platform"
    assert "/v1/projects" in schema["paths"]
    assert "/v1/documents/projects/{project_id}" in schema["paths"]
    assert "/v1/rules" in schema["paths"]


def test_write_openapi_schema_is_deterministic(tmp_path: Path) -> None:
    first_path = tmp_path / "first" / "openapi.json"
    second_path = tmp_path / "second" / "openapi.json"

    write_openapi_schema(first_path)
    write_openapi_schema(second_path)

    first_output = first_path.read_text(encoding="utf-8")
    second_output = second_path.read_text(encoding="utf-8")

    assert first_output == second_output
    assert first_output.endswith("\n")
    assert json.loads(first_output)["paths"]["/v1/projects"]
