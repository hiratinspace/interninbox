"""Role presets expand to whole-word keyword sets."""

import pytest

from interninbox.roles import ROLE_PRESETS, expand_roles


def test_every_preset_is_nonempty_lowercase() -> None:
    assert ROLE_PRESETS  # ships with presets
    for name, keywords in ROLE_PRESETS.items():
        assert name == name.lower() and keywords
        assert all(kw == kw.lower() for kw in keywords)


def test_expand_unions_and_dedupes() -> None:
    both = expand_roles(("software", "data"))
    assert set(ROLE_PRESETS["software"]).issubset(both)
    assert set(ROLE_PRESETS["data"]).issubset(both)
    assert len(both) == len(set(both))


def test_unknown_role_names_valid_ones() -> None:
    with pytest.raises(ValueError, match="cybersecurity"):
        expand_roles(("underwater-basketweaving",))


def test_no_overbroad_engineer_keyword() -> None:
    # Bare "engineer" would match every engineering discipline.
    for keywords in ROLE_PRESETS.values():
        assert "engineer" not in keywords and "engineering" not in keywords
