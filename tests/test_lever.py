"""Lever adapter parse + fetch tests (synthetic fixtures only)."""

import datetime as dt

import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox.adapters import lever
from interninbox.models import AdapterError


def test_parse_full_board() -> None:
    listings = lever.parse(load_fixture("lever/cobalt_cartography.json"), "cobalt-cartography")
    assert len(listings) == 3
    first = listings[0]
    assert first.source == "lever"
    assert first.title == "Cartography Engineering Intern"
    assert first.url == "https://jobs.example-lever.test/cobalt-cartography/d3adbeef-0001"
    assert first.locations == ("San Francisco, CA", "New York, NY")


def test_parse_epoch_milliseconds_created_at() -> None:
    listings = lever.parse(load_fixture("lever/cobalt_cartography.json"), "cobalt-cartography")
    assert listings[0].posted_at == dt.datetime.fromtimestamp(1785592800, tz=dt.UTC)


def test_parse_remote_workplace_type_adds_remote_location() -> None:
    listings = lever.parse(load_fixture("lever/cobalt_cartography.json"), "cobalt-cartography")
    remote = listings[2]
    assert remote.locations == ("United States", "Remote")


def test_parse_empty_array() -> None:
    assert lever.parse([], "cobalt-cartography") == []


def test_parse_not_a_list_raises() -> None:
    with pytest.raises(AdapterError, match="not a JSON array"):
        lever.parse(load_fixture("lever/not_a_list.json"), "cobalt-cartography")


def test_parse_malformed_posting_raises() -> None:
    with pytest.raises(AdapterError, match="malformed Lever posting"):
        lever.parse([{"id": "x"}], "cobalt-cartography")  # missing text/hostedUrl


def test_fetch_hits_documented_endpoint(instant_fetcher) -> None:
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        return json_response([])

    with instant_fetcher(make_transport(handler)) as fetcher:
        assert lever.fetch(fetcher, "cobalt-cartography") == []
    assert seen == ["https://api.lever.co/v0/postings/cobalt-cartography?mode=json"]


def test_parse_all_locations_preferred_over_single() -> None:
    listings = lever.parse(load_fixture("lever/cobalt_cartography.json"), "cobalt-cartography")
    assert listings[0].locations == ("San Francisco, CA", "New York, NY")


def test_boolean_created_at_is_not_a_date() -> None:
    posting = {
        "id": "x1",
        "text": "QA Intern",
        "hostedUrl": "https://jobs.example-lever.test/x/x1",
        "createdAt": True,  # bool is an int subclass; must not become 1970-01-01
    }
    assert lever.parse([posting], "x")[0].posted_at is None


def test_description_plain_is_classified() -> None:
    listings = lever.parse(load_fixture("lever/cobalt_cartography.json"), "cobalt-cartography")
    by_title = {listing.title: listing for listing in listings}
    assert by_title["Cartography Engineering Intern"].sponsorship == "citizenship-required"
    assert by_title["Geospatial Data Intern"].sponsorship is None  # no description, unknown
