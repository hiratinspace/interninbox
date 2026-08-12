"""Location alias intelligence: US states/DC and common country/city forms.

Board location strings are free text; whole-word matching (filters.py) fixed
substring false-positives, but "CA" vs "California" remained the user's
problem. Expanding each filter term to its known aliases closes the common
cases; genuinely unknown terms pass through unchanged.
"""

from __future__ import annotations

# Full name -> USPS abbreviation, all 50 states + DC.
US_STATES: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
}

# Groups of equivalent spellings beyond the states table. Each group expands
# to all of its members whenever any member is used as a filter term.
# NOTE: no ("Los Angeles", "LA") group, "LA" is Louisiana's USPS code, and a
# "Los Angeles" query must never surface "New Orleans, LA" boards. "NY"/"SF"
# are safe (not English words, no state collision beyond their own).
_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("New York", "NYC", "NY"),
    ("United States", "USA", "US"),
    ("United Kingdom", "UK", "Great Britain"),
    ("Washington, D.C.", "Washington DC", "D.C.", "DC"),
    ("San Francisco", "SF"),
)

# Tokens that are also ordinary English words: only ever safe COMMA-ANCHORED
# (", US" matches "Remote, US" but never the pronoun "us" in prose). State
# codes are already anchored in _alias_map; this covers the alias groups.
_ANCHOR_ONLY: frozenset[str] = frozenset({"us"})


def _anchor(term: str) -> str:
    return f", {term}" if term.lower() in _ANCHOR_ONLY else term


def _alias_map() -> dict[str, tuple[str, ...]]:
    """lowercased term -> the extra spellings it expands to.

    Full state name -> the COMMA-ANCHORED abbreviation (", CA"): boards write
    "City, ST", and the anchor keeps codes that are English words (OR, IN, ME,
    OK, HI) from matching prose like "Remote in USA or Canada", matching is
    case-insensitive. Abbreviation -> the full name, plain (full names are
    unambiguous words).
    """
    groups: dict[str, set[str]] = {}
    for name, abbr in US_STATES.items():
        groups.setdefault(name.lower(), set()).add(f", {abbr}")
        groups.setdefault(abbr.lower(), set()).add(name)
    for group in _ALIAS_GROUPS:
        for term in group:
            groups.setdefault(term.lower(), set()).update(set(group) - {term})
    return {key: tuple(sorted(values)) for key, values in groups.items()}


_ALIASES = _alias_map()


def expand_location_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Each term, followed by its known aliases; deduped case-insensitively.

    English-word tokens (e.g. "US") are comma-anchored wherever they appear
    (even a user-typed one), so no expansion can match the pronoun "us".
    """
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        for candidate in (term, *_ALIASES.get(term.strip().lower(), ())):
            candidate = _anchor(candidate)
            if candidate.lower() not in seen:
                seen.add(candidate.lower())
                out.append(candidate)
    return tuple(out)
