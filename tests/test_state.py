"""Seen-state behavior: first run, subsequent runs, corruption."""

from pathlib import Path

from conftest import make_listing

from interninbox.state import load_state


def test_missing_state_everything_new_no_warning(tmp_path: Path) -> None:
    state = load_state(tmp_path / ".interninbox-state.json")
    assert state.warning is None
    assert state.is_new(make_listing())


def test_record_save_reload_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / ".interninbox-state.json"
    listing = make_listing(listing_id="42")
    state = load_state(path)
    state.record([listing])
    state.save(path)

    reloaded = load_state(path)
    assert reloaded.warning is None
    assert not reloaded.is_new(listing)
    assert reloaded.is_new(make_listing(listing_id="43"))


def test_same_id_different_company_is_still_new(tmp_path: Path) -> None:
    path = tmp_path / ".interninbox-state.json"
    state = load_state(path)
    state.record([make_listing(listing_id="42", company="aurora-widgets")])
    state.save(path)
    reloaded = load_state(path)
    assert reloaded.is_new(make_listing(listing_id="42", company="harborline"))


def test_corrupt_state_warns_once_and_treats_all_as_new(tmp_path: Path) -> None:
    path = tmp_path / ".interninbox-state.json"
    path.write_text("{ not json", encoding="utf-8")
    state = load_state(path)
    assert state.warning is not None and "treating every listing as new" in state.warning
    assert state.is_new(make_listing())


def test_wrong_shape_state_warns(tmp_path: Path) -> None:
    path = tmp_path / ".interninbox-state.json"
    path.write_text('{"seen": "oops"}', encoding="utf-8")
    state = load_state(path)
    assert state.warning is not None
    assert state.is_new(make_listing())
