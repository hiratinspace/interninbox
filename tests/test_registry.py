"""Registry shape, tiers, and estimates, data-integrity tests, all offline."""

import pytest

from interninbox.config import KNOWN_ATS
from interninbox.registry import (
    REGISTRY,
    TIERS,
    estimate_label,
    estimate_label_for,
    estimate_seconds,
    select,
)


def test_registry_is_reasonably_large_and_mixed() -> None:
    assert len(REGISTRY) >= 160  # grew from 109 in the 2026-08-15 list harvest
    sizes = {entry.size for entry in REGISTRY}
    assert sizes == {"large", "startup"}  # update 4: big AND small every run


def test_entries_are_wellformed_and_unique() -> None:
    seen: set[str] = set()
    for entry in REGISTRY:
        assert entry.ats in KNOWN_ATS
        assert entry.slug and entry.slug == entry.slug.strip()
        assert entry.size in ("large", "startup")
        label = f"{entry.ats}:{entry.slug}"
        assert label not in seen, f"duplicate registry entry {label}"
        seen.add(label)


def test_top_tier_is_a_subset_of_about_fifty() -> None:
    top = select("top")
    assert 40 <= len(top) <= 60
    assert set(top) <= set(select("all"))


def test_size_tiers_partition_all() -> None:
    assert len(select("large")) + len(select("startups")) == len(select("all"))


def test_unknown_tier_raises() -> None:
    with pytest.raises(ValueError, match="top"):
        select("everything")
    assert "top" in TIERS and "all" in TIERS


def test_estimate_label_scales() -> None:
    assert estimate_label(4).endswith("s")
    assert "min" in estimate_label(150)


def test_estimate_weighs_enterprise_boards_by_requests() -> None:
    from interninbox.config import Company

    light = [Company("greenhouse", f"g{i}") for i in range(10)]
    heavy = light + [Company("smartrecruiters", "BigCo")]
    assert estimate_seconds(heavy) > estimate_seconds(light) + 5  # ~10 requests, not 1


def test_estimate_label_for_companies() -> None:
    from interninbox.config import Company

    label = estimate_label_for([Company("greenhouse", f"g{i}") for i in range(100)])
    assert label.startswith("~")
