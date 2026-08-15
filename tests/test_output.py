"""Output rendering: table, JSON, Markdown, sorting, summary."""

import datetime as dt
import json
import unicodedata

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
        listings_checked=3,
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
        "listings_checked": 3,
        "sources_scanned": 0,
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


def test_table_strips_ansi_and_control_chars() -> None:
    result = ScanResult(
        listings=[
            make_listing(
                title="Intern\x1b]0;pwned\x07 \x1b[31mRed\x1b[0m",
                company="acme\x9bevil",
                locations=("New\nYork", "SF\rBay"),
            )
        ],
        companies_scanned=1,
    )
    text = format_table(result)
    assert "\x1b" not in text
    assert "\x07" not in text
    assert "\x9b" not in text
    assert "\r" not in text
    # A newline smuggled inside a location must not create an extra row.
    assert len(text.splitlines()) == 4  # header, one row, blank, summary


def test_markdown_strips_ansi_and_escapes_link_syntax() -> None:
    result = ScanResult(
        listings=[
            make_listing(
                title="\x1b[31m[click me](https://evil.test)",
                company="ac|me",
                url="https://boards.example.test/jobs/1)?tracking=(x",
            )
        ],
        companies_scanned=1,
    )
    text = format_markdown(result)
    assert "\x1b" not in text
    # Title cannot forge a markdown link.
    assert "[click me](https://evil.test)" not in text
    # Company pipes are escaped like title pipes already are.
    assert "ac\\|me" in text
    # A ')' in the URL cannot terminate the [apply](...) link early.
    row = text.splitlines()[2]
    assert "[apply](https://boards.example.test/jobs/1%29?tracking=%28x)" in row


def test_empty_table_explains_filters_matched_none() -> None:
    result = ScanResult(companies_scanned=3, listings_checked=57)
    text = format_table(result)
    assert "57 listings checked" in text


def test_empty_table_explains_empty_boards() -> None:
    result = ScanResult(companies_scanned=3, listings_checked=0)
    text = format_table(result)
    assert "no jobs at all" in text


def test_empty_table_explains_nothing_new() -> None:
    result = ScanResult(companies_scanned=1, listings_checked=10, listings_matched=4)
    text = format_table(result)
    assert "already seen" in text


def _display_col(line: str, marker: str) -> int:
    """Visual column (terminal cells) where `marker` starts in `line`."""
    prefix = line[: line.index(marker)]
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in prefix)


def test_table_aligns_columns_by_display_width_for_wide_chars() -> None:
    # A CJK company name (each glyph is 2 cells wide) must not push the TITLE
    # column out of visual alignment relative to an ASCII row.
    result = ScanResult(
        listings=[
            make_listing(company="东京公司", title="Intern A", listing_id="1"),
            make_listing(company="acme", title="Intern B", listing_id="2"),
        ],
        companies_scanned=1,
    )
    lines = format_table(result).splitlines()
    header, wide_row, ascii_row = lines[0], lines[1], lines[2]
    # "Intern A"/"Intern B" begin at the same terminal cell in both rows,
    # and at the header's TITLE column.
    assert _display_col(wide_row, "Intern") == _display_col(ascii_row, "Intern")
    assert _display_col(ascii_row, "Intern") == _display_col(header, "TITLE")


def test_truncate_counts_display_width_not_codepoints() -> None:
    # 40 double-width glyphs = 80 cells; must be truncated to fit the column.
    wide = "西" * 40
    result = ScanResult(listings=[make_listing(locations=(wide,))], companies_scanned=1)
    row = format_table(result).splitlines()[1]
    assert "…" in row


def test_json_includes_eligibility_metadata() -> None:
    result = ScanResult(
        listings=[
            make_listing(
                sponsorship="offers-sponsorship",
                terms=("Summer 2027",),
            )
        ],
        companies_scanned=1,
    )
    item = json.loads(format_json(result))["listings"][0]
    assert item["sponsorship"] == "offers-sponsorship"
    assert item["terms"] == ["Summer 2027"]


def test_table_hyperlinks_wrap_urls_only_when_asked() -> None:
    result = ScanResult(listings=[make_listing()], companies_scanned=1)
    plain = format_table(result)
    assert "\x1b]8;;" not in plain
    linked = format_table(result, hyperlinks=True)
    assert "\x1b]8;;https://boards.example-greenhouse.test" in linked
    # Every open hyperlink is closed, nothing leaks past the row.
    assert linked.count("\x1b]8;;") == 2 * len(result.listings)
