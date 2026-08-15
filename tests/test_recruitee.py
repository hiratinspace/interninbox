"""Recruitee adapter tests (synthetic fixtures only)."""

import datetime as dt

import httpx
import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox.adapters import ADAPTERS, recruitee
from interninbox.config import KNOWN_ATS
from interninbox.models import AdapterError


def _board() -> object:
    return load_fixture("recruitee/silverfen.json")


def test_parse_full_board() -> None:
    listings = recruitee.parse(_board(), "silverfen")
    assert len(listings) == 3
    first = listings[0]
    assert first.source == "recruitee"
    assert first.company == "silverfen"  # the API exposes no display name
    assert first.listing_id == "2140001"
    assert first.title == "Pipeline Developer Intern (Summer 2027)"
    assert first.url == "https://silverfen.recruitee.com/o/pipeline-developer-intern-summer-2027"
    # published_at is "YYYY-MM-DD HH:MM:SS UTC", not ISO-8601; parsed as UTC.
    assert first.posted_at == dt.datetime(2026, 8, 1, 9, 30, tzinfo=dt.UTC)
    assert first.terms == ("Summer 2027",)
    assert first.key == "recruitee:silverfen:2140001"


def test_missing_careers_url_falls_back_to_the_board_page() -> None:
    listings = recruitee.parse(_board(), "silverfen")
    # The second offer carries no careers_url; the slug builds the public URL.
    assert listings[1].url == "https://silverfen.recruitee.com/o/strategy-early-careers-programme"


def test_posted_date_tolerates_format_drift() -> None:
    listings = recruitee.parse(_board(), "silverfen")
    # ISO-8601 drift (not the documented "YYYY-MM-DD HH:MM:SS UTC") leaves
    # posted unset rather than guessing.
    assert listings[2].posted_at is None


def test_locations_join_structured_entries_and_fall_back() -> None:
    listings = recruitee.parse(_board(), "silverfen")
    # Structured `locations` entries join city + state + country per entry.
    assert listings[0].locations == ("Bristol, United Kingdom", "London, United Kingdom")
    # Empty locations list, blank top-level fields, remote true: Remote.
    assert listings[1].locations == ("Remote",)
    # Empty locations list falls back to top-level city/state_name/country.
    assert listings[2].locations == ("Montreal, Quebec, Canada",)


def test_inline_descriptions_classified_with_evidence() -> None:
    listings = recruitee.parse(_board(), "silverfen")
    assert listings[0].sponsorship == "no-sponsorship"
    assert "unable to sponsor" in listings[0].sponsorship_evidence
    # The sponsorship sentence lives in `requirements`, which is read too.
    assert listings[1].sponsorship == "offers-sponsorship"
    # Empty description and requirements: unknown.
    assert listings[2].sponsorship is None
    assert listings[2].sponsorship_evidence is None


def test_employment_type_code_maps_to_intern_signal() -> None:
    listings = recruitee.parse(_board(), "silverfen")
    assert listings[0].employment_intern is True
    # "Strategy - Early Careers Programme" has no intern word in any language;
    # employment_type_code == "internship" is the signal that keeps it.
    assert listings[1].employment_intern is True
    assert listings[2].employment_intern is False


def test_empty_board_parses_to_no_listings() -> None:
    assert recruitee.parse({"offers": []}, "onexrobotics") == []


def test_wrong_shape_and_malformed_entry_raise() -> None:
    with pytest.raises(AdapterError, match="unexpected Recruitee"):
        recruitee.parse([], "silverfen")
    with pytest.raises(AdapterError, match="unexpected Recruitee"):
        recruitee.parse({"offers": "nope"}, "silverfen")
    with pytest.raises(AdapterError, match="malformed Recruitee"):
        recruitee.parse({"offers": [{"slug": "mystery-role"}]}, "silverfen")


def test_fetch_hits_documented_endpoint_in_one_request(instant_fetcher) -> None:
    # All published offers arrive in one response: the API has no pagination.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("recruitee/silverfen.json"))

    with instant_fetcher(make_transport(handler)) as fetcher:
        listings = recruitee.fetch(fetcher, "silverfen")
    assert len(listings) == 3
    assert len(seen) == 1
    assert str(seen[0].url) == "https://silverfen.recruitee.com/api/offers/"


def test_content_flag_costs_no_extra_request(instant_fetcher) -> None:
    # Descriptions are inline in the one response, so content=True changes
    # nothing: same single request, same classification.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("recruitee/silverfen.json"))

    with instant_fetcher(make_transport(handler)) as fetcher:
        listings = recruitee.fetch(fetcher, "silverfen", content=True)
    assert len(seen) == 1
    assert listings[0].sponsorship == "no-sponsorship"


def test_registered_as_a_known_ats() -> None:
    assert "recruitee" in KNOWN_ATS
    assert ADAPTERS["recruitee"] is recruitee.fetch
