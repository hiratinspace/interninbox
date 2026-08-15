"""The scan core: one path shared by the CLI (and later MCP and watch).

`run_scan` does everything between "a validated Config" and "a finished
ScanResult": effective filters and companies, the scale note, fetching
(boards, USAJOBS, community sources), dedup, filtering, the freshness
window, and the seen-listings state behind new-only. Presentation stays
with the caller: the banner, note/warning printing, output formatting,
and exit codes all live in the CLI.

Human-facing status goes through the injected `progress` callable, called
as `progress(line, essential=...)`. Lines the CLI always prints (the state
warning, the scale note) are marked `essential=True`; per-company progress
lines are not, so the caller can gate them on a TTY. `progress=None` runs
completely silent, which is what a protocol server wants.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
import time
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

import httpx

from interninbox import registry as registry_mod
from interninbox import sources as sources_mod
from interninbox.adapters import ADAPTERS, usajobs
from interninbox.config import Company, Config, Filters
from interninbox.fetch import Fetcher
from interninbox.filters import matches
from interninbox.freshness import apply_since
from interninbox.locations import expand_location_terms
from interninbox.models import AdapterError, Listing, ScanResult
from interninbox.roles import expand_roles
from interninbox.state import State, load_state


class Progress(Protocol):
    """Status sink for a scan; `essential` lines should reach the user."""

    def __call__(self, line: str, *, essential: bool = False) -> None: ...


def effective_filters(config: Config) -> Filters:
    """Scan-time filter view: aliases expanded, role presets merged in."""
    role_keywords = expand_roles(config.filters.roles)
    merged = config.filters.match_keywords + tuple(
        keyword for keyword in role_keywords
        if keyword not in config.filters.match_keywords
    )
    return dataclasses.replace(
        config.filters,
        match_keywords=merged,
        locations=expand_location_terms(config.filters.locations),
    )


def effective_companies(config: Config) -> tuple[Company, ...]:
    """Config companies first, then the chosen registry tier (deduped)."""
    companies = list(config.companies)
    if config.registry != "none":
        listed = {company.label for company in companies}
        for entry in registry_mod.select(config.registry):
            company = Company(ats=entry.ats, slug=entry.slug)
            if company.label not in listed:
                listed.add(company.label)
                companies.append(company)
    return tuple(companies)


def _normalize_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


def dedupe_listings(listings: list[Listing]) -> list[Listing]:
    """Collapse the same posting seen via a board AND a community list.

    The direct board version wins (fresher title and locations), but inherits
    any eligibility metadata only the list knew (sponsorship, terms, degrees).
    Order-preserving; first occurrence keeps its position.
    """
    by_url: dict[str, int] = {}
    kept: list[Listing] = []
    for listing in listings:
        key = _normalize_url(listing.url)
        index = by_url.get(key)
        if index is None:
            by_url[key] = len(kept)
            kept.append(listing)
            continue
        existing = kept[index]
        base, extra = (
            (existing, listing) if listing.curated or not existing.curated
            else (listing, existing)
        )
        kept[index] = dataclasses.replace(
            base,
            sponsorship=base.sponsorship or extra.sponsorship,
            # Evidence travels with whichever sponsorship verdict was kept.
            sponsorship_evidence=(
                base.sponsorship_evidence if base.sponsorship else extra.sponsorship_evidence
            ),
            terms=base.terms or extra.terms,
            degrees=base.degrees or extra.degrees,
        )
    return kept


def run_scan(
    config: Config,
    *,
    new_only: bool = False,
    since: dt.timedelta | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    env: Mapping[str, str] | None = None,
    progress: Progress | None = None,
    state_path: Path | None = None,
) -> ScanResult:
    """Run one full scan of `config` and return the finished ScanResult.

    `state_path=None` runs stateless: nothing is read or written, and
    `new_only` treats every listing as new. With a path, every fetched
    listing is recorded (flag or not), so "new" means "never fetched
    before". `env` defaults to `os.environ` (USAJOBS reads its key there).
    """

    def emit(line: str, *, essential: bool = False) -> None:
        if progress is not None:
            progress(line, essential=essential)

    environ = env if env is not None else os.environ
    state = load_state(state_path) if state_path is not None else State({})
    if state.warning:
        emit(f"warning: {state.warning}", essential=True)

    companies = effective_companies(config)
    filters = effective_filters(config)
    if len(companies) >= 20:
        note = (
            f"scanning {len(companies)} boards, roughly "
            f"{registry_mod.estimate_label_for(companies)} at polite pacing"
        )
        if filters.require_sponsorship:
            note += " (downloading descriptions for the sponsorship filter)"
        emit(note, essential=True)

    step = None if progress is None else emit
    result = ScanResult()
    with Fetcher(transport=transport, sleep=sleep) as fetcher:
        # Descriptions are only worth fetching when a filter reads them.
        scan_boards(
            companies, fetcher, result, progress=step, content=filters.require_sponsorship
        )
        scan_usajobs(config, fetcher, environ, result, progress=step)
        scan_sources(config, fetcher, result, progress=step)

    result.listings = dedupe_listings(result.listings)
    result.listings_checked = len(result.listings)
    matched = [listing for listing in result.listings if matches(listing, filters)]
    if since is not None:
        matched = apply_since(matched, since)
    result.listings_matched = len(matched)
    shown = [listing for listing in matched if state.is_new(listing)] if new_only else matched
    # Record EVERYTHING fetched, flag or not, so "new" means "never fetched
    # before": loosening a filter later cannot flood --new-only with old posts.
    state.record(result.listings)
    result.listings = shown
    if state_path is not None:
        try:
            state.save(state_path)
        except OSError as exc:
            result.warnings.append(f"could not write state file {state_path}: {exc}")
    return result


def scan_boards(
    companies: tuple[Company, ...],
    fetcher: Fetcher,
    result: ScanResult,
    *,
    progress: Callable[[str], None] | None = None,
    content: bool = False,
) -> None:
    total = len(companies)
    for index, company in enumerate(companies, start=1):
        if progress is not None:
            progress(f"[{index}/{total}] {company.label} ...")
        adapter_fetch = ADAPTERS[company.ats]
        try:
            listings = adapter_fetch(
                fetcher, company.slug, content=content, warn=result.warnings.append
            )
        except AdapterError as exc:
            result.companies_failed += 1
            result.warnings.append(f"{company.label}: {exc}")
            continue
        result.companies_scanned += 1
        result.listings.extend(listings)


def scan_sources(
    config: Config,
    fetcher: Fetcher,
    result: ScanResult,
    *,
    progress: Callable[[str], None] | None = None,
) -> None:
    for name in config.sources:
        if progress is not None:
            progress(f"[source] {name} ...")
        try:
            listings = sources_mod.fetch_source(fetcher, name, warn=result.warnings.append)
        except AdapterError as exc:
            result.companies_failed += 1
            result.warnings.append(f"source {name}: {exc}")
            continue
        result.sources_scanned += 1
        result.listings.extend(listings)


def scan_usajobs(
    config: Config,
    fetcher: Fetcher,
    env: Mapping[str, str],
    result: ScanResult,
    *,
    progress: Callable[[str], None] | None = None,
) -> None:
    cfg = config.usajobs
    if not cfg.enabled:
        return
    api_key = env.get(cfg.api_key_env, "").strip()
    if not api_key:
        result.notes.append(
            f"usajobs: enabled but {cfg.api_key_env} is not set, skipping "
            "(get a free key at https://developer.usajobs.gov/apirequest/)"
        )
        return
    if progress is not None:
        progress("[usajobs] data.usajobs.gov ...")
    try:
        listings = usajobs.fetch(fetcher, cfg, api_key, warn=result.warnings.append)
    except AdapterError as exc:
        result.companies_failed += 1
        result.warnings.append(f"usajobs: {exc}")
        return
    result.companies_scanned += 1
    result.listings.extend(listings)
