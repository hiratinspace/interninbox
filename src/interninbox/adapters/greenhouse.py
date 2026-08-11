"""Greenhouse Job Board API adapter.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
(documented, public, no auth). Top-level shape is `{"jobs": [...]}`.

Field notes:
  - `id` is the stable per-posting identifier (it is the path segment in
    `absolute_url`); `requisition_id` is free text and sometimes blank.
  - `location.name` is a single string — the one-element locations list.
  - `first_published` is an ISO-8601 timestamp.
"""

from __future__ import annotations

import datetime as dt

from interninbox.fetch import Fetcher
from interninbox.models import AdapterError, Listing

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

SOURCE = "greenhouse"


def fetch(fetcher: Fetcher, slug: str) -> list[Listing]:
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

    return Listing(
        company=slug,
        source=SOURCE,
        listing_id=str(job["id"]),
        title=str(job["title"]),
        url=str(job["absolute_url"]),
        locations=locations,
        posted_at=posted_at,
    )
