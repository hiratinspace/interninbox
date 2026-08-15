"""SmartRecruiters adapter tests (synthetic fixtures only)."""

import datetime as dt

import httpx
import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox.adapters import smartrecruiters
from interninbox.models import AdapterError


def test_parse_full_board() -> None:
    listings = smartrecruiters.parse(
        load_fixture("smartrecruiters/meridian.json"), "MeridianPay"
    )
    assert len(listings) == 3
    first = listings[0]
    assert first.source == "smartrecruiters"
    assert first.listing_id == "744000900000001"
    assert first.title == "Payments Software Intern (Summer 2027)"
    assert first.url == "https://jobs.smartrecruiters.com/MeridianPay/744000900000001"
    assert first.locations == ("Austin, TX, United States",)
    assert first.posted_at == dt.datetime(2026, 8, 1, 10, 0, 11, 853000, tzinfo=dt.UTC)
    assert first.terms == ("Summer 2027",)


def test_remote_flag_adds_remote_location() -> None:
    listings = smartrecruiters.parse(
        load_fixture("smartrecruiters/meridian.json"), "MeridianPay"
    )
    assert listings[1].locations == ("Remote",)  # empty fullLocation, remote true


def test_fetch_paginates_with_offset(instant_fetcher) -> None:
    requests_seen: list[httpx.Request] = []
    page = load_fixture("smartrecruiters/meridian.json")
    page["totalFound"] = 6  # our 3-entry page twice over -> exactly two requests

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return json_response(page)

    with instant_fetcher(make_transport(handler)) as fetcher:
        smartrecruiters.fetch(fetcher, "MeridianPay")
    offsets = [request.url.params.get("offset") for request in requests_seen]
    assert offsets == ["0", "100"]
    assert requests_seen[0].url.params.get("limit") == "100"


def test_truncation_at_page_cap_warns(instant_fetcher, monkeypatch) -> None:
    monkeypatch.setattr(smartrecruiters, "MAX_PAGES", 2)
    page = load_fixture("smartrecruiters/meridian.json")
    page["totalFound"] = 100_000
    warnings: list[str] = []
    with instant_fetcher(make_transport(lambda _: json_response(page))) as fetcher:
        smartrecruiters.fetch(fetcher, "MeridianPay", warn=warnings.append)
    assert warnings and "truncated" in warnings[0]


def test_wrong_shape_and_malformed_entry_raise() -> None:
    with pytest.raises(AdapterError, match="unexpected SmartRecruiters"):
        smartrecruiters.parse([], "MeridianPay")
    with pytest.raises(AdapterError, match="malformed SmartRecruiters"):
        smartrecruiters.parse({"totalFound": 1, "content": [{"id": "x"}]}, "MeridianPay")


def test_fetch_hits_documented_endpoint(instant_fetcher) -> None:
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        return json_response({"totalFound": 0, "content": []})

    with instant_fetcher(make_transport(handler)) as fetcher:
        assert smartrecruiters.fetch(fetcher, "MeridianPay") == []
    assert seen[0].startswith(
        "https://api.smartrecruiters.com/v1/companies/MeridianPay/postings"
    )
