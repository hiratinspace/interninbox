"""`--since`: keep only recently posted listings.

Undated listings always pass (the keep-unknown rule used everywhere else);
naive timestamps are treated as UTC, matching the sort in output.py.
"""

from __future__ import annotations

import datetime as dt
import re

from interninbox.models import Listing

_SINCE = re.compile(r"^(\d+)([hdw])$")
_UNIT_HOURS = {"h": 1, "d": 24, "w": 24 * 7}


def parse_since(text: str) -> dt.timedelta:
    """"7d" / "36h" / "2w" -> a timedelta; anything else raises ValueError."""
    match = _SINCE.match(text.strip())
    if not match:
        raise ValueError(f"invalid --since value {text!r}: use a number and unit, like 7d, 36h, 2w")
    amount, unit = match.groups()
    return dt.timedelta(hours=int(amount) * _UNIT_HOURS[unit])


def apply_since(
    listings: list[Listing], window: dt.timedelta, now: dt.datetime | None = None
) -> list[Listing]:
    """Listings posted within `window` of `now`, plus every undated listing."""
    now = now or dt.datetime.now(tz=dt.UTC)
    cutoff = now - window
    kept: list[Listing] = []
    for listing in listings:
        posted = listing.posted_at
        if posted is None:
            kept.append(listing)
            continue
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=dt.UTC)
        if posted >= cutoff:
            kept.append(listing)
    return kept
