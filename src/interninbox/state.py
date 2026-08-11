"""The seen-listings state file behind `--new-only`.

Lives next to the config as `.interninbox-state.json` (override with
`--state PATH`). Every scan updates it — flag or not — so "new" always
means "since the last scan". A corrupt or missing file means everything is
new: warn once, never crash.
"""

from __future__ import annotations

import json
from pathlib import Path

from interninbox.models import Listing

STATE_FILE_NAME = ".interninbox-state.json"
_VERSION = 1


class State:
    def __init__(self, seen: dict[str, dict[str, str]], warning: str | None = None) -> None:
        # key -> {"url": ...} ; the key already encodes source/company/id.
        self._seen = seen
        self.warning = warning

    def is_new(self, listing: Listing) -> bool:
        return listing.key not in self._seen

    def record(self, listings: list[Listing]) -> None:
        for listing in listings:
            self._seen[listing.key] = {"url": listing.url}

    def save(self, path: Path) -> None:
        payload = {"version": _VERSION, "seen": self._seen}
        path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def load_state(path: Path) -> State:
    """Load the state file, degrading gracefully — see module docstring."""
    if not path.exists():
        return State({})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        seen = payload["seen"]
        if not isinstance(seen, dict):
            raise ValueError("'seen' is not an object")
        cleaned = {
            str(key): {"url": str(value.get("url", ""))}
            for key, value in seen.items()
            if isinstance(value, dict)
        }
        return State(cleaned)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return State(
            {},
            warning=(
                f"state file {path} could not be read ({exc}) — treating every "
                "listing as new and rewriting it after this scan"
            ),
        )
