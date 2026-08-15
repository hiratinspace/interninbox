"""SmartRecruiters Posting API adapter.

Endpoint: https://api.smartrecruiters.com/v1/companies/{identifier}/postings
(documented, public, no auth), the enterprise ATS used by many large
companies. Top-level shape is `{"totalFound": N, "content": [...]}` with
offset/limit pagination (limit max 100).

Field notes (verified live):
  - `id` is the stable posting identifier and the path segment of the public
    page: https://jobs.smartrecruiters.com/{identifier}/{id};
  - `name` is the title; `releasedDate` is ISO-8601 (Z-suffixed);
  - `location.fullLocation` is a display string ("Austin, TX, United
    States"); `location.remote` is a boolean;
  - identifiers are matched case-insensitively by the API.

Descriptions require one extra request per posting, so this adapter does not
fetch them (the `content` flag is accepted for signature uniformity and
ignored); sponsorship stays unknown, which the eligibility filters treat as
"keep". Enterprise boards can carry thousands of postings; pagination stops
at MAX_PAGES with a warning rather than hammering the host.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from interninbox import eligibility
from interninbox.fetch import Fetcher
from interninbox.models import AdapterError, Listing

BASE_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
POSTING_URL = "https://jobs.smartrecruiters.com/{slug}/{posting_id}"

RESULTS_PER_PAGE = 100
MAX_PAGES = 10  # 1,000 postings; beyond that we warn instead of hammering

SOURCE = "smartrecruiters"


def fetch(
    fetcher: Fetcher,
    slug: str,
    *,
    content: bool = False,
    warn: Callable[[str], None] = lambda message: None,
) -> list[Listing]:
    listings: list[Listing] = []
    fetched = 0
    total: int | None = None
    for page in range(MAX_PAGES):
        payload = fetcher.get_json(
            BASE_URL.format(slug=slug),
            params={"limit": str(RESULTS_PER_PAGE), "offset": str(page * RESULTS_PER_PAGE)},
        )
        page_listings, total = parse_page(payload, slug)
        listings.extend(page_listings)
        fetched += len(page_listings)
        if not page_listings or (total is not None and fetched >= total):
            break
    if total is not None and fetched < total:
        warn(
            f"{SOURCE}:{slug}: board truncated at {fetched} of {total} postings "
            "(enterprise board; the internship filter still applies to what was fetched)"
        )
    return listings


def parse(payload: object, slug: str) -> list[Listing]:
    listings, _total = parse_page(payload, slug)
    return listings


def parse_page(payload: object, slug: str) -> tuple[list[Listing], int | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
        raise AdapterError(
            f"unexpected SmartRecruiters response shape for {slug!r} (no content array)"
        )
    listings: list[Listing] = []
    for posting in payload["content"]:
        try:
            listings.append(_parse_posting(posting, slug))
        except (KeyError, TypeError) as exc:
            raise AdapterError(
                f"malformed SmartRecruiters posting entry for {slug!r}: {exc}"
            ) from exc
    total = payload.get("totalFound")
    return listings, total if isinstance(total, int) else None


def _parse_posting(posting: dict[str, object], slug: str) -> Listing:
    title = str(posting["name"])

    locations: list[str] = []
    location = posting.get("location")
    if isinstance(location, dict):
        full = str(location.get("fullLocation") or "").strip()
        if full:
            locations.append(full)
        if location.get("remote") and not any(
            "remote" in entry.lower() for entry in locations
        ):
            locations.append("Remote")

    posted_at: dt.datetime | None = None
    released = posting.get("releasedDate")
    if isinstance(released, str) and released:
        try:
            posted_at = dt.datetime.fromisoformat(released.replace("Z", "+00:00"))
        except ValueError:
            posted_at = None

    posting_id = str(posting["id"])
    return Listing(
        company=slug,
        source=SOURCE,
        listing_id=posting_id,
        title=title,
        url=POSTING_URL.format(slug=slug, posting_id=posting_id),
        locations=tuple(locations),
        posted_at=posted_at,
        terms=eligibility.derive_terms(title),
    )
