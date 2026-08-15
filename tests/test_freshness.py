"""--since parsing and filtering."""

import datetime as dt

import pytest
from conftest import make_listing

from interninbox.freshness import apply_since, parse_since

_NOW = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.UTC)


def test_parse_since_units() -> None:
    assert parse_since("7d") == dt.timedelta(days=7)
    assert parse_since("36h") == dt.timedelta(hours=36)
    assert parse_since("2w") == dt.timedelta(weeks=2)


@pytest.mark.parametrize("bad", ["", "7", "d7", "3m", "-2d", "7 d"])
def test_parse_since_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError, match="like 7d"):
        parse_since(bad)


def test_apply_since_keeps_fresh_and_undated() -> None:
    fresh = make_listing(listing_id="1", posted_at=_NOW - dt.timedelta(days=2))
    stale = make_listing(listing_id="2", posted_at=_NOW - dt.timedelta(days=30))
    undated = make_listing(listing_id="3", posted_at=None)
    naive_fresh = make_listing(
        listing_id="4", posted_at=(_NOW - dt.timedelta(days=1)).replace(tzinfo=None)
    )
    kept = apply_since([fresh, stale, undated, naive_fresh], dt.timedelta(days=7), now=_NOW)
    assert [listing.listing_id for listing in kept] == ["1", "3", "4"]
