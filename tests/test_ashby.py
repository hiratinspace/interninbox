"""Ashby adapter parse + fetch tests (synthetic fixtures only)."""

import datetime as dt

import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox.adapters import ashby
from interninbox.models import AdapterError


def test_parse_full_board() -> None:
    listings = ashby.parse(load_fixture("ashby/harborline.json"), "harborline")
    assert len(listings) == 3
    first = listings[0]
    assert first.source == "ashby"
    assert first.listing_id == "1b2c3d4e-1111-4222-8333-444455556666"
    assert first.title == "Platform Engineering Intern (Fall)"
    assert first.url == "https://jobs.example-ashby.test/harborline/1b2c3d4e"
    assert first.locations == ("Seattle, WA",)
    assert first.posted_at == dt.datetime(2026, 8, 3, 16, 0, tzinfo=dt.UTC)


def test_parse_remote_workplace_type_adds_remote_location() -> None:
    listings = ashby.parse(load_fixture("ashby/harborline.json"), "harborline")
    remote = listings[1]
    assert remote.locations == ("North America", "Europe", "Remote")


def test_parse_missing_jobs_raises() -> None:
    with pytest.raises(AdapterError, match="no jobs array"):
        ashby.parse({"apiVersion": "1"}, "harborline")


def test_parse_malformed_job_raises() -> None:
    with pytest.raises(AdapterError, match="malformed Ashby job entry"):
        ashby.parse({"jobs": [{"id": "x", "title": "Intern"}]}, "harborline")  # no jobUrl


def test_fetch_hits_documented_endpoint(instant_fetcher) -> None:
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        return json_response({"jobs": []})

    with instant_fetcher(make_transport(handler)) as fetcher:
        assert ashby.fetch(fetcher, "harborline") == []
    assert seen == ["https://api.ashbyhq.com/posting-api/job-board/harborline"]


def test_parse_secondary_locations_included_and_deduped() -> None:
    listings = ashby.parse(load_fixture("ashby/harborline.json"), "harborline")
    # Primary "North America" + secondary "Europe"; the duplicate secondary
    # "North America" is dropped; "Remote" still appended from workplaceType.
    assert listings[1].locations == ("North America", "Europe", "Remote")
