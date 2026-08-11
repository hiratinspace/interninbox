"""USAJOBS adapter tests: headers per its documented contract, pagination,
cross-page dedupe, malformed shapes (synthetic fixtures only)."""

import httpx
import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox.adapters import usajobs
from interninbox.config import UsaJobsConfig
from interninbox.models import AdapterError

CFG = UsaJobsConfig(enabled=True, keywords=("software",), email="fixture@example.test")


def _paginated_handler(requests_seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        page = request.url.params.get("Page")
        fixture = "usajobs/page1.json" if page == "1" else "usajobs/page2.json"
        return json_response(load_fixture(fixture))

    return handler


def test_fetch_sends_documented_auth_headers(instant_fetcher) -> None:
    requests_seen: list[httpx.Request] = []
    with instant_fetcher(make_transport(_paginated_handler(requests_seen))) as fetcher:
        usajobs.fetch(fetcher, CFG, "fixture-api-key")
    first = requests_seen[0]
    # User-Agent = registered email, plus the key; Host comes from the URL.
    assert first.headers["User-Agent"] == "fixture@example.test"
    assert first.headers["Authorization-Key"] == "fixture-api-key"
    assert first.url.host == "data.usajobs.gov"


def test_fetch_sends_student_hiring_path_and_keywords(instant_fetcher) -> None:
    requests_seen: list[httpx.Request] = []
    with instant_fetcher(make_transport(_paginated_handler(requests_seen))) as fetcher:
        usajobs.fetch(fetcher, CFG, "fixture-api-key")
    params = requests_seen[0].url.params
    assert params["HiringPath"] == "student"
    assert params["Keyword"] == "software"


def test_fetch_paginates_until_count_all_and_dedupes(instant_fetcher) -> None:
    requests_seen: list[httpx.Request] = []
    with instant_fetcher(make_transport(_paginated_handler(requests_seen))) as fetcher:
        listings = usajobs.fetch(fetcher, CFG, "fixture-api-key")
    # Two pages requested (page1 says CountAll=3, page1 carries 2 items).
    assert [request.url.params["Page"] for request in requests_seen] == ["1", "2"]
    # 800000002 appears on both pages — deduped on the control number.
    assert [listing.listing_id for listing in listings] == [
        "800000001",
        "800000002",
        "800000003",
    ]


def test_parse_item_maps_documented_fields() -> None:
    payload = load_fixture("usajobs/page1.json")
    item = payload["SearchResult"]["SearchResultItems"][0]
    listing = usajobs.parse_item(item)
    assert listing.source == "usajobs"
    assert listing.company == "Bureau of Fictional Statistics"
    assert listing.listing_id == "800000001"
    assert listing.title == "Student Trainee (Information Technology)"
    assert listing.url.endswith("/ViewDetails/800000001")
    assert listing.locations == (
        "Washington, District of Columbia",
        "Suitland, Maryland",
    )
    assert listing.posted_at is not None and listing.posted_at.tzinfo is not None


def test_parse_item_malformed_raises() -> None:
    with pytest.raises(AdapterError, match="malformed USAJOBS announcement"):
        usajobs.parse_item({"MatchedObjectId": "1"})  # no descriptor


def test_fetch_unexpected_shape_raises(instant_fetcher) -> None:
    with instant_fetcher(make_transport(lambda _: json_response({"nope": True}))) as fetcher:
        with pytest.raises(AdapterError, match="unexpected USAJOBS response shape"):
            usajobs.fetch(fetcher, CFG, "fixture-api-key")


def test_fetch_stops_on_empty_page(instant_fetcher) -> None:
    empty = {"SearchResult": {"SearchResultCountAll": 0, "SearchResultItems": []}}
    requests_seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return json_response(empty)

    with instant_fetcher(make_transport(handler)) as fetcher:
        assert usajobs.fetch(fetcher, CFG, "fixture-api-key") == []
    assert len(requests_seen) == 1


def test_no_hardcoded_host_header() -> None:
    # httpx derives Host from the URL; hardcoding it would follow a redirect
    # to a different host while still claiming to be data.usajobs.gov.
    assert "Host" not in usajobs._headers("key", "fixture@example.test")


def test_redirects_are_not_followed(instant_fetcher) -> None:
    def redirecting(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://elsewhere.test/x"})

    with instant_fetcher(make_transport(redirecting)) as fetcher:
        with pytest.raises(AdapterError, match="unexpected redirect"):
            usajobs.fetch(fetcher, CFG, "fixture-api-key")


def test_two_keywords_are_queried_separately_or_semantics(instant_fetcher) -> None:
    # USAJOBS ANDs words inside one Keyword param; a keyword LIST means OR,
    # so each keyword gets its own query (deduped on control number).
    requests_seen: list[httpx.Request] = []
    cfg = UsaJobsConfig(enabled=True, keywords=("software", "data"), email="fixture@example.test")
    with instant_fetcher(make_transport(_paginated_handler(requests_seen))) as fetcher:
        usajobs.fetch(fetcher, cfg, "fixture-api-key")
    keywords = {request.url.params["Keyword"] for request in requests_seen}
    assert keywords == {"software", "data"}


def test_truncation_at_page_cap_warns(instant_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["Page"]
        item = {
            "MatchedObjectId": f"9000{page}",
            "MatchedObjectDescriptor": {
                "PositionTitle": "Student Trainee (Synthetic)",
                "PositionURI": f"https://example.test/ViewDetails/9000{page}",
                "OrganizationName": "Bureau of Fictional Statistics",
            },
        }
        return json_response(
            {"SearchResult": {"SearchResultCountAll": 10000, "SearchResultItems": [item]}}
        )

    warnings: list[str] = []
    with instant_fetcher(make_transport(handler)) as fetcher:
        usajobs.fetch(fetcher, CFG, "fixture-api-key", warn=warnings.append)
    assert warnings and "truncated" in warnings[0]
