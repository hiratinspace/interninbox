"""Lever Postings API adapter.

Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json
(documented, public, no auth). Top-level shape is a bare JSON array.

Field notes:
  - the title field is called `text`;
  - `hostedUrl` is the public posting page (preferred over `applyUrl` for
    display);
  - `categories.location` is a single string;
  - `categories.allLocations` (when present) supersedes the single
    `categories.location`.
  - `createdAt` is epoch *milliseconds*.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from interninbox import eligibility
from interninbox.fetch import Fetcher
from interninbox.models import AdapterError, Listing

BASE_URL = "https://api.lever.co/v0/postings/{slug}"

# Descriptions ride along in every response, so big boards routinely
# exceed the default cap (OpenAI's Ashby board did, live).
BOARD_MAX_BYTES = 30_000_000

SOURCE = "lever"


def fetch(
    fetcher: Fetcher,
    slug: str,
    *,
    content: bool = False,
    warn: Callable[[str], None] = lambda message: None,
) -> list[Listing]:
    # `content` is accepted for adapter-signature uniformity; Lever includes
    # descriptions in every response, so classification is always on.
    payload = fetcher.get_json(
        BASE_URL.format(slug=slug), params={"mode": "json"}, max_response_bytes=BOARD_MAX_BYTES
    )
    return parse(payload, slug)


def parse(payload: object, slug: str) -> list[Listing]:
    if not isinstance(payload, list):
        raise AdapterError(f"unexpected Lever response shape for {slug!r} (not a JSON array)")
    listings: list[Listing] = []
    for posting in payload:
        try:
            listings.append(_parse_posting(posting, slug))
        except (KeyError, TypeError) as exc:
            raise AdapterError(f"malformed Lever posting entry for {slug!r}: {exc}") from exc
    return listings


def _parse_posting(posting: dict[str, object], slug: str) -> Listing:
    locations: list[str] = []
    categories = posting.get("categories")
    if isinstance(categories, dict):
        raw_all = categories.get("allLocations")
        if isinstance(raw_all, list):
            for entry in raw_all:
                if isinstance(entry, str) and entry and entry not in locations:
                    locations.append(entry)
        if not locations and categories.get("location"):
            locations.append(str(categories["location"]))
    workplace_type = posting.get("workplaceType")
    if isinstance(workplace_type, str) and workplace_type.lower() == "remote":
        if not any("remote" in location.lower() for location in locations):
            locations.append("Remote")

    posted_at: dt.datetime | None = None
    created_at = posting.get("createdAt")
    if isinstance(created_at, int | float) and not isinstance(created_at, bool):
        posted_at = dt.datetime.fromtimestamp(created_at / 1000, tz=dt.UTC)

    title = str(posting["text"])
    description = posting.get("descriptionPlain") or posting.get("description") or ""
    sponsorship, evidence = eligibility.classify_sponsorship_with_evidence(str(description))

    return Listing(
        company=slug,
        source=SOURCE,
        listing_id=str(posting["id"]),
        title=title,
        url=str(posting["hostedUrl"]),
        locations=tuple(locations),
        posted_at=posted_at,
        sponsorship=sponsorship,
        sponsorship_evidence=evidence,
        terms=eligibility.derive_terms(title),
    )
