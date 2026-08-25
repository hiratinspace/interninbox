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

# Phrases are matched case-insensitively with flexible whitespace, and
# classification is scoped to sentences: a REQUIREMENT in one sentence is
# never softened by a hedge in another, and a mere mention ("clearance is a
# plus") never disqualifies. Keep patterns specific: a false "does not
# sponsor" hides a real opportunity.

# Self-contained requirement phrases: the requirement is in the phrase itself.
_CITIZENSHIP_STRONG_PATTERNS = (
    r"u\.?s\.?\s+citizenship\s+is\s+required",
    r"citizenship\s+(?:is\s+)?required",
    r"requires?\s+u\.?s\.?\s+citizenship",
    r"must\s+be\s+an?\s+u\.?s\.?\s+citizen",
    r"u\.?s\.?\s+citizens?\s+only",
)
# Weak signals: only a requirement when their sentence says so.
_CITIZENSHIP_WEAK_PATTERNS = (
    r"security\s+clearance",
    r"\bitar\b",
)
_REQUIREMENT_MARKERS = (
    r"\b(?:required|requires?|must|mandatory|active|necessary|subject\s+to)\b"
)
# Hedges: the sentence explicitly softens or negates the signal.
_HEDGE_PATTERNS = (
    r"\bpreferred\b",
    r"\ba\s+plus\b",
    r"\bnice\s+to\s+have\b",
    r"\bdesir(?:ed|able)\b",
    r"\bbonus\b",
    r"\badvantageous\b",
    r"\bnot\s+required\b",
    r"\bno\b[^.!?;]{0,60}\brequired\b",
)
_NEGATIVE_PATTERNS = (
    r"unable\s+to\s+sponsor",
    r"not\s+able\s+to\s+sponsor",
    r"can\s*not\s+sponsor",
    r"cannot\s+sponsor",
    r"will\s+not\s+sponsor",
    r"do(?:es)?\s+not\s+sponsor",
    r"do(?:es)?\s+not\s+offer\s+(?:visa\s+)?sponsorship",
    # "no sponsorship available", but never "no sponsorship required/needed".
    r"no\s+(?:visa\s+|employment\s+)?sponsorship"
    r"(?!\s+(?:is\s+)?(?:required|needed|necessary))",
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
# "sponsorship ... but not for interns": an offer that excludes this audience.
_NOT_FOR_INTERNS = re.compile(r"\bnot\s+(?:available\s+)?for\s+intern", re.IGNORECASE)

_CITIZENSHIP_STRONG = re.compile("|".join(_CITIZENSHIP_STRONG_PATTERNS), re.IGNORECASE)
_CITIZENSHIP_WEAK = re.compile("|".join(_CITIZENSHIP_WEAK_PATTERNS), re.IGNORECASE)
_REQUIREMENT = re.compile(_REQUIREMENT_MARKERS, re.IGNORECASE)
_HEDGE = re.compile("|".join(_HEDGE_PATTERNS), re.IGNORECASE)
_NEGATIVE = re.compile("|".join(_NEGATIVE_PATTERNS), re.IGNORECASE)
_POSITIVE = re.compile("|".join(_POSITIVE_PATTERNS), re.IGNORECASE)
# The lookbehind refuses to split after a single-letter abbreviation
# ("U.S.", "e.g."): a non-word char, one letter, then the period. Without
# it, "must be a U.S. citizen" splits mid-phrase and the strong
# citizenship patterns can never match their own most common phrasing.
_SENTENCE = re.compile(r"(?<=[.!?;])(?<!\W[A-Za-z]\.)\s+|\n+")

_TERM = re.compile(r"\b(spring|summer|fall|autumn|winter)\s+(20\d{2})\b", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


# Evidence sentences are provenance for humans: long enough to audit the
# verdict, short enough for a JSON payload.
_EVIDENCE_MAX_CHARS = 160


def _evidence(sentence: str) -> str:
    return " ".join(sentence.split())[:_EVIDENCE_MAX_CHARS]


def classify_sponsorship(text: str) -> str | None:
    """The sponsorship signal in `text`, or None when it says nothing.

    Sentence-scoped, requirement-vs-mention aware: hedged signals
    ("clearance preferred", "no sponsorship required") never disqualify.
    Across sentences, the most restrictive confirmed signal wins.
    """
    classification, _ = classify_sponsorship_with_evidence(text)
    return classification


def classify_sponsorship_with_evidence(text: str) -> tuple[str | None, str | None]:
    """`classify_sponsorship` plus provenance: the sentence that decided it.

    Returns (classification, evidence). The evidence is the first sentence
    carrying the winning signal, whitespace-collapsed and trimmed to 160
    characters; both are None when the text says nothing.
    """
    if not text:
        return None, None
    negative_evidence: str | None = None
    positive_evidence: str | None = None
    for sentence in _SENTENCE.split(text):
        if not sentence.strip():
            continue
        hedged = bool(_HEDGE.search(sentence))
        if not hedged:
            if _CITIZENSHIP_STRONG.search(sentence):
                return CITIZENSHIP_REQUIRED, _evidence(sentence)
            if _CITIZENSHIP_WEAK.search(sentence) and _REQUIREMENT.search(sentence):
                return CITIZENSHIP_REQUIRED, _evidence(sentence)
        if _NEGATIVE.search(sentence) and not (hedged and not _POSITIVE.search(sentence)):
            if negative_evidence is None:
                negative_evidence = _evidence(sentence)
        if _POSITIVE.search(sentence):
            if _NOT_FOR_INTERNS.search(sentence):
                if negative_evidence is None:
                    negative_evidence = _evidence(sentence)
            elif positive_evidence is None:
                positive_evidence = _evidence(sentence)
    if negative_evidence is not None:
        return NO_SPONSORSHIP, negative_evidence
    if positive_evidence is not None:
        return OFFERS_SPONSORSHIP, positive_evidence
    return None, None


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
