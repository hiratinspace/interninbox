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


def test_content_flag_requests_descriptions_and_classifies(instant_fetcher) -> None:
    from conftest import load_fixture

    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        return json_response(load_fixture("greenhouse/aurora_widgets.json"))

    with instant_fetcher(make_transport(handler)) as fetcher:
        listings = greenhouse.fetch(fetcher, "aurora-widgets", content=True)
    assert "content=true" in seen[0]
    by_title = {listing.title: listing for listing in listings}
    swe = by_title["Software Engineering Intern (Summer 2027)"]
    assert swe.sponsorship == "no-sponsorship"  # escaped HTML content classified
    assert swe.terms == ("Summer 2027",)  # derived from the title
    assert by_title["Data Science Intern"].sponsorship == "offers-sponsorship"


def test_without_content_flag_no_param_and_unknown_sponsorship(instant_fetcher) -> None:
    from conftest import load_fixture

    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        payload = load_fixture("greenhouse/aurora_widgets.json")
        # The real API includes `content` only when ?content=true is sent.
        for job in payload["jobs"]:
            job.pop("content", None)
        return json_response(payload)

    with instant_fetcher(make_transport(handler)) as fetcher:
        listings = greenhouse.fetch(fetcher, "aurora-widgets")
    assert "content" not in seen[0]
    assert all(listing.sponsorship is None for listing in listings)
    assert all(listing.sponsorship_evidence is None for listing in listings)


def test_content_mode_populates_sponsorship_evidence(instant_fetcher) -> None:
    from conftest import load_fixture

    def handler(request):
        return json_response(load_fixture("greenhouse/aurora_widgets.json"))

    with instant_fetcher(make_transport(handler)) as fetcher:
        listings = greenhouse.fetch(fetcher, "aurora-widgets", content=True)
    by_title = {listing.title: listing for listing in listings}
    swe = by_title["Software Engineering Intern (Summer 2027)"]
    assert swe.sponsorship_evidence == "We are unable to sponsor visas for this role."
    data_science = by_title["Data Science Intern"]
    assert data_science.sponsorship_evidence == "Visa sponsorship is available for this role."
    assert by_title["Senior Backend Engineer, Widget Platform"].sponsorship_evidence is None
