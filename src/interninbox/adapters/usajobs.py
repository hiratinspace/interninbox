"""USAJOBS Search API adapter (optional, off unless configured).

Endpoint: https://data.usajobs.gov/api/search, the official federal API.
Unlike the ATS adapters this one requires a (free) API key, and its
documented authentication contract is two headers plus the URL-derived
Host: `User-Agent` set to the email address the key was registered under,
and `Authorization-Key`. That is why this adapter does NOT send this tool's
normal User-Agent: the vendor's own contract for this API is that the UA
*is* the registered email.

Query: `HiringPath=student`, USAJOBS's hiring-path filter for the Pathways
Internship Program (currently enrolled students), plus any user-configured
`Keyword`. Results are paginated (`ResultsPerPage` max 500) and capped at a
conservative page limit; results still pass through the same local
internship filter as every other source.

Field notes (from the published response schema):
  - `MatchedObjectId` is the announcement's Control Number, its stable
    identity and the key of its canonical URL;
  - `PositionURI` is the announcement page; `ApplyURI` is an array;
  - `PositionLocation[].LocationName` are the duty stations;
  - `PublicationStartDate` is an ISO-8601 timestamp (sample is Z-suffixed).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from interninbox.config import UsaJobsConfig
from interninbox.fetch import Fetcher
from interninbox.models import AdapterError, Listing

SEARCH_URL = "https://data.usajobs.gov/api/search"

RESULTS_PER_PAGE = 500
MAX_PAGES = 5  # conservative cap; 2500 announcements is far beyond any intern search

SOURCE = "usajobs"
COMPANY_LABEL = "usajobs"


def _headers(api_key: str, email: str) -> dict[str, str]:
    # The documented auth contract: the User-Agent IS the registered email.
    # Host is NOT set by hand, httpx derives it from the URL, so a redirect
    # can never carry a stale data.usajobs.gov Host header elsewhere.
    return {
        "User-Agent": email,
        "Authorization-Key": api_key,
    }


def fetch(
    fetcher: Fetcher,
    cfg: UsaJobsConfig,
    api_key: str,
    warn: Callable[[str], None] = lambda message: None,
) -> list[Listing]:
    headers = _headers(api_key, cfg.email)
    base_params: dict[str, str] = {
        "HiringPath": "student",
        "ResultsPerPage": str(RESULTS_PER_PAGE),
    }
    # One query per keyword: USAJOBS ANDs the words inside a single Keyword
    # param, but a configured keyword list means OR. No keywords = one
    # unrestricted query. Results are deduped on the control number.
    queries: list[dict[str, str]] = (
        [{**base_params, "Keyword": keyword} for keyword in cfg.keywords]
        if cfg.keywords
        else [base_params]
    )

    listings: list[Listing] = []
    seen_ids: set[str] = set()
    for params in queries:
        fetched = 0
        count_all: int | None = None
        for page_number in range(1, MAX_PAGES + 1):
            payload = fetcher.get_json(
                SEARCH_URL,
                params={**params, "Page": str(page_number)},
                headers=headers,
                follow_redirects=False,
            )
            items, count_all = _page_items(payload)
            if not items:
                break
            for item in items:
                listing = parse_item(item)
                if listing.listing_id in seen_ids:
                    continue
                seen_ids.add(listing.listing_id)
                listings.append(listing)
            fetched += len(items)
            if count_all is not None and fetched >= count_all:
                break
        if count_all is not None and fetched < count_all:
            keyword = params.get("Keyword", "")
            scope = f" for keyword {keyword!r}" if keyword else ""
            warn(
                f"usajobs: results truncated{scope}: fetched {fetched} of {count_all}; "
                "add or narrow keywords to see everything"
            )
    return listings


def _page_items(payload: object) -> tuple[list[dict[str, object]], int | None]:
    if not isinstance(payload, dict):
        raise AdapterError("unexpected USAJOBS response shape (not a JSON object)")
    search_result = payload.get("SearchResult")
    if not isinstance(search_result, dict):
        raise AdapterError("unexpected USAJOBS response shape (no SearchResult)")
    items = search_result.get("SearchResultItems")
    if not isinstance(items, list):
        raise AdapterError("unexpected USAJOBS response shape (no SearchResultItems list)")
    count_all = search_result.get("SearchResultCountAll")
    return items, count_all if isinstance(count_all, int) else None


def parse_item(item: object) -> Listing:
    if not isinstance(item, dict):
        raise AdapterError("malformed USAJOBS announcement entry (not an object)")
    try:
        control_number = str(item["MatchedObjectId"])
        descriptor = item["MatchedObjectDescriptor"]
        if not isinstance(descriptor, dict):
            raise TypeError("MatchedObjectDescriptor is not an object")
        title = str(descriptor["PositionTitle"])
        position_uri = str(descriptor["PositionURI"])
    except (KeyError, TypeError) as exc:
        raise AdapterError(f"malformed USAJOBS announcement entry: {exc}") from exc

    organization = descriptor.get("OrganizationName")
    company = str(organization) if organization else COMPANY_LABEL

    locations: list[str] = []
    raw_locations = descriptor.get("PositionLocation")
    if isinstance(raw_locations, list):
        for location in raw_locations:
            if isinstance(location, dict):
                name = str(location.get("LocationName") or "").strip()
                if name and name not in locations:
                    locations.append(name)

    posted_at: dt.datetime | None = None
    start_date = descriptor.get("PublicationStartDate")
    if isinstance(start_date, str) and start_date:
        try:
            posted_at = dt.datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except ValueError:
            posted_at = None
        if posted_at is not None and posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=dt.UTC)

    return Listing(
        company=company,
        source=SOURCE,
        listing_id=control_number,
        title=title,
        url=position_uri,
        locations=tuple(locations),
        posted_at=posted_at,
        # Key on the stable Control Number only, the org name displayed above
        # can change (agency rename) without making this a "new" listing (L6).
        identity=f"{SOURCE}:{control_number}",
    )
