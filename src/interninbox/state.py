"""The seen-listings state file behind `--new-only`.

Lives next to the config (see `default_state_path`; override with `--state
PATH`). Every scan updates it — flag or not — so "new" always means "since
the last scan". A corrupt or missing file means everything is new: warn once,
never crash.

Format (v2): `{"version": 2, "seen": {"<key>": "<last-seen ISO date>"}}`.
The stored value is the last time the listing was seen, which lets old
entries be pruned so the file cannot grow forever. v1 files (whose values
were `{"url": ...}`) still load: their entries are recognized as seen and
re-stamped with the current time on the next save.

Two robustness properties matter for unattended (cron) use:
  - writes are atomic (a per-process temp file + `os.replace`), so a crash
    mid-write can never leave a half-written file and two overlapping runs
    never collide on one shared temp file;
  - saves union-merge with whatever is on disk at save time, so an overlapping
    run's additions are re-read and preserved rather than blindly clobbered.
    This is best-effort, not a lock: a genuinely simultaneous read/replace
    interleave can still lose one addition (full safety needs file locking —
    see KNOWN-ISSUES M8).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from interninbox.models import Listing

STATE_FILE_NAME = ".interninbox-state.json"
_VERSION = 2
RETENTION_DAYS = 365  # drop listings not seen in this long; bounds file growth

# key -> last-seen ISO date, or None for a legacy (v1) entry whose date is
# unknown until the next save re-stamps it.
_Seen = dict[str, "str | None"]


def default_state_path(config_path: Path) -> Path:
    """Where the state file lives for a given config, when `--state` is unset.

    The default config (`interninbox.toml`) keeps the plain
    `.interninbox-state.json`. Any other config name gets its own suffixed
    file, so two configs in one directory do not silently share state (L7).
    """
    parent = config_path.resolve().parent
    stem = config_path.stem
    if stem == "interninbox":
        return parent / STATE_FILE_NAME
    return parent / f".interninbox-state.{stem}.json"


class State:
    def __init__(self, seen: _Seen, warning: str | None = None) -> None:
        # The key already encodes source/company/id (or a stable identity).
        self._seen = seen
        self.warning = warning

    def is_new(self, listing: Listing) -> bool:
        return listing.key not in self._seen

    def record(self, listings: list[Listing], now: dt.datetime | None = None) -> None:
        stamp = (now or _utcnow()).isoformat()
        for listing in listings:
            self._seen[listing.key] = stamp

    def save(
        self,
        path: Path,
        now: dt.datetime | None = None,
        retention_days: int = RETENTION_DAYS,
    ) -> None:
        now = now or _utcnow()
        merged = _merge(self._seen, _read_seen(path))
        cutoff = (now - dt.timedelta(days=retention_days)).isoformat()
        kept = {
            key: (date if date is not None else now.isoformat())
            for key, date in merged.items()
            # A legacy (None) entry has no date yet, so it can't be too old.
            if date is None or date >= cutoff
        }
        payload = {"version": _VERSION, "seen": kept}
        text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
        # Write-then-rename: a crash, Ctrl-C, or full disk mid-write can never
        # leave a half-written (corrupt) state file behind. The temp name is
        # per-process so two overlapping runs never share (and rename away)
        # one another's temp file.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)  # never leave our temp file behind
            raise


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _newer(a: str | None, b: str | None) -> str | None:
    """The later of two ISO dates; a known date always beats an unknown one."""
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _merge(memory: _Seen, disk: _Seen) -> _Seen:
    """Union of in-memory and on-disk state, keeping the newest date per key.

    Re-reading the file at save time means a concurrent writer's additions
    are preserved rather than clobbered.
    """
    merged: _Seen = dict(memory)
    for key, date in disk.items():
        merged[key] = _newer(merged[key], date) if key in merged else date
    return merged


def _coerce_seen(raw: object) -> _Seen:
    """Validate and normalise the `seen` mapping across schema versions."""
    if not isinstance(raw, dict):
        raise ValueError("'seen' is not an object")
    cleaned: _Seen = {}
    for key, value in raw.items():
        if isinstance(value, str):  # v2: last-seen ISO date
            cleaned[str(key)] = value
        elif isinstance(value, dict):  # v1: {"url": ...}; date unknown
            cleaned[str(key)] = None
        # anything else is a malformed entry — skip it
    return cleaned


def _read_seen(path: Path) -> _Seen:
    """Best-effort read of the current on-disk `seen` map (empty on any error)."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _coerce_seen(payload["seen"])
    except (ValueError, KeyError, TypeError, OSError):
        return {}


def load_state(path: Path) -> State:
    """Load the state file, degrading gracefully — see module docstring."""
    if not path.exists():
        return State({})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return State(_coerce_seen(payload["seen"]))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return State(
            {},
            warning=(
                f"state file {path} could not be read ({exc}) — treating every "
                "listing as new and rewriting it after this scan"
            ),
        )
