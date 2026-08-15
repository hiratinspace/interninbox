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


def test_source_cache_round_trip(instant_fetcher, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sources, "_cache_dir", lambda: tmp_path)
    calls: list[object] = []

    def handler(request):
        calls.append(request)
        if request.headers.get("If-None-Match") == '"v1"':
            return __import__("httpx").Response(304)
        return __import__("httpx").Response(
            200,
            json=load_fixture("sources/simplify.json"),
            headers={"ETag": '"v1"'},
        )

    with instant_fetcher(make_transport(handler)) as fetcher:
        first = sources.fetch_source(fetcher, "simplify")
        assert (tmp_path / "simplify.json").is_file()  # body cached
        assert (tmp_path / "simplify.etag").read_text() == '"v1"'
        second = sources.fetch_source(fetcher, "simplify")  # server says 304

    assert [listing.title for listing in first] == [listing.title for listing in second]
    assert len(calls) == 2  # one full fetch, one conditional


def test_corrupt_cache_falls_back_to_full_fetch(instant_fetcher, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sources, "_cache_dir", lambda: tmp_path)
    (tmp_path / "simplify.json").write_text("{ nope", encoding="utf-8")
    (tmp_path / "simplify.etag").write_text('"v1"', encoding="utf-8")
    full_fetches: list[bool] = []

    def handler(request):
        conditional = "If-None-Match" in request.headers
        full_fetches.append(not conditional)
        if conditional:
            return __import__("httpx").Response(304)
        return __import__("httpx").Response(
            200, json=load_fixture("sources/simplify.json"), headers={"ETag": '"v2"'}
        )

    with instant_fetcher(make_transport(handler)) as fetcher:
        listings = sources.fetch_source(fetcher, "simplify")
    assert listings  # recovered by refetching in full
    assert True in full_fetches


def test_unwritable_cache_never_breaks_the_scan(instant_fetcher, monkeypatch) -> None:
    monkeypatch.setattr(sources, "_cache_dir", lambda: (_ for _ in ()).throw(OSError(13, "denied")))
    with instant_fetcher(make_transport(_handler)) as fetcher:
        assert sources.fetch_source(fetcher, "simplify")
