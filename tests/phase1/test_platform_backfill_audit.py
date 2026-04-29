from __future__ import annotations

from scripts.platform_backfill_audit import (
    compare_project_numbers,
    extract_expected_project_number,
    load_expected_project_numbers,
)


def test_extract_expected_project_number_prefers_egp_number_over_list_prefix() -> None:
    assert (
        extract_expected_project_number("1. แพลตฟอร์มข้อมูลสุขภาพ เลขที่โครงการ 69010000009")
        == "69010000009"
    )
    assert extract_expected_project_number("2) 68020000077") == "68020000077"
    assert extract_expected_project_number("3") is None


def test_load_expected_project_numbers_dedupes_and_tracks_ignored_lines(tmp_path) -> None:
    expected_file = tmp_path / "expected.txt"
    expected_file.write_text(
        "\n".join(
            [
                "1. 69010000009",
                "2. 69010000009",
                "แพลตฟอร์ม 68020000077",
                "3",
            ]
        ),
        encoding="utf-8",
    )

    expected_numbers, ignored_values = load_expected_project_numbers(
        expected_values=["69030000088"],
        expected_file=expected_file,
    )

    assert expected_numbers == ["69030000088", "69010000009", "68020000077"]
    assert ignored_values == ["3"]


def test_compare_project_numbers_reports_missing_and_unexpected() -> None:
    comparison = compare_project_numbers(
        expected_numbers=["69010000009", "68020000077"],
        found_numbers=["69010000009", "69030000088", "69030000088"],
    )

    assert comparison.matched == ["69010000009"]
    assert comparison.missing == ["68020000077"]
    assert comparison.unexpected == ["69030000088"]
