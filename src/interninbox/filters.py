"""Local heuristic matching, no LLM, just word-boundary regexes.

Two-stage title filter:
  1. internship signal (built-in patterns OR the user's include_keywords);
  2. staff-role exclusion, recruiters, managers, and "Intern Program
     Manager"-style roles about internships are dropped.

Word boundaries matter: a naive substring match on "intern" catches
"International Program Manager" and "Internal Tools Engineer"; `\\bintern\\b`
does not, because there is no word boundary at that position.
"""

from __future__ import annotations

import re

from interninbox import eligibility
from interninbox.config import Filters
from interninbox.models import Listing

_SIGNAL_PATTERNS: tuple[str, ...] = (
    r"\bintern\b",
    r"\binterns\b",
    r"\binternship\b",
    r"\binternships\b",
    r"\bco-op\b",
    r"\bcoop\b",
    r"\bco\s+op\b",
    r"\bsummer\s+analyst\b",
    r"\bsummer\s+associate\b",
    r"\bapprentice\b",
    r"\bapprenticeship\b",
    r"\bstudent\s+researcher\b",
    r"\bundergraduate\s+researcher\b",
    r"\bworking\s+student\b",
    # US-federal Pathways titling: "Student Trainee (Information Technology)".
    # Bare "Pathways" would also catch "Pathways Recent Graduates", a
    # post-degree full-time program, so require the intern word.
    r"\bstudent\s+trainee\b",
    r"\bpathways\s+intern(ship)?s?\b",
    # Program titles that don't say "intern": "... - Summer 2027",
    # UK industrial placements, fellowships, and the standard German/French
    # student-role words these ATSes host EU boards under.
    r"\bsummer\s+20\d{2}\b",
    r"\bindustrial\s+placement\b",
    r"\bplacement\s+(student|year)\b",
    r"\bfellowship\b",
    r"\bpraktikant(in)?\b",
    r"\bwerkstudent(in)?\b",
    r"\bstagiaire\b",
)

INTERNSHIP_SIGNAL = re.compile("|".join(_SIGNAL_PATTERNS), re.IGNORECASE)

# Roles *about* interns rather than *for* interns, plus unambiguous
# seniority markers, an intern posting is never "Senior" or "Staff".
STAFF_ROLE = re.compile(
    r"\b(manager|director|coordinator|recruiter|recruiting|head of|team lead|supervisor"
    r"|professor|instructor|senior|staff|principal)\b|\bsr\b",
    re.IGNORECASE,
)
# Roman-numeral levels are case-sensitive on purpose: as lowercase words,
# "ii"/"iv" would over-match ordinary text.
LEVEL_MARKER = re.compile(r"\b(II|III|IV)\b")

_REMOTE = re.compile(r"\b(remote|anywhere)\b", re.IGNORECASE)


def has_internship_signal(title: str, include_keywords: tuple[str, ...] = ()) -> bool:
    if INTERNSHIP_SIGNAL.search(title):
        return True
    lowered = title.lower()
    return any(keyword.lower() in lowered for keyword in include_keywords)


def matches_required_keywords(title: str, keywords: tuple[str, ...]) -> bool:
    """True when `title` contains at least one keyword as a whole word.

    An empty list means no requirement. Unlike include_keywords (which is
    OR-ed INTO the internship signal and so broadens results), this is
    AND-ed with it and narrows.
    """
    if not keywords:
        return True
    return any(
        re.search(rf"\b{re.escape(keyword)}\b", title, re.IGNORECASE) for keyword in keywords
    )


def is_staff_role(title: str) -> bool:
    return bool(STAFF_ROLE.search(title) or LEVEL_MARKER.search(title))


def is_remote(locations: tuple[str, ...]) -> bool:
    return any(_REMOTE.search(location) for location in locations)


def _passes_locations(listing: Listing, filters: Filters) -> bool:
    locations = listing.locations
    remote_count = sum(1 for location in locations if _REMOTE.search(location))
    if locations and remote_count == len(locations) and not filters.remote_ok:
        return False  # remote-only listing, and the user said no remote
    if remote_count and filters.remote_ok:
        return True  # a remote option satisfies any location preference
    if not filters.locations:
        return True
    if not locations:
        # No stated location and the user asked for specific ones, drop.
        return False
    return any(
        _location_contains(location, want)
        for location in locations
        for want in filters.locations
    )


def _location_contains(location: str, want: str) -> bool:
    """Whole-word location match; lookarounds only at word-character edges.

    A term that starts or ends in punctuation anchors itself: ", CA" (an
    alias expansion) must match "San Francisco, CA" even though a word
    character precedes the comma, and "D.C." keeps matching as before.
    """
    if not want:
        return False
    prefix = r"(?<!\w)" if (want[0].isalnum() or want[0] == "_") else ""
    suffix = r"(?!\w)" if (want[-1].isalnum() or want[-1] == "_") else ""
    return re.search(f"{prefix}{re.escape(want)}{suffix}", location, re.IGNORECASE) is not None


def _passes_eligibility(listing: Listing, filters: Filters) -> bool:
    """Sponsorship / term / degree gates. Unknown metadata always passes:
    a listing is only dropped on a *known* disqualifier."""
    if filters.require_sponsorship and listing.sponsorship in (
        eligibility.NO_SPONSORSHIP,
        eligibility.CITIZENSHIP_REQUIRED,
    ):
        return False
    if filters.terms and listing.terms:
        wanted = {term.lower() for term in filters.terms}
        if not any(term.lower() in wanted for term in listing.terms):
            return False
    if filters.degrees and listing.degrees:
        wanted = {degree.lower() for degree in filters.degrees}
        if not any(degree.lower() in wanted for degree in listing.degrees):
            return False
    return True


def matches(listing: Listing, filters: Filters) -> bool:
    """The full filter chain for one listing.

    Curated list entries skip the title heuristics (internship signal and
    staff-role exclusion): the list's curation already answered those. The
    user's own narrowing (keywords, locations, eligibility) always applies.
    """
    if not listing.curated:
        if not has_internship_signal(listing.title, filters.include_keywords):
            return False
        if is_staff_role(listing.title):
            return False
    if not matches_required_keywords(listing.title, filters.match_keywords):
        return False
    lowered = listing.title.lower()
    if any(keyword.lower() in lowered for keyword in filters.exclude_keywords):
        return False
    if not _passes_eligibility(listing, filters):
        return False
    return _passes_locations(listing, filters)
