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

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    label: str  # attribution shown in docs / errors


def _simplify(repo: str) -> str:
    return f"https://raw.githubusercontent.com/SimplifyJobs/{repo}/dev/.github/scripts/listings.json"


KNOWN_SOURCES: dict[str, Source] = {
    "simplify": Source(
        "simplify", _simplify("Summer2027-Internships"), "SimplifyJobs Summer 2027 list"
    ),
    "simplify-summer2027": Source(
        "simplify-summer2027", _simplify("Summer2027-Internships"), "SimplifyJobs Summer 2027 list"
    ),
    "simplify-summer2026": Source(
        "simplify-summer2026", _simplify("Summer2026-Internships"), "SimplifyJobs Summer 2026 list"
    ),
}
