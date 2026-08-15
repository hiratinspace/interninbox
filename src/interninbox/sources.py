"""Community internship-list sources.

These are curated, structured lists maintained in public GitHub repos, the
best-known being SimplifyJobs' seasonal internship lists (the data file behind
the README students refresh). One polite request fetches the whole list, so a
source gives coverage of every employer on it, including ATSes this tool has
no adapter for; the list links out and interninbox never scrapes those hosts.

"simplify" always points at the current default season; explicit seasonal
names stay available so users can pin one. New seasons arrive via releases.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from interninbox import eligibility
from interninbox.fetch import Fetcher
from interninbox.models import AdapterError, Listing

# The Simplify file is ~11 MB mid-season and grows; well beyond the normal
# per-board cap, still bounded.
SOURCE_MAX_BYTES = 50_000_000

_SPONSORSHIP_MAP = {
    "Offers Sponsorship": eligibility.OFFERS_SPONSORSHIP,
    "Does Not Offer Sponsorship": eligibility.NO_SPONSORSHIP,
    "U.S. Citizenship is Required": eligibility.CITIZENSHIP_REQUIRED,
}


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    label: str  # attribution shown in docs / errors

    @property
    def family(self) -> str:
        """Season-independent name ("simplify-summer2026" -> "simplify"), so
        listing identities stay stable across seasonal repos."""
        return self.name.split("-")[0]


def _simplify(repo: str) -> str:
    return f"https://raw.githubusercontent.com/SimplifyJobs/{repo}/dev/.github/scripts/listings.json"


KNOWN_SOURCES: dict[str, Source] = {
    "simplify": Source(
        "simplify", _simplify("Summer2027-Internships"), "SimplifyJobs Summer 2027 list"
    ),
    "simplify-summer2027": Source(
        "simplify-summer2027", _simplify("Summer2027-Internships"), "SimplifyJobs Summer 2027 list"
    ),
    "simplify-summer2026": Source(
        "simplify-summer2026", _simplify("Summer2026-Internships"), "SimplifyJobs Summer 2026 list"
    ),
}


def fetch_source(fetcher: Fetcher, name: str) -> list[Listing]:
    """Fetch one community list and map its entries to Listings.

    Only active, visible entries are kept. Individual malformed rows are
    skipped (this is community-maintained data; one broken row must not kill
    the source); only a wrong top-level shape is an error.
    """
    spec = KNOWN_SOURCES.get(name)
    if spec is None:
        valid = ", ".join(sorted(KNOWN_SOURCES))
        raise AdapterError(f"unknown source {name!r}; valid sources: {valid}")
    payload = fetcher.get_json(spec.url, max_response_bytes=SOURCE_MAX_BYTES)
    if not isinstance(payload, list):
        raise AdapterError(f"unexpected {spec.label} shape (not a JSON array)")
    listings: list[Listing] = []
    for entry in payload:
        listing = _parse_entry(entry, spec)
        if listing is not None:
            listings.append(listing)
    return listings


def _parse_entry(entry: object, spec: Source) -> Listing | None:
    if not isinstance(entry, dict):
        return None
    if not (entry.get("active") and entry.get("is_visible", True)):
        return None
    listing_id = entry.get("id")
    title = entry.get("title")
    url = entry.get("url")
    company = entry.get("company_name")
    if not all(isinstance(value, str) and value for value in (listing_id, title, url, company)):
        return None

    posted_at: dt.datetime | None = None
    date_posted = entry.get("date_posted")
    if isinstance(date_posted, int) and not isinstance(date_posted, bool) and date_posted > 0:
        posted_at = dt.datetime.fromtimestamp(date_posted, tz=dt.UTC)

    return Listing(
        company=str(company),
        source=spec.family,
        listing_id=str(listing_id),
        title=str(title),
        url=str(url),
        locations=_str_tuple(entry.get("locations")),
        posted_at=posted_at,
        identity=f"{spec.family}:{listing_id}",
        sponsorship=_SPONSORSHIP_MAP.get(str(entry.get("sponsorship", ""))),
        terms=_str_tuple(entry.get("terms")) or eligibility.derive_terms(str(title)),
        degrees=_str_tuple(entry.get("degrees")),
        curated=True,
    )


def _str_tuple(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)
