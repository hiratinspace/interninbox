"""Workable adapter tests (synthetic fixtures only)."""

import datetime as dt

import httpx
import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox.adapters import ADAPTERS, workable
from interninbox.config import KNOWN_ATS
from interninbox.models import AdapterError


def _board() -> object:
    return load_fixture("workable/meadowbrook.json")


def test_parse_full_board() -> None:
    listings = workable.parse(_board(), "meadowbrook-robotics")
    assert len(listings) == 3
    first = listings[0]
    assert first.source == "workable"
    assert first.company == "Meadowbrook Robotics"  # display name from the payload
    assert first.listing_id == "AB12CD3"
    assert first.title == "Robotics Software Intern (Summer 2027)"
    assert first.url == "https://apply.workable.com/j/AB12CD3"
    assert first.posted_at == dt.datetime(2026, 8, 1)  # date-only stamp, naive
    assert first.terms == ("Summer 2027",)
    # The state key stays slug-based even though the display name is mutable.
    assert first.key == "workable:meadowbrook-robotics:AB12CD3"


def test_locations_skip_hidden_and_fall_back_to_top_level() -> None:
    listings = workable.parse(_board(), "meadowbrook-robotics")
    # The hidden Munich entry is dropped; city + region + country joined.
    assert listings[0].locations == ("Ann Arbor, Michigan, United States",)
    # Empty locations list and blank top-level fields: telecommuting -> Remote.
    assert listings[1].locations == ("Remote",)
    # Empty locations list falls back to top-level city/state/country.
    assert listings[2].locations == ("Boulder, Colorado, United States",)


def test_descriptions_classified_with_evidence() -> None:
    listings = workable.parse(_board(), "meadowbrook-robotics")
    assert listings[0].sponsorship == "no-sponsorship"
    assert "unable to sponsor" in listings[0].sponsorship_evidence
    assert listings[1].sponsorship == "offers-sponsorship"
    # No description key (the default, detail-less response): unknown.
    assert listings[2].sponsorship is None
    assert listings[2].sponsorship_evidence is None


def test_empty_board_parses_to_no_listings() -> None:
    assert workable.parse({"name": "Grayce", "jobs": []}, "grayce") == []


def test_wrong_shape_and_malformed_entry_raise() -> None:
    with pytest.raises(AdapterError, match="unexpected Workable"):
        workable.parse([], "meadowbrook-robotics")
    with pytest.raises(AdapterError, match="malformed Workable"):
        workable.parse(
            {"name": "X", "jobs": [{"shortcode": "AB12CD3"}]}, "meadowbrook-robotics"
        )


def test_fetch_hits_documented_endpoint_in_one_request(instant_fetcher) -> None:
    # The whole board arrives in a single response: no pagination exists.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("workable/meadowbrook.json"))

    with instant_fetcher(make_transport(handler)) as fetcher:
        listings = workable.fetch(fetcher, "meadowbrook-robotics")
    assert len(listings) == 3
    assert len(seen) == 1
    assert str(seen[0].url).startswith(
        "https://www.workable.com/api/accounts/meadowbrook-robotics"
    )
    assert "details" not in seen[0].url.params  # descriptions are opt-in


def test_fetch_content_requests_details(instant_fetcher) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("workable/meadowbrook.json"))

    with instant_fetcher(make_transport(handler)) as fetcher:
        workable.fetch(fetcher, "meadowbrook-robotics", content=True)
    assert len(seen) == 1
    assert seen[0].url.params.get("details") == "true"


def test_registered_as_a_known_ats() -> None:
    assert "workable" in KNOWN_ATS
    assert ADAPTERS["workable"] is workable.fetch
