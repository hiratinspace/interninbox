"""Community-list source fetching and mapping (synthetic fixture only)."""

import datetime as dt

import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox import sources
from interninbox.fetch import Fetcher
from interninbox.models import AdapterError


def _handler(request):
    assert request.url.host == "raw.githubusercontent.com"
    return json_response(load_fixture("sources/simplify.json"))


def test_fetch_source_maps_active_visible_entries(instant_fetcher) -> None:
    with instant_fetcher(make_transport(_handler)) as fetcher:
        listings = sources.fetch_source(fetcher, "simplify")
    # 6 fixture rows: one inactive, one hidden, one malformed -> 3 survive.
    assert [listing.title for listing in listings] == [
        "Quantum Software Intern",
        "2027 Mapping Analyst Program",
        "Systems Intern (Clearance)",
    ]
    first = listings[0]
    assert first.company == "Aurora Widgets"
    assert first.source == "simplify"
    assert first.curated is True
    assert first.identity == "simplify:aaaa-1111"
    assert first.sponsorship == "offers-sponsorship"
    assert first.terms == ("Summer 2027",)
    assert first.degrees == ("Bachelor's",)
    assert first.locations == ("Seattle, WA",)
    assert first.posted_at == dt.datetime.fromtimestamp(1754902800, tz=dt.UTC)
    by_title = {listing.title: listing for listing in listings}
    assert by_title["2027 Mapping Analyst Program"].sponsorship == "no-sponsorship"
    assert by_title["Systems Intern (Clearance)"].sponsorship == "citizenship-required"


def test_seasonal_source_names_share_the_simplify_family(instant_fetcher) -> None:
    with instant_fetcher(make_transport(_handler)) as fetcher:
        listings = sources.fetch_source(fetcher, "simplify-summer2026")
    assert listings[0].source == "simplify"
    assert listings[0].identity == "simplify:aaaa-1111"  # stable across seasons


def test_large_list_bypasses_the_instance_size_cap() -> None:
    # The real listings.json is >10 MB; fetch_source must use its own cap.
    with Fetcher(
        transport=make_transport(_handler), sleep=lambda _: None, max_response_bytes=512
    ) as fetcher:
        assert sources.fetch_source(fetcher, "simplify")


def test_wrong_top_level_shape_raises(instant_fetcher) -> None:
    with instant_fetcher(make_transport(lambda _: json_response({"nope": 1}))) as fetcher:
        with pytest.raises(AdapterError, match="unexpected"):
            sources.fetch_source(fetcher, "simplify")


def test_unknown_source_name_raises(instant_fetcher) -> None:
    with instant_fetcher(make_transport(_handler)) as fetcher:
        with pytest.raises(AdapterError, match="unknown source"):
            sources.fetch_source(fetcher, "linkedin")
