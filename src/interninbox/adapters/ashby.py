"""Ashby Job Board API adapter.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{slug}
(documented, public, no auth). Top-level shape is `{"jobs": [...]}`.

Field notes:
  - `id` is a stable UUID string;
  - `jobUrl` is the public posting page (`applyUrl` also exists);
  - `location` is a single free-text string; `workplaceType` is one of
    "Remote"/"Hybrid"/"OnSite";
  - `publishedAt` is an ISO-8601 timestamp.
"""

from __future__ import annotations

import datetime as dt

from interninbox.fetch import Fetcher
from interninbox.models import AdapterError, Listing

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

SOURCE = "ashby"


def fetch(fetcher: Fetcher, slug: str) -> list[Listing]:
    payload = fetcher.get_json(BASE_URL.format(slug=slug))
    return parse(payload, slug)


def parse(payload: object, slug: str) -> list[Listing]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise AdapterError(f"unexpected Ashby response shape for {slug!r} (no jobs array)")
    listings: list[Listing] = []
    for job in payload["jobs"]:
        try:
            listings.append(_parse_job(job, slug))
        except (KeyError, TypeError) as exc:
            raise AdapterError(f"malformed Ashby job entry for {slug!r}: {exc}") from exc
    return listings


def _parse_job(job: dict[str, object], slug: str) -> Listing:
    locations: tuple[str, ...] = ()
    location = job.get("location")
    if location:
        locations = (str(location),)
    workplace_type = job.get("workplaceType")
    if isinstance(workplace_type, str) and workplace_type.lower() == "remote":
        if not any("remote" in entry.lower() for entry in locations):
            locations = (*locations, "Remote")

    posted_at: dt.datetime | None = None
    published_at = job.get("publishedAt")
    if isinstance(published_at, str) and published_at:
        try:
            posted_at = dt.datetime.fromisoformat(published_at)
        except ValueError:
            posted_at = None

    return Listing(
        company=slug,
        source=SOURCE,
        listing_id=str(job["id"]),
        title=str(job["title"]),
        url=str(job["jobUrl"]),
        locations=locations,
        posted_at=posted_at,
    )
