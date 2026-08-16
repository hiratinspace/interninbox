"""Greenhouse Job Board API adapter.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
(documented, public, no auth). Top-level shape is `{"jobs": [...]}`.

Field notes:
  - `id` is the stable per-posting identifier (it is the path segment in
    `absolute_url`); `requisition_id` is free text and sometimes blank.
  - `location.name` is a single string, the one-element locations list.
  - `first_published` is an ISO-8601 timestamp.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from interninbox import eligibility
from interninbox.fetch import Fetcher
from interninbox.models import AdapterError, Listing

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

SOURCE = "greenhouse"


# Descriptions inflate big boards to several MB, so they are opt-in and get
# a wider per-call size cap.
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
            params={"content": "true"},
            max_response_bytes=CONTENT_MAX_BYTES,
        )
    else:
        payload = fetcher.get_json(BASE_URL.format(slug=slug))
    return parse(payload, slug)


def parse(payload: object, slug: str) -> list[Listing]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise AdapterError(f"unexpected Greenhouse response shape for {slug!r} (no jobs array)")
    listings: list[Listing] = []
    for job in payload["jobs"]:
        try:
            listings.append(_parse_job(job, slug))
        except (KeyError, TypeError) as exc:
            raise AdapterError(f"malformed Greenhouse job entry for {slug!r}: {exc}") from exc
    return listings


def _parse_job(job: dict[str, object], slug: str) -> Listing:
    location = job.get("location")
    locations: tuple[str, ...] = ()
    if isinstance(location, dict) and location.get("name"):
        locations = (str(location["name"]),)

    posted_at: dt.datetime | None = None
    first_published = job.get("first_published")
    if isinstance(first_published, str) and first_published:
        try:
            posted_at = dt.datetime.fromisoformat(first_published)
        except ValueError:
            posted_at = None

    title = str(job["title"])
    # `content` is present only when fetched with content=true; it arrives
    # HTML-escaped ("&lt;p&gt;...").
    sponsorship = evidence = None
    raw_content = job.get("content")
    if isinstance(raw_content, str) and raw_content:
        sponsorship, evidence = eligibility.classify_sponsorship_with_evidence(
            eligibility.text_from_html(raw_content, escaped=True)
        )

    return Listing(
        company=slug,
        source=SOURCE,
        listing_id=str(job["id"]),
        title=title,
        url=str(job["absolute_url"]),
        locations=locations,
        posted_at=posted_at,
        sponsorship=sponsorship,
        sponsorship_evidence=evidence,
        terms=eligibility.derive_terms(title),
    )
