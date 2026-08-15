"""Workable careers-page API adapter.

Endpoint: https://www.workable.com/api/accounts/{slug} (documented, public,
no API key: Workable Help article 115012771647, "Using the Workable API to
create a careers page"). One GET returns the whole board as `{"name": ...,
"description": ..., "jobs": [...]}`; there is no pagination (a 507-job board
answered in a single response), and unknown slugs answer a clean 404.

Field notes (verified live):
  - `shortcode` is the stable job identifier and the path segment of the
    public page https://apply.workable.com/j/{shortcode} (the `url` field);
  - `published_on` is a date-only stamp ("2026-07-30"), no time, no zone;
  - `locations` entries carry city/region/country plus a `hidden` flag, with
    top-level city/state/country as the fallback; `telecommuting` is a bool;
  - with `?details=true` each job gains an HTML `description`; without the
    param the key is absent entirely.

Descriptions inflate multi-hundred-job boards to several MB, so they follow
the Greenhouse pattern: opt-in via `content=True`, with a wider size cap.
`employment_type` is NOT an internship signal (live intern postings carried
"Full-time" and "Contract"), so title heuristics stay the filter path.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from interninbox import eligibility
from interninbox.fetch import Fetcher
from interninbox.models import AdapterError, Listing

BASE_URL = "https://www.workable.com/api/accounts/{slug}"
POSTING_URL = "https://apply.workable.com/j/{shortcode}"

SOURCE = "workable"

# Same rationale as Greenhouse: description-laden boards outgrow the default
# response cap, so `content=True` fetches get a wider one.
CONTENT_MAX_BYTES = 30_000_000


def fetch(
    fetcher: Fetcher,
    slug: str,
    *,
    content: bool = False,
    warn: Callable[[str], None] = lambda message: None,
) -> list[Listing]:
    if content:
        payload = fetcher.get_json(
            BASE_URL.format(slug=slug),
            params={"details": "true"},
            max_response_bytes=CONTENT_MAX_BYTES,
        )
    else:
        payload = fetcher.get_json(BASE_URL.format(slug=slug))
    return parse(payload, slug)


def parse(payload: object, slug: str) -> list[Listing]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise AdapterError(f"unexpected Workable response shape for {slug!r} (no jobs array)")
    board_name = payload.get("name")
    company = board_name.strip() if isinstance(board_name, str) and board_name.strip() else slug
    listings: list[Listing] = []
    for job in payload["jobs"]:
        try:
            listings.append(_parse_job(job, slug, company))
        except (KeyError, TypeError) as exc:
            raise AdapterError(f"malformed Workable job entry for {slug!r}: {exc}") from exc
    return listings


def _parse_job(job: dict[str, object], slug: str, company: str) -> Listing:
    title = str(job["title"])
    shortcode = str(job["shortcode"])
    url = str(job.get("url") or POSTING_URL.format(shortcode=shortcode))

    locations = _locations(job)

    # `published_on` is date-only ("2026-07-30"); a naive stamp is treated
    # as UTC downstream (freshness.py, output.py).
    posted_at: dt.datetime | None = None
    published = job.get("published_on")
    if isinstance(published, str) and published:
        try:
            posted_at = dt.datetime.fromisoformat(published)
        except ValueError:
            posted_at = None

    # Present only with ?details=true; plain HTML (not escaped).
    sponsorship = evidence = None
    description = job.get("description")
    if isinstance(description, str) and description:
        sponsorship, evidence = eligibility.classify_sponsorship_with_evidence(
            eligibility.text_from_html(description)
        )

    return Listing(
        company=company,
        source=SOURCE,
        listing_id=shortcode,
        title=title,
        url=url,
        locations=locations,
        posted_at=posted_at,
        # `company` is the board's mutable display name, so pin the state key
        # to the slug (the USAJOBS pattern).
        identity=f"{SOURCE}:{slug}:{shortcode}",
        sponsorship=sponsorship,
        sponsorship_evidence=evidence,
        terms=eligibility.derive_terms(title),
    )


def _locations(job: dict[str, object]) -> tuple[str, ...]:
    locations: list[str] = []
    raw = job.get("locations")
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict) or entry.get("hidden"):
                continue
            joined = _join(entry.get(key) for key in ("city", "region", "country"))
            if joined and joined not in locations:
                locations.append(joined)
    if not locations:
        joined = _join(job.get(key) for key in ("city", "state", "country"))
        if joined:
            locations.append(joined)
    if job.get("telecommuting") and not any("remote" in entry.lower() for entry in locations):
        locations.append("Remote")
    return tuple(locations)


def _join(parts: object) -> str:
    cleaned = [str(part).strip() for part in parts if part is not None and str(part).strip()]
    return ", ".join(cleaned)
