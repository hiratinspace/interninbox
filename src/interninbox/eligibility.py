"""Eligibility signals: sponsorship classification and term derivation.

Job descriptions and community-list metadata carry the answers students
actually filter by: does this role sponsor a visa, does it require US
citizenship, and which season is it for. Classification here is deliberately
conservative: high-precision phrase lists, and silence means unknown (None),
never a guess. A listing is only ever *dropped* on a known signal.

Precedence when a text carries several signals: citizenship-required beats
no-sponsorship beats offers-sponsorship (the most restrictive read is the
safe one).
"""

from __future__ import annotations

import html
import re

OFFERS_SPONSORSHIP = "offers-sponsorship"
NO_SPONSORSHIP = "no-sponsorship"
CITIZENSHIP_REQUIRED = "citizenship-required"

# Phrases are matched case-insensitively with flexible whitespace. Keep them
# specific: a false "does not sponsor" hides a real opportunity.
_CITIZENSHIP_PATTERNS = (
    r"u\.?s\.?\s+citizenship\s+is\s+required",
    r"citizenship\s+(?:is\s+)?required",
    r"requires?\s+u\.?s\.?\s+citizenship",
    r"must\s+be\s+an?\s+u\.?s\.?\s+citizen",
    r"u\.?s\.?\s+citizens?\s+only",
    r"security\s+clearance",
    r"\bitar\b",
)
_NEGATIVE_PATTERNS = (
    r"unable\s+to\s+sponsor",
    r"not\s+able\s+to\s+sponsor",
    r"can\s*not\s+sponsor",
    r"cannot\s+sponsor",
    r"will\s+not\s+sponsor",
    r"do(?:es)?\s+not\s+sponsor",
    r"do(?:es)?\s+not\s+offer\s+(?:visa\s+)?sponsorship",
    r"no\s+(?:visa\s+|employment\s+)?sponsorship",
    r"sponsorship\s+is\s+not\s+available",
    r"not\s+eligible\s+for\s+(?:visa\s+)?sponsorship",
    r"without\s+(?:visa\s+)?sponsorship",
    r"not\s+require\s+(?:visa\s+)?sponsorship",  # "must not require sponsorship"
)
_POSITIVE_PATTERNS = (
    r"(?:visa\s+)?sponsorship\s+(?:is\s+)?available",
    r"able\s+to\s+sponsor",
    r"will\s+sponsor",
    r"provides?\s+(?:visa\s+)?sponsorship",
    r"offers?\s+(?:visa\s+)?sponsorship",
)

_CITIZENSHIP = re.compile("|".join(_CITIZENSHIP_PATTERNS), re.IGNORECASE)
_NEGATIVE = re.compile("|".join(_NEGATIVE_PATTERNS), re.IGNORECASE)
_POSITIVE = re.compile("|".join(_POSITIVE_PATTERNS), re.IGNORECASE)

_TERM = re.compile(r"\b(spring|summer|fall|autumn|winter)\s+(20\d{2})\b", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def classify_sponsorship(text: str) -> str | None:
    """The sponsorship signal in `text`, or None when it says nothing."""
    if not text:
        return None
    if _CITIZENSHIP.search(text):
        return CITIZENSHIP_REQUIRED
    if _NEGATIVE.search(text):
        return NO_SPONSORSHIP
    if _POSITIVE.search(text):
        return OFFERS_SPONSORSHIP
    return None


def derive_terms(title: str) -> tuple[str, ...]:
    """Season terms named in a title, normalized like "Summer 2027"."""
    terms: list[str] = []
    for season, year in _TERM.findall(title):
        term = f"{season.capitalize()} {year}"
        if term not in terms:
            terms.append(term)
    return tuple(terms)


def text_from_html(markup: str, *, escaped: bool = False) -> str:
    """Plain text out of an HTML description.

    `escaped=True` for sources that HTML-escape the markup itself
    (Greenhouse's `content` field arrives as "&lt;p&gt;...").
    """
    if escaped:
        markup = html.unescape(markup)
    return html.unescape(_TAG.sub(" ", markup))
