"""Seen-state behavior: first run, subsequent runs, corruption."""

import datetime as dt
import json
import os
from pathlib import Path

import pytest
from conftest import make_listing

from interninbox.state import load_state

_NOW = dt.datetime(2026, 8, 11, tzinfo=dt.UTC)


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


def test_save_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / ".interninbox-state.json"
    state = load_state(path)
    state.record([make_listing()])
    state.save(path)
    assert [entry.name for entry in tmp_path.iterdir()] == [path.name]


def test_failed_save_preserves_previous_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".interninbox-state.json"
    path.write_text('{"version": 1, "seen": {"old": {"url": ""}}}', encoding="utf-8")
    state = load_state(path)
    state.record([make_listing()])

    def no_space(self: Path, *args: object, **kwargs: object) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", no_space)
    with pytest.raises(OSError):
        state.save(path)
    monkeypatch.undo()
    assert "old" in json.loads(path.read_text(encoding="utf-8"))["seen"]


def test_stale_entries_are_pruned_on_save(tmp_path: Path) -> None:
    path = tmp_path / ".interninbox-state.json"
    old = _NOW - dt.timedelta(days=400)  # beyond the retention window
    state = load_state(path)
    state.record([make_listing(listing_id="stale")], now=old)
    state.record([make_listing(listing_id="fresh")], now=_NOW)
    state.save(path, now=_NOW, retention_days=365)

    reloaded = load_state(path)
    assert reloaded.is_new(make_listing(listing_id="stale"))  # pruned -> new again
    assert not reloaded.is_new(make_listing(listing_id="fresh"))  # within retention


def test_concurrent_writers_are_merged_not_clobbered(tmp_path: Path) -> None:
    # Two overlapping processes both load the (empty) file, each record a
    # different listing; the second save must not lose the first's write.
    path = tmp_path / ".interninbox-state.json"
    proc_a = load_state(path)
    proc_b = load_state(path)
    proc_a.record([make_listing(listing_id="A")], now=_NOW)
    proc_b.record([make_listing(listing_id="B")], now=_NOW)
    proc_b.save(path, now=_NOW)  # B writes first
    proc_a.save(path, now=_NOW)  # A must union-merge, not clobber B

    reloaded = load_state(path)
    assert not reloaded.is_new(make_listing(listing_id="A"))
    assert not reloaded.is_new(make_listing(listing_id="B"))


def test_saved_state_is_v2_and_stores_no_url(tmp_path: Path) -> None:
    path = tmp_path / ".interninbox-state.json"
    state = load_state(path)
    state.record([make_listing(url="https://tracker.example/secret-path")], now=_NOW)
    state.save(path, now=_NOW)
    raw = path.read_text(encoding="utf-8")
    assert "tracker.example" not in raw  # the dead url field is gone
    assert json.loads(raw)["version"] == 2


def test_v1_state_file_still_recognized_and_upgraded(tmp_path: Path) -> None:
    path = tmp_path / ".interninbox-state.json"
    listing = make_listing(listing_id="42")
    path.write_text(
        json.dumps({"version": 1, "seen": {listing.key: {"url": "u"}}}),
        encoding="utf-8",
    )
    state = load_state(path)
    assert state.warning is None
    assert not state.is_new(listing)  # legacy entry recognized

    state.save(path, now=_NOW)
    reloaded = load_state(path)
    assert not reloaded.is_new(listing)  # survives the upgrade
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2


def test_concurrent_saves_use_process_unique_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two overlapping processes must not collide on one shared "<state>.tmp":
    # a shared temp file lets one process's rename pull the file out from under
    # the other's os.replace. The temp name is per-process.
    path = tmp_path / ".interninbox-state.json"
    temps: list[str] = []
    real_replace = os.replace

    def spy_replace(src: object, dst: object) -> None:
        temps.append(Path(str(src)).name)
        real_replace(src, dst)

    monkeypatch.setattr("interninbox.state.os.replace", spy_replace)

    monkeypatch.setattr("interninbox.state.os.getpid", lambda: 111)
    proc_a = load_state(path)
    proc_a.record([make_listing(listing_id="A")], now=_NOW)
    proc_a.save(path, now=_NOW)

    monkeypatch.setattr("interninbox.state.os.getpid", lambda: 222)
    proc_b = load_state(path)
    proc_b.record([make_listing(listing_id="B")], now=_NOW)
    proc_b.save(path, now=_NOW)

    assert temps[0] != temps[1]  # different processes -> different temp files
