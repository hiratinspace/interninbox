"""schema.org JobPosting extraction from embedded JSON-LD.

The standards route to company career sites: many job pages embed a
schema.org `JobPosting` object inside `<script type="application/ld+json">`
blocks (it is how search engines index jobs), so a page that publishes one
is readable without any private API. This module is pure: HTML in, postings
or Listings out; all fetching stays in the website adapter.

Tolerance rules: one malformed script block never hides a valid one; a
posting may sit at the top level, inside an array, or inside an `@graph`
wrapper; `@type` may be a string or a list. Anything without a title is
unusable and maps to None; a posting past its `validThrough` is expired and
maps to None; every other missing field just stays unset.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse

from interninbox import eligibility
from interninbox.models import Listing

SOURCE = "website"

_SCRIPT_BLOCK = re.compile(
    r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def extract_job_postings(html: str) -> list[dict]:
    """Every JobPosting object embedded in `html` as JSON-LD, page order."""
    postings: list[dict] = []
    for match in _SCRIPT_BLOCK.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except (ValueError, RecursionError):
            continue  # one broken block never hides the others
        for node in _flatten(payload):
            if _is_job_posting(node):
                postings.append(node)
    return postings


def _flatten(payload: object) -> list[dict]:
    """Candidate nodes in a parsed block: object, array, or @graph members."""
    if isinstance(payload, list):
        nodes: list[dict] = []
        for item in payload:
            nodes.extend(_flatten(item))
        return nodes
    if isinstance(payload, dict):
        graph = payload.get("@graph")
        if isinstance(graph, list):
            return [node for node in graph if isinstance(node, dict)]
        return [payload]
    return []


def _is_job_posting(node: dict) -> bool:
    kind = node.get("@type")
    if isinstance(kind, str):
        return kind == "JobPosting"
    if isinstance(kind, list):
        return "JobPosting" in kind
    return False


def normalize_page_url(url: str) -> str:
    """Stable page identity: host lowercased, query and fragment dropped."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, "", "")
    )


def posting_to_listing(data: dict, page_url: str, domain: str) -> Listing | None:
    """Map one JobPosting object to a Listing, or None when unusable.

    None means no title (nothing to show) or a posting past `validThrough`
    (expired). An unparseable `validThrough` keeps the listing: unknown
    never drops anything.
    """
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    if _expired(data.get("validThrough")):
        return None

    sponsorship = evidence = None
    description = data.get("description")
    if isinstance(description, str) and description.strip():
        sponsorship, evidence = eligibility.classify_sponsorship_with_evidence(
            eligibility.text_from_html(description)
        )

    title = title.strip()
    normalized = normalize_page_url(page_url)
    return Listing(
        company=domain,
        source=SOURCE,
        listing_id=normalized,
        title=title,
        url=page_url,
        locations=_locations(data),
        posted_at=_parse_datetime(data.get("datePosted")),
        identity=f"{SOURCE}:{normalized}",
        sponsorship=sponsorship,
        sponsorship_evidence=evidence,
        terms=eligibility.derive_terms(title),
        employment_intern=_employment_intern(data.get("employmentType")),
    )


def _parse_datetime(value: object) -> dt.datetime | None:
    """An ISO date or datetime as an aware datetime, else None (never guess)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def _expired(valid_through: object) -> bool:
    deadline = _parse_datetime(valid_through)
    return deadline is not None and deadline < dt.datetime.now(dt.UTC)


def _locations(data: dict) -> tuple[str, ...]:
    """`jobLocation` (object or list of Places) joined per entry, plus
    Remote when `jobLocationType` says TELECOMMUTE."""
    locations: list[str] = []
    raw = data.get("jobLocation")
    entries = raw if isinstance(raw, list) else [raw]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        address = entry.get("address")
        if not isinstance(address, dict):
            continue
        parts = (
            address.get("addressLocality"),
            address.get("addressRegion"),
            _country(address.get("addressCountry")),
        )
        joined = ", ".join(
            str(part).strip() for part in parts if part is not None and str(part).strip()
        )
        if joined and joined not in locations:
            locations.append(joined)
    location_type = data.get("jobLocationType")
    if isinstance(location_type, str) and location_type.strip().upper() == "TELECOMMUTE":
        if not any("remote" in location.lower() for location in locations):
            locations.append("Remote")
    return tuple(locations)


def _country(value: object) -> object:
    """`addressCountry` is a plain string or a Country object with a name."""
    if isinstance(value, dict):
        return value.get("name")
    return value


def _employment_intern(value: object) -> bool:
    """True when `employmentType` (string or list) declares an internship."""
    values = value if isinstance(value, list) else [value]
    return any(isinstance(item, str) and "INTERN" in item.upper() for item in values)
