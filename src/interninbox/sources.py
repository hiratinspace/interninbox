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
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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


def _simplify_url(year: int) -> str:
    return (
        "https://raw.githubusercontent.com/SimplifyJobs/"
        f"Summer{year}-Internships/dev/.github/scripts/listings.json"
    )


def default_simplify_season(today: dt.date | None = None) -> int:
    """The summer season students are hunting for on `today`.

    From August, the cycle targets NEXT summer (recruiting opens ~a year
    ahead); through July, the current one. No release needed when seasons
    roll over.
    """
    today = today or dt.date.today()
    return today.year + 1 if today.month >= 8 else today.year


_PINNED = re.compile(r"^simplify-summer(20\d{2})$")


def resolve_source(name: str, today: dt.date | None = None) -> Source:
    """A concrete Source for a configured name, or raise AdapterError."""
    if name == "simplify":
        year = default_simplify_season(today)
        return Source("simplify", _simplify_url(year), f"SimplifyJobs Summer {year} list")
    pinned = _PINNED.match(name)
    if pinned:
        year = int(pinned.group(1))
        return Source(name, _simplify_url(year), f"SimplifyJobs Summer {year} list")
    valid = ", ".join(sorted(known_source_names()))
    raise AdapterError(f"unknown source {name!r}; valid sources: {valid}")


def is_known_source(name: str) -> bool:
    return name == "simplify" or bool(_PINNED.match(name))


def known_source_names() -> tuple[str, ...]:
    """Names shown in validation errors (the pinned form is a pattern)."""
    year = default_simplify_season()
    return ("simplify", f"simplify-summer{year - 1}", f"simplify-summer{year}")


def fetch_source(
    fetcher: Fetcher,
    name: str,
    warn: Callable[[str], None] = lambda message: None,
    today: dt.date | None = None,
) -> list[Listing]:
    """Fetch one community list and map its entries to Listings.

    Only active, visible entries are kept. Individual malformed rows are
    skipped (this is community-maintained data; one broken row must not kill
    the source); only a wrong top-level shape is an error.
    """
    spec = resolve_source(name, today)
    try:
        payload = _fetch_with_cache(fetcher, spec)
    except AdapterError as exc:
        # Only a 404/410 means the next season's repo is not published yet.
        # A transient failure (5xx, network) must NOT silently serve the
        # year-old previous season's list with a misleading explanation.
        if name != "simplify" or exc.status not in (404, 410):
            raise
        # The next season's repo may not be published yet: fall back one
        # season rather than failing the scan.
        year = default_simplify_season(today) - 1
        fallback = Source("simplify", _simplify_url(year), f"SimplifyJobs Summer {year} list")
        payload = _fetch_with_cache(fetcher, fallback)
        warn(f"source simplify: next season's list is not published yet, "
             f"using the Summer {year} list")
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

    raw_sponsorship = str(entry.get("sponsorship", ""))
    sponsorship = _SPONSORSHIP_MAP.get(raw_sponsorship)
    # Provenance is the list's own words; unmapped values stay unknown with
    # no evidence.
    evidence = f'list: "{raw_sponsorship}"' if sponsorship is not None else None

    return Listing(
        company=str(company),
        source=spec.family,
        listing_id=str(listing_id),
        title=str(title),
        url=str(url),
        locations=_str_tuple(entry.get("locations")),
        posted_at=posted_at,
        identity=f"{spec.family}:{listing_id}",
        sponsorship=sponsorship,
        sponsorship_evidence=evidence,
        terms=_str_tuple(entry.get("terms")) or eligibility.derive_terms(str(title)),
        degrees=_str_tuple(entry.get("degrees")),
        curated=True,
    )


def _str_tuple(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


def _cache_dir() -> Path:
    """Platform cache directory for list bodies (created on demand)."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "interninbox"


def _fetch_with_cache(fetcher: Fetcher, spec: Source) -> object:
    """Conditional fetch: a fresh list updates the cache; an unchanged one
    (HTTP 304) is served from it. Cache trouble never breaks a scan; it just
    costs the full download."""
    body_path = etag_path = None
    etag = None
    try:
        cache = _cache_dir()
        body_path = cache / f"{spec.name}.json"
        etag_path = cache / f"{spec.name}.etag"
        if body_path.is_file() and etag_path.is_file():
            etag = etag_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        body_path = etag_path = None

    payload, new_etag = fetcher.get_json_conditional(
        spec.url, etag=etag, max_response_bytes=SOURCE_MAX_BYTES
    )
    if payload is None and body_path is not None:  # 304: our copy is current
        try:
            return json.loads(body_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Cache rotted underneath us: pay for one full refetch.
            payload, new_etag = fetcher.get_json_conditional(
                spec.url, etag=None, max_response_bytes=SOURCE_MAX_BYTES
            )

    if payload is not None and new_etag and body_path is not None and etag_path is not None:
        try:
            body_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = body_path.with_name(body_path.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, body_path)
            etag_path.write_text(new_etag, encoding="utf-8")
        except OSError:
            pass  # caching is an optimization, never a requirement
    return payload
