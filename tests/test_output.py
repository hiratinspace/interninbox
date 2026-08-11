"""Output rendering: table, JSON, Markdown, sorting, summary."""

import datetime as dt
import json

from conftest import make_listing

from interninbox.models import ScanResult
from interninbox.output import format_json, format_markdown, format_table, sort_listings


def _dt(day: int) -> dt.datetime:
    return dt.datetime(2026, 8, day, tzinfo=dt.UTC)


def _result() -> ScanResult:
    return ScanResult(
        listings=[
            make_listing(listing_id="1", title="Older Intern", posted_at=_dt(1)),
            make_listing(listing_id="2", title="Undated Intern", posted_at=None),
            make_listing(listing_id="3", title="Newest Intern", posted_at=_dt(9)),
        ],
        companies_scanned=2,
        companies_failed=1,
    )


def test_sort_newest_first_undated_last() -> None:
    titles = [listing.title for listing in sort_listings(_result().listings)]
    assert titles == ["Newest Intern", "Older Intern", "Undated Intern"]


def test_table_has_header_rows_and_summary() -> None:
    text = format_table(_result())
    lines = text.splitlines()
    assert lines[0].startswith("COMPANY") and "TITLE" in lines[0]
    assert "Newest Intern" in lines[1]
    assert lines[-1] == "3 internships across 2 companies (1 company failed)"
    # Columns align: TITLE starts at the same offset in every row.
    offset = lines[0].index("TITLE")
    assert all(line[offset] != " " for line in lines[1:4])


def test_table_empty_result() -> None:
    result = ScanResult(companies_scanned=3)
    text = format_table(result)
    assert "No matching internships found." in text
    assert "0 internships across 3 companies" in text


def test_table_truncates_long_locations() -> None:
    result = ScanResult(
        listings=[make_listing(locations=("A really extremely long location name " * 3,))],
        companies_scanned=1,
    )
    row = format_table(result).splitlines()[1]
    assert "…" in row


def test_json_output_shape() -> None:
    payload = json.loads(format_json(_result()))
    assert payload["summary"] == {
        "internships": 3,
        "companies_scanned": 2,
        "companies_failed": 1,
    }
    first = payload["listings"][0]
    assert first["title"] == "Newest Intern"
    assert first["posted_at"] == "2026-08-09T00:00:00+00:00"
    assert first["url"].startswith("https://")


def test_markdown_output() -> None:
    text = format_markdown(_result())
    lines = text.splitlines()
    assert lines[0].startswith("| Company | Title |")
    assert lines[2].count("|") == 6
    assert "[apply](" in lines[2]
    assert lines[-1].startswith("3 internships")
