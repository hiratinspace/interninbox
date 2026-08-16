"""Maintainer tool: mine the Simplify list for registry candidates and adapter gaps.

Run manually when growing the registry (never from tests):
    .venv/bin/python scripts/mine_lists.py
Reads /tmp/simplify.json when present, otherwise fetches the live list once
through the shared polite Fetcher. Prints (a) ready-to-paste RegistryCompany
lines for supported-ATS boards not yet in the registry, ranked by active
listing count (size "startup" is a placeholder: review size/tags before
landing, then live-verify with scripts/verify_registry.py), (b) the adapter
opportunity table counting active listings per uncovered host family, and
(c) totals. The table is the authoritative input to adapter ordering.

Live run of 2026-08-15 (Simplify Summer 2027 list, 1698 active rows, 248 new
candidates), top 8 uncovered host families:

    workday             455  e.g. psu.wd1.myworkdayjobs.com
    lifeattiktok.com    141  e.g. lifeattiktok.com
    jobs.bytedance.com   86  e.g. jobs.bytedance.com
    www.tesla.com        59  e.g. www.tesla.com
    icims                58  e.g. careers-sig.icims.com
    workable             30  e.g. apply.workable.com
    ats.rippling.com     21  e.g. ats.rippling.com
    www.citadel.com      14  e.g. www.citadel.com
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from interninbox.fetch import Fetcher
from interninbox.registry import REGISTRY
from interninbox.sources import SOURCE_MAX_BYTES, resolve_source

OVERRIDE_PATH = Path("/tmp/simplify.json")

# Job-page hosts our adapters already reach, mapped to the adapter name.
SUPPORTED_HOSTS = {
    "job-boards.greenhouse.io": "greenhouse",
    "boards.greenhouse.io": "greenhouse",
    "jobs.ashbyhq.com": "ashby",
    "jobs.lever.co": "lever",
    "jobs.smartrecruiters.com": "smartrecruiters",
}

# Uncovered hosts grouped into adapter-opportunity families; anything not
# matched here stands as its own family under its bare host name.
_FAMILY_SUFFIXES = (
    (".myworkdayjobs.com", "workday"),
    (".icims.com", "icims"),
    (".recruitee.com", "recruitee"),
    (".jobs.personio.de", "personio"),
)
_FAMILY_EXACT = {"apply.workable.com": "workable"}

_ATS_ALIASES = {"greenhouse": "_G", "lever": "_L", "ashby": "_A", "smartrecruiters": "_S"}


@dataclass(frozen=True)
class Candidate:
    ats: str
    slug: str
    display_name: str
    active_listings: int


@dataclass(frozen=True)
class Opportunity:
    family: str
    active_listings: int
    example_host: str


def active_entries(payload: object) -> list[dict]:
    """The rows worth counting: active, visible, and carrying a URL string."""
    if not isinstance(payload, list):
        return []
    rows: list[dict] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        if not (entry.get("active") and entry.get("is_visible", True)):
            continue
        url = entry.get("url")
        if isinstance(url, str) and url:
            rows.append(entry)
    return rows


def extract_pair(url: str) -> tuple[str, str] | None:
    """(ats, slug) for a supported-host job URL, else None.

    The slug is the first path segment. Greenhouse, Lever, and Ashby slugs
    are case-insensitive lowercase identifiers; SmartRecruiters identifiers
    keep their spelling (the registry stores them as published).
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    ats = SUPPORTED_HOSTS.get(host)
    if ats is None:
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments:
        return None
    slug = segments[0]
    if ats == "greenhouse" and slug.lower() == "embed":
        # boards.greenhouse.io/embed/job_app?token=... names a job, not a
        # board; there is no slug to mine from it.
        return None
    if ats != "smartrecruiters":
        slug = slug.lower()
    return ats, slug


def host_family(host: str) -> str:
    """Adapter-opportunity family for an uncovered host."""
    exact = _FAMILY_EXACT.get(host)
    if exact is not None:
        return exact
    for suffix, family in _FAMILY_SUFFIXES:
        if host.endswith(suffix):
            return family
    return host


def known_pairs() -> frozenset[tuple[str, str]]:
    """(ats, lowercased slug) pairs already in the registry."""
    return frozenset((entry.ats, entry.slug.lower()) for entry in REGISTRY)


def mine_candidates(
    entries: list[dict], known: frozenset[tuple[str, str]]
) -> list[Candidate]:
    """New supported-ATS boards ranked by active-listing count."""
    counts: Counter[tuple[str, str]] = Counter()
    spellings: dict[tuple[str, str], str] = {}
    names: dict[tuple[str, str], Counter[str]] = {}
    for entry in entries:
        pair = extract_pair(entry["url"])
        if pair is None:
            continue
        ats, slug = pair
        key = (ats, slug.lower())
        counts[key] += 1
        spellings.setdefault(key, slug)
        name = entry.get("company_name")
        display = name if isinstance(name, str) and name else slug
        names.setdefault(key, Counter())[display] += 1
    candidates = [
        Candidate(ats, spellings[key], names[key].most_common(1)[0][0], count)
        for key, count in counts.items()
        if key not in known
        for ats in (key[0],)
    ]
    candidates.sort(key=lambda c: (-c.active_listings, c.ats, c.slug.lower()))
    return candidates


def opportunity_table(entries: list[dict]) -> list[Opportunity]:
    """Active-listing counts per uncovered host family, largest first."""
    counts: Counter[str] = Counter()
    hosts: dict[str, Counter[str]] = {}
    for entry in entries:
        try:
            host = (urlsplit(entry["url"]).hostname or "").lower()
        except ValueError:
            continue
        if not host or host in SUPPORTED_HOSTS:
            continue
        family = host_family(host)
        counts[family] += 1
        hosts.setdefault(family, Counter())[host] += 1
    table = [
        Opportunity(family, count, hosts[family].most_common(1)[0][0])
        for family, count in counts.items()
    ]
    table.sort(key=lambda o: (-o.active_listings, o.family))
    return table


def registry_line(candidate: Candidate) -> str:
    """A line ready to paste into registry.py (size is a placeholder)."""
    alias = _ATS_ALIASES[candidate.ats]
    return (
        f'    RegistryCompany({alias}, "{candidate.slug}", "{candidate.display_name}", '
        f'"startup"),  # {candidate.active_listings} active, review size/tags'
    )


def _load_listings() -> object:
    if OVERRIDE_PATH.is_file():
        print(f"reading {OVERRIDE_PATH}", file=sys.stderr)
        return json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
    spec = resolve_source("simplify")
    print(f"fetching {spec.label}", file=sys.stderr)
    with Fetcher() as fetcher:
        return fetcher.get_json(spec.url, max_response_bytes=SOURCE_MAX_BYTES)


def main() -> int:
    payload = _load_listings()
    if not isinstance(payload, list):
        print("unexpected list shape (not a JSON array)", file=sys.stderr)
        return 1
    entries = active_entries(payload)
    candidates = mine_candidates(entries, known_pairs())
    table = opportunity_table(entries)

    covered = sum(1 for entry in entries if extract_pair(entry["url"]) is not None)
    print("== new registry candidates (verify before landing) ==")
    for candidate in candidates:
        print(registry_line(candidate))

    print("\n== adapter opportunity table (uncovered host families) ==")
    width = max((len(o.family) for o in table), default=6)
    for opportunity in table:
        print(
            f"{opportunity.family:<{width}}  {opportunity.active_listings:>5}"
            f"  e.g. {opportunity.example_host}"
        )

    print("\n== totals ==")
    print(f"rows in list:              {len(payload)}")
    print(f"active visible rows:       {len(entries)}")
    print(f"on supported ATS hosts:    {covered}")
    print(f"on uncovered hosts:        {len(entries) - covered}")
    print(f"new registry candidates:   {len(candidates)}")
    print(f"uncovered host families:   {len(table)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
