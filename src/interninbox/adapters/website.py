"""The `website:` pseudo-ATS: sitemaps plus schema.org JobPosting JSON-LD.

Companies without a supported ATS often still publish their jobs as
structured data for search engines. This adapter reads exactly that public
surface and nothing else: robots.txt first (our real User-Agent; disallowed
pages are skipped and counted), then the site's published sitemaps, then
only job-looking pages, each parsed for embedded JobPosting JSON-LD.

Politeness and honesty:
  - every request goes through the shared Fetcher (sequential, per-host
    delay, timeouts, one retry);
  - a site whose robots.txt cannot be read (403 and friends) is refused
    outright: without permission we do not scan (a 404 means no robots file
    exists, which by convention allows everything);
  - hard caps with honest warnings: at most `MAX_CHILD_SITEMAPS` child
    sitemaps, sitemap-index recursion depth `MAX_SITEMAP_DEPTH`, at most
    `WEBSITE_PAGE_CAP` page fetches per site per scan.

Known limitations (verified live 2026-08-15): sites that render jobs purely
client-side (lifeattiktok.com, jobs.bytedance.com, most iCIMS tenants) ship
no server-side JSON-LD and yield nothing; sites that block automated
requests (www.tesla.com) or disallow all crawling in robots.txt are
respected and skipped. Workday-hosted boards (`*.myworkdayjobs.com`) and
WordPress-style career sites publish both sitemaps and JSON-LD and work
end to end.

A per-site cache (`{cache_dir}/website/{domain}.json`) keeps the previous
scan's page results keyed by URL: a page is refetched only when its sitemap
`lastmod` changed or is missing, so steady-state rescans cost sitemap reads
plus the changed pages.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from interninbox import USER_AGENT
from interninbox.fetch import Fetcher
from interninbox.jsonld import SOURCE, extract_job_postings, posting_to_listing
from interninbox.models import AdapterError, Listing
from interninbox.sources import _cache_dir

WEBSITE_PAGE_CAP = 200  # page fetches per site per scan
MAX_SITEMAP_DEPTH = 2  # sitemap-index recursion floor
MAX_CHILD_SITEMAPS = 20  # child sitemaps fetched per site per scan
SITEMAP_MAX_BYTES = 20_000_000  # a sitemap file, generously
PAGE_MAX_BYTES = 5_000_000  # a job page, not an app bundle

# A page URL is a job candidate when its path contains one of these.
_JOB_PATH_WORDS = ("job", "jobs", "career", "careers", "position", "opening", "vacanc")
# A sitemap whose filename says jobs contributes ALL of its URLs.
_JOB_SITEMAP_WORDS = ("job", "career")

Warn = Callable[[str], None]


def fetch(
    fetcher: Fetcher,
    domain: str,
    *,
    content: bool = False,
    warn: Warn = lambda message: None,
) -> list[Listing]:
    # `content` is accepted for signature uniformity; job pages always carry
    # their full description, there is nothing extra to opt into.
    candidates = iter_job_urls(fetcher, domain, warn)
    cache = _load_cache(domain)
    fresh: dict[str, dict] = {}
    listings: list[Listing] = []
    fetched = truncated = failures = 0
    for url, lastmod in candidates:
        entry = cache.get(url)
        if (
            entry is not None
            and lastmod is not None
            and entry.get("lastmod") == lastmod
        ):
            fresh[url] = entry
            cached = entry.get("listing")
            if isinstance(cached, dict):
                listing = _listing_from_dict(cached)
                if listing is not None:
                    listings.append(listing)
            continue
        if fetched >= WEBSITE_PAGE_CAP:
            truncated += 1
            continue
        fetched += 1
        try:
            html = fetcher.get_text(url, max_response_bytes=PAGE_MAX_BYTES)
        except AdapterError:
            failures += 1
            continue
        listing = None
        for posting in extract_job_postings(html):
            listing = posting_to_listing(posting, url, domain)
            if listing is not None:
                break  # one page is one posting; the first usable one wins
        fresh[url] = {
            "lastmod": lastmod,
            "listing": _listing_to_dict(listing) if listing is not None else None,
        }
        if listing is not None:
            listings.append(listing)
    if truncated:
        warn(
            f"website:{domain}: page cap of {WEBSITE_PAGE_CAP} reached, "
            f"{truncated} candidate pages left for the next scan"
        )
    if failures:
        warn(f"website:{domain}: {failures} pages failed to fetch, skipped")
    _save_cache(domain, fresh)
    return listings


# ---- sitemap walking ----


def iter_job_urls(
    fetcher: Fetcher, domain: str, warn: Warn
) -> list[tuple[str, str | None]]:
    """Candidate job page URLs (with sitemap lastmod) for `domain`.

    robots.txt drives everything: its Sitemap lines are the entry points
    (falling back to /sitemap.xml), and pages it disallows for our
    User-Agent are skipped and counted in one honest warning.
    """
    robots = _load_robots(fetcher, domain)
    sitemap_urls = list(robots.site_maps() or [])
    if not sitemap_urls:
        fallback = f"https://{domain}/sitemap.xml"
        if robots.can_fetch(USER_AGENT, fallback):
            sitemap_urls = [fallback]
        else:
            warn(f"website:{domain}: robots.txt disallows the default sitemap, nothing to scan")
            return []
    candidates: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    state = {"children": 0, "warned": False, "offsite": 0}
    for sitemap_url in sitemap_urls:
        # Robots-listed sitemaps count against the same cap as index children:
        # a hostile robots.txt with hundreds of Sitemap lines stays bounded.
        if state["children"] >= MAX_CHILD_SITEMAPS:
            if not state["warned"]:
                state["warned"] = True
                warn(
                    f"website:{domain}: more than {MAX_CHILD_SITEMAPS} "
                    "sitemaps, truncated"
                )
            break
        if not _in_scope(sitemap_url, domain):
            state["offsite"] += 1
            continue
        state["children"] += 1
        _walk_sitemap(fetcher, sitemap_url, domain, 0, state, candidates, seen, warn)
    if state["offsite"]:
        warn(
            f"website:{domain}: {state['offsite']} sitemap or page URLs pointed "
            "outside the configured domain, skipped"
        )
    allowed: list[tuple[str, str | None]] = []
    blocked = 0
    for url, lastmod in candidates:
        if robots.can_fetch(USER_AGENT, url):
            allowed.append((url, lastmod))
        else:
            blocked += 1
    if blocked:
        warn(f"website:{domain}: {blocked} pages disallowed by robots.txt, skipped")
    return allowed


def _load_robots(fetcher: Fetcher, domain: str) -> urllib.robotparser.RobotFileParser:
    parser = urllib.robotparser.RobotFileParser()
    try:
        text = fetcher.get_text(f"https://{domain}/robots.txt")
    except AdapterError as exc:
        message = str(exc)
        if "HTTP 404" in message or "HTTP 410" in message:
            parser.parse([])  # no robots file: everything is allowed
            return parser
        raise AdapterError(
            f"robots.txt could not be read ({message}); scanning without "
            "permission would be impolite, skipping this site"
        ) from exc
    parser.parse(text.splitlines())
    return parser


def _walk_sitemap(
    fetcher: Fetcher,
    url: str,
    domain: str,
    depth: int,
    state: dict,
    candidates: list[tuple[str, str | None]],
    seen: set[str],
    warn: Warn,
) -> None:
    try:
        body = fetcher.get_text(url, max_response_bytes=SITEMAP_MAX_BYTES)
    except AdapterError as exc:
        warn(f"website:{domain}: sitemap {url}: {exc}")
        return
    # No legitimate sitemap declares a DTD; refusing them up front removes
    # the classic XML entity attacks (XXE, billion laughs) without leaving
    # the stdlib parser.
    if "<!doctype" in body[:4096].lower() or "<!entity" in body[:4096].lower():
        warn(f"website:{domain}: sitemap {url} declares a DTD, refused")
        return
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        warn(f"website:{domain}: sitemap {url} is not valid XML, skipped")
        return
    tag = _local_name(root.tag)
    if tag == "sitemapindex":
        if depth >= MAX_SITEMAP_DEPTH:
            return  # nested too deep; the caps keep walks bounded
        for child in root:
            loc = _child_text(child, "loc")
            if not loc:
                continue
            if not _in_scope(loc, domain):
                state["offsite"] += 1
                continue
            if state["children"] >= MAX_CHILD_SITEMAPS:
                if not state["warned"]:
                    state["warned"] = True
                    warn(
                        f"website:{domain}: more than {MAX_CHILD_SITEMAPS} "
                        "sitemaps, truncated"
                    )
                return
            state["children"] += 1
            _walk_sitemap(fetcher, loc, domain, depth + 1, state, candidates, seen, warn)
    elif tag == "urlset":
        take_all = _is_job_sitemap(url)
        for child in root:
            loc = _child_text(child, "loc")
            if not loc or loc in seen:
                continue
            if not _in_scope(loc, domain):
                state["offsite"] += 1
                continue
            if take_all or _looks_like_job_page(loc):
                seen.add(loc)
                candidates.append((loc, _child_text(child, "lastmod")))
    else:
        warn(f"website:{domain}: {url} is not a sitemap (root element {tag!r}), skipped")


def _in_scope(url: str, domain: str) -> bool:
    """Only the configured domain and its subdomains are ever fetched: a
    sitemap must not be able to point the scanner at arbitrary hosts."""
    host = urllib.parse.urlsplit(url).netloc.lower().split(":")[0]
    wanted = domain.lower()
    return host == wanted or host.endswith("." + wanted)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return None


def _is_job_sitemap(sitemap_url: str) -> bool:
    filename = urllib.parse.urlsplit(sitemap_url).path.rsplit("/", 1)[-1].lower()
    return any(word in filename for word in _JOB_SITEMAP_WORDS)


def _looks_like_job_page(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path.lower()
    return any(word in path for word in _JOB_PATH_WORDS)


# ---- the per-site incremental cache ----


def _cache_path(domain: str) -> Path:
    return _cache_dir() / "website" / f"{domain}.json"


def _load_cache(domain: str) -> dict[str, dict]:
    """Previous scan's page results, or empty on absence or corruption."""
    try:
        raw = json.loads(_cache_path(domain).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        url: entry
        for url, entry in raw.items()
        if isinstance(url, str) and isinstance(entry, dict)
    }


def _save_cache(domain: str, entries: dict[str, dict]) -> None:
    """Best effort, same rules as the list cache: failures cost a refetch."""
    try:
        path = _cache_path(domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(entries, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _listing_to_dict(listing: Listing) -> dict:
    return {
        "company": listing.company,
        "listing_id": listing.listing_id,
        "title": listing.title,
        "url": listing.url,
        "locations": list(listing.locations),
        "posted_at": listing.posted_at.isoformat() if listing.posted_at else None,
        "identity": listing.identity,
        "sponsorship": listing.sponsorship,
        "sponsorship_evidence": listing.sponsorship_evidence,
        "terms": list(listing.terms),
        "employment_intern": bool(listing.employment_intern),
    }


def _listing_from_dict(raw: dict) -> Listing | None:
    """A cached listing back as a Listing, or None on any shape rot."""
    try:
        posted_raw = raw.get("posted_at")
        posted = dt.datetime.fromisoformat(posted_raw) if isinstance(posted_raw, str) else None
        identity = raw.get("identity")
        sponsorship = raw.get("sponsorship")
        evidence = raw.get("sponsorship_evidence")
        return Listing(
            company=str(raw["company"]),
            source=SOURCE,
            listing_id=str(raw["listing_id"]),
            title=str(raw["title"]),
            url=str(raw["url"]),
            locations=tuple(str(item) for item in raw.get("locations") or []),
            posted_at=posted,
            identity=str(identity) if isinstance(identity, str) else None,
            sponsorship=str(sponsorship) if isinstance(sponsorship, str) else None,
            sponsorship_evidence=str(evidence) if isinstance(evidence, str) else None,
            terms=tuple(str(item) for item in raw.get("terms") or []),
            employment_intern=bool(raw.get("employment_intern", False)),
        )
    except (KeyError, TypeError, ValueError):
        return None
