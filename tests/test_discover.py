"""Board discovery: probe the known ATS endpoints for a company's slug."""

import httpx
from conftest import json_response, make_transport

from interninbox.discover import find_boards


def _acme_transport():
    """acmecorp exists on Greenhouse; AcmeCorp is a real SR tenant."""

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "boards-api.greenhouse.io" and "/acmecorp/" in path:
            return json_response({"jobs": []})
        if host == "api.smartrecruiters.com" and "/AcmeCorp/" in path:
            return json_response({"totalFound": 12, "content": []})
        if host == "api.smartrecruiters.com":
            return json_response({"totalFound": 0, "content": []})  # SR: 200 for anything
        return httpx.Response(404)

    return make_transport(handler)


def test_finds_boards_across_ats(instant_fetcher) -> None:
    with instant_fetcher(_acme_transport()) as fetcher:
        found = find_boards(fetcher, "Acme Corp")
    assert "greenhouse:acmecorp" in found
    assert "smartrecruiters:AcmeCorp" in found
    # SR with totalFound 0 and 404 hosts are not reported.
    assert not any(label.startswith(("lever:", "ashby:")) for label in found)


def test_no_boards_found_is_empty(instant_fetcher) -> None:
    with instant_fetcher(make_transport(lambda _: httpx.Response(404))) as fetcher:
        assert find_boards(fetcher, "Ghost Startup") == []


def test_multiword_names_try_joined_and_hyphenated(instant_fetcher) -> None:
    probed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        probed.append(request.url.path)
        return httpx.Response(404)

    with instant_fetcher(make_transport(handler)) as fetcher:
        find_boards(fetcher, "Cobalt Cartography")
    joined = "".join(probed)
    assert "cobaltcartography" in joined
    assert "cobalt-cartography" in joined
