"""Greenhouse adapter parse + fetch tests (synthetic fixtures only)."""

import datetime as dt

import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox.adapters import greenhouse
from interninbox.models import AdapterError


def test_parse_full_board() -> None:
    listings = greenhouse.parse(load_fixture("greenhouse/aurora_widgets.json"), "aurora-widgets")
    assert len(listings) == 5
    first = listings[0]
    assert first.company == "aurora-widgets"
    assert first.source == "greenhouse"
    assert first.listing_id == "9100001"
    assert first.title == "Software Engineering Intern (Summer 2027)"
    assert first.url.endswith("/jobs/9100001")
    assert first.locations == ("New York, NY",)
    assert first.posted_at == dt.datetime.fromisoformat("2026-08-01T09:00:00-04:00")


def test_parse_tolerates_null_location_and_bad_date() -> None:
    listings = greenhouse.parse(load_fixture("greenhouse/aurora_widgets.json"), "aurora-widgets")
    no_location = listings[4]
    assert no_location.locations == ()
    assert no_location.posted_at is None


def test_parse_empty_board() -> None:
    assert greenhouse.parse(load_fixture("greenhouse/empty.json"), "aurora-widgets") == []


def test_parse_missing_jobs_key_raises() -> None:
    with pytest.raises(AdapterError, match="no jobs array"):
        greenhouse.parse(load_fixture("greenhouse/missing_jobs_key.json"), "aurora-widgets")


def test_parse_malformed_job_entry_raises() -> None:
    payload = {"jobs": [{"id": 1, "title": "Intern"}]}  # missing absolute_url
    with pytest.raises(AdapterError, match="malformed Greenhouse job entry"):
        greenhouse.parse(payload, "aurora-widgets")


def test_fetch_hits_documented_endpoint(instant_fetcher) -> None:
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        return json_response(load_fixture("greenhouse/empty.json"))

    with instant_fetcher(make_transport(handler)) as fetcher:
        assert greenhouse.fetch(fetcher, "aurora-widgets") == []
    assert seen == ["https://boards-api.greenhouse.io/v1/boards/aurora-widgets/jobs"]
