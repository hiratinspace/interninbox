"""Render scan results: aligned plain-text table (default), JSON, Markdown."""

from __future__ import annotations

import datetime as dt
import json
import unicodedata

from interninbox.models import Listing, ScanResult

_MAX_LOCATIONS_WIDTH = 40
_MAX_TITLE_WIDTH = 60


def sort_listings(listings: list[Listing]) -> list[Listing]:
    """Newest first where dates exist; undated listings follow, in fetch order."""
    dated = [listing for listing in listings if listing.posted_at is not None]
    undated = [listing for listing in listings if listing.posted_at is None]
    dated.sort(key=_posted_utc, reverse=True)
    return dated + undated


def _posted_utc(listing: Listing) -> dt.datetime:
    posted = listing.posted_at
    assert posted is not None
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=dt.UTC)
    return posted


def _clean(text: str) -> str:
    """Drop control/format characters from untrusted board text.

    Board JSON is arbitrary third-party data; ANSI/OSC escapes, C0/C1
    controls, bidi overrides, and zero-width characters (categories Cc/Cf)
    must never reach the terminal or a pasted markdown table.
    """
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf"))


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _row(listing: Listing) -> tuple[str, str, str, str, str]:
    locations = ", ".join(_clean(entry) for entry in listing.locations) or "-"
    posted = listing.posted_at.date().isoformat() if listing.posted_at else "-"
    return (
        _clean(listing.company),
        _truncate(_clean(listing.title), _MAX_TITLE_WIDTH),
        _truncate(locations, _MAX_LOCATIONS_WIDTH),
        posted,
        _clean(listing.url),
    )


def summary_line(result: ScanResult) -> str:
    count = len(result.listings)
    noun = "internship" if count == 1 else "internships"
    line = f"{count} {noun} across {result.companies_scanned} companies"
    if result.companies_failed:
        failed_noun = "company" if result.companies_failed == 1 else "companies"
        line += f" ({result.companies_failed} {failed_noun} failed)"
    return line


def format_table(result: ScanResult) -> str:
    listings = sort_listings(result.listings)
    if not listings:
        return "No matching internships found.\n" + summary_line(result)
    header = ("COMPANY", "TITLE", "LOCATIONS", "POSTED", "URL")
    rows = [_row(listing) for listing in listings]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(4)]
    lines = []
    for row in [header, *rows]:
        padded = [row[i].ljust(widths[i]) for i in range(4)]
        lines.append("  ".join([*padded, row[4]]).rstrip())
    lines.append("")
    lines.append(summary_line(result))
    return "\n".join(lines)


def format_json(result: ScanResult) -> str:
    listings = sort_listings(result.listings)
    payload = {
        "listings": [
            {
                "company": listing.company,
                "source": listing.source,
                "id": listing.listing_id,
                "title": listing.title,
                "locations": list(listing.locations),
                "posted_at": listing.posted_at.isoformat() if listing.posted_at else None,
                "url": listing.url,
            }
            for listing in listings
        ],
        "summary": {
            "internships": len(listings),
            "companies_scanned": result.companies_scanned,
            "companies_failed": result.companies_failed,
        },
    }
    return json.dumps(payload, indent=2)


def _md_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _md_url(url: str) -> str:
    return url.replace("(", "%28").replace(")", "%29")


def format_markdown(result: ScanResult) -> str:
    listings = sort_listings(result.listings)
    lines = ["| Company | Title | Locations | Posted | Link |", "| --- | --- | --- | --- | --- |"]
    for listing in listings:
        company, title, locations, posted, url = _row(listing)
        lines.append(
            f"| {_md_escape(company)} | {_md_escape(title)} | {_md_escape(locations)} "
            f"| {posted} | [apply]({_md_url(url)}) |"
        )
    lines.append("")
    lines.append(summary_line(result))
    return "\n".join(lines)
