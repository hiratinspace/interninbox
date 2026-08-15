"""`interninbox find-board`: probe the known ATS endpoints for a company.

Careers-page URLs are the ground truth for slugs, but most of the time the
slug is just the company name lowercased. This probes each supported ATS with
the obvious guesses (a handful of polite GETs through the shared Fetcher) and
reports the ones that answer as real boards. SmartRecruiters answers 200 for
ANY identifier, so a hit there additionally requires at least one posting.
"""

from __future__ import annotations

import re

from interninbox.fetch import Fetcher
from interninbox.models import AdapterError

_PROBES = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}
_SR_PROBE = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1"


def _guesses(name: str) -> list[str]:
    """Lowercase slug candidates: words joined, and hyphenated when multiword."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    if not words:
        return []
    joined = "".join(words)
    guesses = [joined]
    if len(words) > 1:
        guesses.append("-".join(words))
    return guesses


def _sr_guesses(name: str) -> list[str]:
    """SmartRecruiters identifiers are conventionally CamelCase ("BoschGroup")
    and matched case-insensitively; probe the as-typed form first."""
    stripped = re.sub(r"[^A-Za-z0-9]+", "", name)
    guesses = [stripped] if stripped else []
    lowered = stripped.lower()
    if lowered and lowered != stripped:
        guesses.append(lowered)
    return guesses


def find_boards(fetcher: Fetcher, name: str) -> list[str]:
    """`ats:slug` labels of boards that answered for `name`'s slug guesses."""
    found: list[str] = []
    for ats, template in _PROBES.items():
        for guess in _guesses(name):
            try:
                fetcher.get_json(template.format(slug=guess))
            except AdapterError:
                continue
            found.append(f"{ats}:{guess}")
            break  # one hit per ATS is enough
    for guess in _sr_guesses(name):
        try:
            payload = fetcher.get_json(_SR_PROBE.format(slug=guess))
        except AdapterError:
            continue
        total = payload.get("totalFound") if isinstance(payload, dict) else 0
        if isinstance(total, int) and total > 0:
            found.append(f"smartrecruiters:{guess}")
            break
    return found
