"""Export the FastAPI OpenAPI schema for frontend contract generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from egp_api.main import create_app

DEFAULT_DATABASE_URL = "sqlite+pysqlite:///:memory:"
DEFAULT_PAYMENT_CALLBACK_SECRET = "openapi-contract-generation-secret"


def build_openapi_schema() -> dict[str, Any]:
    """Build the API OpenAPI schema without requiring local runtime services."""

    app = create_app(
        database_url=DEFAULT_DATABASE_URL,
        payment_callback_secret=DEFAULT_PAYMENT_CALLBACK_SECRET,
        auth_required=False,
        background_runtime_mode="external",
    )
    return app.openapi()


def write_openapi_schema(output_path: Path) -> None:
    """Write a deterministic OpenAPI JSON document to output_path."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_openapi_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the generated OpenAPI JSON schema.",
    )
    args = parser.parse_args()

    write_openapi_schema(args.output)


if __name__ == "__main__":
    main()
