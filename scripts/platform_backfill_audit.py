"""Audit a keyword backfill against an exact e-GP project-number list."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from egp_db.repositories.project_repo import create_project_repository

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from egp_db.repositories.project_repo import ProjectRecord


LIKELY_EGP_PROJECT_NUMBER_RE = re.compile(r"\b(6[89]\d{5,})\b")
FALLBACK_PROJECT_TOKEN_RE = re.compile(r"^[A-Za-z0-9-]{6,}$")


@dataclass(frozen=True, slots=True)
class ProjectNumberComparison:
    matched: list[str]
    missing: list[str]
    unexpected: list[str]


def extract_expected_project_number(value: str) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    egp_match = LIKELY_EGP_PROJECT_NUMBER_RE.search(normalized)
    if egp_match is not None:
        return egp_match.group(1)
    compact = re.sub(r"\s+", "", normalized)
    if FALLBACK_PROJECT_TOKEN_RE.fullmatch(compact):
        return compact
    return None


def load_expected_project_numbers(
    *,
    expected_values: Sequence[str],
    expected_file: Path | None = None,
) -> tuple[list[str], list[str]]:
    raw_values = list(expected_values)
    if expected_file is not None:
        raw_values.extend(expected_file.read_text(encoding="utf-8").splitlines())

    expected_numbers: list[str] = []
    ignored_values: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        project_number = extract_expected_project_number(raw_value)
        if project_number is None:
            stripped = str(raw_value or "").strip()
            if stripped:
                ignored_values.append(stripped)
            continue
        if project_number in seen:
            continue
        seen.add(project_number)
        expected_numbers.append(project_number)
    return expected_numbers, ignored_values


def compare_project_numbers(
    *,
    expected_numbers: Iterable[str],
    found_numbers: Iterable[str],
) -> ProjectNumberComparison:
    expected = sorted(set(expected_numbers))
    found = sorted(set(found_numbers))
    expected_set = set(expected)
    found_set = set(found)
    return ProjectNumberComparison(
        matched=sorted(expected_set & found_set),
        missing=sorted(expected_set - found_set),
        unexpected=sorted(found_set - expected_set),
    )


def _collect_keyword_projects(
    *,
    database_url: str,
    tenant_id: str,
    keyword: str,
    updated_after: str | None,
    page_size: int,
) -> list[ProjectRecord]:
    repository = create_project_repository(database_url=database_url)
    projects: list[ProjectRecord] = []
    offset = 0
    normalized_page_size = max(1, min(int(page_size), 200))
    while True:
        page = repository.list_projects(
            tenant_id=tenant_id,
            keyword=keyword,
            updated_after=updated_after,
            limit=normalized_page_size,
            offset=offset,
        )
        projects.extend(page.items)
        offset += len(page.items)
        if offset >= page.total or not page.items:
            return projects


def _group_projects_by_number(projects: Sequence[ProjectRecord]) -> dict[str, list[ProjectRecord]]:
    grouped: dict[str, list[ProjectRecord]] = {}
    for project in projects:
        project_number = str(project.project_number or "").strip()
        if not project_number:
            continue
        grouped.setdefault(project_number, []).append(project)
    return grouped


def _print_plaintext_report(
    *,
    keyword: str,
    tenant_id: str,
    updated_after: str | None,
    expected_numbers: Sequence[str],
    ignored_values: Sequence[str],
    comparison: ProjectNumberComparison,
    projects_by_number: dict[str, list[ProjectRecord]],
    projects_without_numbers: int,
) -> None:
    print(f"keyword={keyword}")
    print(f"tenant_id={tenant_id}")
    if updated_after is not None:
        print(f"updated_after={updated_after}")
    print(f"expected_count={len(expected_numbers)}")
    print(f"matched_count={len(comparison.matched)}")
    print(f"missing_count={len(comparison.missing)}")
    print(f"unexpected_count={len(comparison.unexpected)}")
    print(f"ignored_manual_lines={len(ignored_values)}")
    print(f"projects_without_number={projects_without_numbers}")

    if comparison.matched:
        print("\n[matched]")
        for project_number in comparison.matched:
            records = projects_by_number.get(project_number, [])
            project_names = ", ".join(record.project_name for record in records[:3])
            print(f"{project_number} | {project_names}")

    if comparison.missing:
        print("\n[missing]")
        for project_number in comparison.missing:
            print(project_number)

    if comparison.unexpected:
        print("\n[unexpected]")
        for project_number in comparison.unexpected:
            records = projects_by_number.get(project_number, [])
            project_names = ", ".join(record.project_name for record in records[:3])
            print(f"{project_number} | {project_names}")

    duplicate_numbers = sorted(
        project_number
        for project_number, records in projects_by_number.items()
        if len(records) > 1
    )
    if duplicate_numbers:
        print("\n[duplicate_project_numbers]")
        for project_number in duplicate_numbers:
            print(project_number)

    if ignored_values:
        print("\n[ignored_manual_lines]")
        for value in ignored_values:
            print(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Application database URL.")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID to audit.")
    parser.add_argument(
        "--keyword",
        default="แพลตฟอร์ม",
        help="Keyword used for the backfill query.",
    )
    parser.add_argument(
        "--updated-after",
        help="Optional ISO date/datetime lower bound for project updates.",
    )
    parser.add_argument(
        "--expected-project-number",
        action="append",
        default=[],
        help=(
            "Exact e-GP project number, or a freeform line containing one. "
            "Repeat this flag for multiple entries."
        ),
    )
    parser.add_argument(
        "--expected-file",
        type=Path,
        help="Optional text file containing one manual entry per line.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=200,
        help="Internal fetch size for paginated project reads.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the audit report as JSON.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    expected_numbers, ignored_values = load_expected_project_numbers(
        expected_values=args.expected_project_number,
        expected_file=args.expected_file,
    )
    if not expected_numbers:
        parser.error("at least one expected project number is required")

    projects = _collect_keyword_projects(
        database_url=args.database_url,
        tenant_id=args.tenant_id,
        keyword=args.keyword,
        updated_after=args.updated_after,
        page_size=args.page_size,
    )
    projects_by_number = _group_projects_by_number(projects)
    comparison = compare_project_numbers(
        expected_numbers=expected_numbers,
        found_numbers=projects_by_number.keys(),
    )
    projects_without_numbers = sum(
        1 for project in projects if not str(project.project_number or "").strip()
    )

    if args.json:
        print(
            json.dumps(
                {
                    "keyword": args.keyword,
                    "tenant_id": args.tenant_id,
                    "updated_after": args.updated_after,
                    "expected_numbers": expected_numbers,
                    "ignored_manual_lines": ignored_values,
                    "comparison": asdict(comparison),
                    "projects_without_number": projects_without_numbers,
                    "matched_projects": {
                        project_number: [
                            {
                                "project_id": record.id,
                                "project_name": record.project_name,
                                "organization_name": record.organization_name,
                                "last_changed_at": record.last_changed_at,
                            }
                            for record in projects_by_number.get(project_number, [])
                        ]
                        for project_number in comparison.matched
                    },
                    "unexpected_projects": {
                        project_number: [
                            {
                                "project_id": record.id,
                                "project_name": record.project_name,
                                "organization_name": record.organization_name,
                                "last_changed_at": record.last_changed_at,
                            }
                            for record in projects_by_number.get(project_number, [])
                        ]
                        for project_number in comparison.unexpected
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_plaintext_report(
            keyword=args.keyword,
            tenant_id=args.tenant_id,
            updated_after=args.updated_after,
            expected_numbers=expected_numbers,
            ignored_values=ignored_values,
            comparison=comparison,
            projects_by_number=projects_by_number,
            projects_without_numbers=projects_without_numbers,
        )
    return 1 if comparison.missing or comparison.unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
