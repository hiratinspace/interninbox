"""Shared data shapes."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Listing:
    """One job listing, normalized across every source."""

    company: str  # display label ("stripe", "NASA", ...)
    source: str  # "greenhouse" | "lever" | "ashby" | "usajobs"
    listing_id: str  # the source's own stable identifier
    title: str
    url: str
    locations: tuple[str, ...] = ()
    posted_at: dt.datetime | None = None
    # Overrides the derived state key when the default one would be unstable,
    # e.g. USAJOBS, whose `company` is a mutable free-text agency name.
    identity: str | None = None
    # Eligibility signals (see eligibility.py); None / empty means unknown,
    # and unknown never causes a listing to be dropped.
    sponsorship: str | None = None
    terms: tuple[str, ...] = ()
    degrees: tuple[str, ...] = ()
    # True for listings from a curated internship list: the internship-signal
    # and staff-role title heuristics are skipped (curation already did that).
    curated: bool = False

    @property
    def key(self) -> str:
        """Stable identity used by the seen-state file."""
        return self.identity or f"{self.source}:{self.company}:{self.listing_id}"


class AdapterError(Exception):
    """A board fetch or parse failed for one company.

    Callers report it as a one-line warning and keep scanning; one broken
    board never aborts the whole run.
    """


@dataclass
class ScanResult:
    """Everything one scan produced, for the output layer."""

    listings: list[Listing] = field(default_factory=list)
    companies_scanned: int = 0
    companies_failed: int = 0
    listings_checked: int = 0  # everything fetched, before any filtering
    listings_matched: int = 0  # after filters, before --new-only
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
