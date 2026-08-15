"""Recruitee Careers Site API adapter.

Endpoint: https://{company}.recruitee.com/api/offers/ (documented Careers
Site API, docs.recruitee.com/reference/offers, no auth). One GET returns
every published offer as `{"offers": [...]}`: there is no pagination (limit
and offset are silently ignored; a 78-offer board arrived in one response),
and unknown tenants answer a clean 404 while an existing tenant with zero
published offers answers 200 with an empty offers array.

Field notes (verified live):
  - `id` is the stable offer identifier; `careers_url` is the absolute
    public posting URL (a custom careers domain when configured, else
    https://{company}.recruitee.com/o/{slug});
  - `published_at` is "YYYY-MM-DD HH:MM:SS UTC", not ISO-8601; parsed with
    strptime and pinned to UTC, with format drift leaving posted unset;
  - `locations` entries carry city/state/country (localized display strings,
    e.g. "Allemagne" on a French board), with top-level city/state_name/
    country as the fallback; `remote` is a boolean;
  - `description` and `requirements` are inline HTML in the list response,
    so sponsorship classification costs zero extra requests and the
    `content` flag changes nothing;
  - `employment_type_code == "internship"` is an explicit internship signal:
    intern roles on non-English boards do not always say intern in a
    parseable way, so it feeds `Listing.employment_intern`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from interninbox import eligibility
from interninbox.fetch import Fetcher
from interninbox.models import AdapterError, Listing

BASE_URL = "https://{slug}.recruitee.com/api/offers/"
POSTING_URL = "https://{slug}.recruitee.com/o/{offer_slug}"

SOURCE = "recruitee"


def fetch(
    fetcher: Fetcher,
    slug: str,
    *,
    content: bool = False,
    warn: Callable[[str], None] = lambda message: None,
) -> list[Listing]:
    # `content` is accepted for signature uniformity; descriptions are inline
    # in the one response, so there is nothing extra to fetch.
    payload = fetcher.get_json(BASE_URL.format(slug=slug))
    return parse(payload, slug)


def parse(payload: object, slug: str) -> list[Listing]:
    if not isinstance(payload, dict) or not isinstance(payload.get("offers"), list):
        raise AdapterError(f"unexpected Recruitee response shape for {slug!r} (no offers array)")
    listings: list[Listing] = []
    for offer in payload["offers"]:
        try:
            listings.append(_parse_offer(offer, slug))
        except (KeyError, TypeError) as exc:
            raise AdapterError(f"malformed Recruitee offer entry for {slug!r}: {exc}") from exc
    return listings


def _parse_offer(offer: dict[str, object], slug: str) -> Listing:
    title = str(offer["title"])
    offer_id = str(offer["id"])
    url = str(
        offer.get("careers_url")
        or POSTING_URL.format(slug=slug, offer_slug=offer["slug"])
    )

    # Description and requirements are both inline HTML; together they carry
    # everything the posting says, so both feed the sponsorship classifier.
    sponsorship = evidence = None
    text = " ".join(
        eligibility.text_from_html(str(part))
        for part in (offer.get("description"), offer.get("requirements"))
        if isinstance(part, str) and part
    )
    if text.strip():
        sponsorship, evidence = eligibility.classify_sponsorship_with_evidence(text)

    return Listing(
        company=slug,
        source=SOURCE,
        listing_id=offer_id,
        title=title,
        url=url,
        locations=_locations(offer),
        posted_at=_posted_at(offer.get("published_at")),
        sponsorship=sponsorship,
        sponsorship_evidence=evidence,
        terms=eligibility.derive_terms(title),
        employment_intern=offer.get("employment_type_code") == "internship",
    )


def _posted_at(value: object) -> dt.datetime | None:
    """`published_at` as a UTC datetime, or None on absence or format drift."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return None
    return parsed.replace(tzinfo=dt.UTC)


def _locations(offer: dict[str, object]) -> tuple[str, ...]:
    locations: list[str] = []
    raw = offer.get("locations")
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            joined = _join(entry.get(key) for key in ("city", "state", "country"))
            if joined and joined not in locations:
                locations.append(joined)
    if not locations:
        joined = _join(offer.get(key) for key in ("city", "state_name", "country"))
        if joined:
            locations.append(joined)
    if offer.get("remote") and not any("remote" in entry.lower() for entry in locations):
        locations.append("Remote")
    return tuple(locations)


def _join(parts: object) -> str:
    cleaned = [str(part).strip() for part in parts if part is not None and str(part).strip()]
    return ", ".join(cleaned)
