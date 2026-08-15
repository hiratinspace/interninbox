"""Pure extraction/aggregation functions of scripts/mine_lists.py.

The script's __main__ does live IO and is not under test; these tests load
the module by path (scripts/ is not a package) and drive its pure functions
against a small synthetic listings fixture.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "mine_lists.py"
_spec = importlib.util.spec_from_file_location("mine_lists", _SCRIPT)
assert _spec is not None and _spec.loader is not None
mine_lists = importlib.util.module_from_spec(_spec)
sys.modules["mine_lists"] = mine_lists  # dataclasses resolve annotations via sys.modules
_spec.loader.exec_module(mine_lists)


def _entry(company: str, url: str, *, active: bool = True, visible: bool = True) -> dict:
    return {
        "company_name": company,
        "title": f"{company} Intern",
        "url": url,
        "active": active,
        "is_visible": visible,
    }


FIXTURE = [
    # Two greenhouse hosts must merge into one pair (and count 2).
    _entry("Aurora Widgets", "https://job-boards.greenhouse.io/aurorawidgets/jobs/101"),
    _entry("Aurora Widgets", "https://boards.greenhouse.io/AuroraWidgets/jobs/102"),
    # Already in registry.REGISTRY: must be dropped from candidates.
    _entry("Stripe", "https://job-boards.greenhouse.io/stripe/jobs/1"),
    # One per remaining supported ATS.
    _entry("Cobalt Cartography", "https://jobs.ashbyhq.com/cobalt/1f2e3d4c"),
    _entry("Harborline", "https://jobs.lever.co/harborline/9a8b7c6d"),
    _entry("Enterprise Co", "https://jobs.smartrecruiters.com/EnterpriseCo/744000-intern"),
    # Inactive and hidden entries never count anywhere.
    _entry("Gone Inc", "https://jobs.lever.co/goneinc/1", active=False),
    _entry("Hidden Inc", "https://jobs.ashbyhq.com/hiddeninc/2", visible=False),
    # Uncovered hosts, grouped into families.
    _entry("Acme", "https://acme.wd1.myworkdayjobs.com/en-US/External/job/1"),
    _entry("Acme", "https://acme.wd1.myworkdayjobs.com/en-US/External/job/2"),
    _entry("Globex", "https://globex.wd5.myworkdayjobs.com/careers/job/3"),
    _entry("Initech", "https://careers-initech.icims.com/jobs/4/intern/job"),
    _entry("Hooli", "https://apply.workable.com/hooli/j/AB12CD/"),
    _entry("Umbrella", "https://umbrella.recruitee.com/o/intern"),
    _entry("Vandelay", "https://vandelay.jobs.personio.de/job/5"),
    _entry("Tesla", "https://www.tesla.com/careers/search/job/6"),
]

_ACTIVE = [entry for entry in FIXTURE if entry["active"] and entry["is_visible"]]


# ---- extract_pair ----------------------------------------------------------


def test_extract_pair_supported_hosts() -> None:
    cases = {
        "https://job-boards.greenhouse.io/acme/jobs/1": ("greenhouse", "acme"),
        "https://boards.greenhouse.io/acme/jobs/2": ("greenhouse", "acme"),
        "https://jobs.ashbyhq.com/cobalt/1f2e3d4c": ("ashby", "cobalt"),
        "https://jobs.lever.co/harborline/9a8b7c6d": ("lever", "harborline"),
        "https://jobs.smartrecruiters.com/EnterpriseCo/744000": ("smartrecruiters", "EnterpriseCo"),
    }
    for url, expected in cases.items():
        assert mine_lists.extract_pair(url) == expected


def test_extract_pair_lowercases_slug_except_smartrecruiters() -> None:
    assert mine_lists.extract_pair("https://boards.greenhouse.io/AcmeCo/jobs/1") == (
        "greenhouse",
        "acmeco",
    )
    # SmartRecruiters identifiers are conventionally CamelCase; keep them.
    assert mine_lists.extract_pair("https://jobs.smartrecruiters.com/BoschGroup/1") == (
        "smartrecruiters",
        "BoschGroup",
    )


def test_extract_pair_rejects_greenhouse_embed_urls() -> None:
    # boards.greenhouse.io/embed/job_app?token=... carries no board slug;
    # "embed" is Greenhouse's embed endpoint, never a board.
    url = "https://boards.greenhouse.io/embed/job_app?token=7231006"
    assert mine_lists.extract_pair(url) is None


def test_extract_pair_rejects_unsupported_or_pathless_urls() -> None:
    assert mine_lists.extract_pair("https://www.tesla.com/careers/search/job/6") is None
    assert mine_lists.extract_pair("https://acme.wd1.myworkdayjobs.com/en-US/x/job/1") is None
    assert mine_lists.extract_pair("https://jobs.lever.co/") is None
    assert mine_lists.extract_pair("not a url") is None


# ---- host_family -----------------------------------------------------------


def test_host_family_groups_known_families() -> None:
    assert mine_lists.host_family("acme.wd1.myworkdayjobs.com") == "workday"
    assert mine_lists.host_family("careers-initech.icims.com") == "icims"
    assert mine_lists.host_family("apply.workable.com") == "workable"
    assert mine_lists.host_family("umbrella.recruitee.com") == "recruitee"
    assert mine_lists.host_family("vandelay.jobs.personio.de") == "personio"


def test_host_family_falls_back_to_the_host_itself() -> None:
    assert mine_lists.host_family("www.tesla.com") == "www.tesla.com"
    assert mine_lists.host_family("lifeattiktok.com") == "lifeattiktok.com"


# ---- active_entries --------------------------------------------------------


def test_active_entries_keeps_only_active_visible_rows_with_urls() -> None:
    rows = mine_lists.active_entries(
        FIXTURE + [{"active": True, "is_visible": True}, "not a dict", {"url": 7, "active": True}]
    )
    assert rows == _ACTIVE


def test_active_entries_defaults_is_visible_to_true() -> None:
    row = {"company_name": "X", "url": "https://jobs.lever.co/x/1", "active": True}
    assert mine_lists.active_entries([row]) == [row]


# ---- mine_candidates -------------------------------------------------------


def test_mine_candidates_aggregates_ranks_and_drops_known() -> None:
    known = mine_lists.known_pairs()
    candidates = mine_lists.mine_candidates(_ACTIVE, known)
    assert [(c.ats, c.slug, c.display_name, c.active_listings) for c in candidates] == [
        ("greenhouse", "aurorawidgets", "Aurora Widgets", 2),
        ("ashby", "cobalt", "Cobalt Cartography", 1),
        ("lever", "harborline", "Harborline", 1),
        ("smartrecruiters", "EnterpriseCo", "Enterprise Co", 1),
    ]


def test_known_pairs_come_from_the_registry_case_insensitively() -> None:
    known = mine_lists.known_pairs()
    assert ("greenhouse", "stripe") in known
    assert ("smartrecruiters", "boschgroup") in known


def test_mine_candidates_merges_slug_case_variants() -> None:
    entries = [
        _entry("Acme Co", "https://jobs.smartrecruiters.com/AcmeCo/1"),
        _entry("Acme Co", "https://jobs.smartrecruiters.com/acmeco/2"),
    ]
    candidates = mine_lists.mine_candidates(entries, frozenset())
    assert len(candidates) == 1
    assert candidates[0].slug == "AcmeCo"  # first seen spelling wins
    assert candidates[0].active_listings == 2


# ---- opportunity_table -----------------------------------------------------


def test_opportunity_table_groups_uncovered_hosts_by_family() -> None:
    table = mine_lists.opportunity_table(_ACTIVE)
    as_tuples = [(o.family, o.active_listings, o.example_host) for o in table]
    assert as_tuples[0] == ("workday", 3, "acme.wd1.myworkdayjobs.com")
    remainder = dict((family, (count, host)) for family, count, host in as_tuples[1:])
    assert remainder == {
        "icims": (1, "careers-initech.icims.com"),
        "workable": (1, "apply.workable.com"),
        "recruitee": (1, "umbrella.recruitee.com"),
        "personio": (1, "vandelay.jobs.personio.de"),
        "www.tesla.com": (1, "www.tesla.com"),
    }


def test_opportunity_table_excludes_supported_ats_hosts() -> None:
    families = {o.family for o in mine_lists.opportunity_table(_ACTIVE)}
    assert not any("greenhouse" in family for family in families)
    assert not any("lever" in family for family in families)


# ---- registry_line ---------------------------------------------------------


def test_registry_line_is_ready_to_paste() -> None:
    candidate = mine_lists.Candidate("greenhouse", "aurorawidgets", "Aurora Widgets", 2)
    line = mine_lists.registry_line(candidate)
    assert line == (
        '    RegistryCompany(_G, "aurorawidgets", "Aurora Widgets", "startup"),'
        "  # 2 active, review size/tags"
    )


def test_registry_line_uses_each_ats_alias() -> None:
    aliases = {"greenhouse": "_G", "lever": "_L", "ashby": "_A", "smartrecruiters": "_S"}
    for ats, alias in aliases.items():
        line = mine_lists.registry_line(mine_lists.Candidate(ats, "slug", "Name", 1))
        assert f"RegistryCompany({alias}, " in line
