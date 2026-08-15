"""Shared test helpers, all tests are offline (httpx.MockTransport only)."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from interninbox.fetch import Fetcher
from interninbox.models import Listing

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(relative: str) -> object:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def fixture_bytes(relative: str) -> bytes:
    return (FIXTURES / relative).read_bytes()


def make_transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def json_response(payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


@pytest.fixture
def instant_fetcher() -> Callable[[httpx.MockTransport], Fetcher]:
    """Build a Fetcher whose politeness delay costs no wall-clock time."""

    def build(transport: httpx.MockTransport) -> Fetcher:
        return Fetcher(transport=transport, sleep=lambda _: None)

    return build


def make_listing(
    *,
    company: str = "aurora-widgets",
    source: str = "greenhouse",
    listing_id: str = "1",
    title: str = "Software Engineering Intern",
    url: str = "https://boards.example-greenhouse.test/aurora-widgets/jobs/1",
    locations: tuple[str, ...] = ("New York, NY",),
    posted_at: dt.datetime | None = None,
    sponsorship: str | None = None,
    sponsorship_evidence: str | None = None,
    terms: tuple[str, ...] = (),
    degrees: tuple[str, ...] = (),
    curated: bool = False,
) -> Listing:
    return Listing(
        company=company,
        source=source,
        listing_id=listing_id,
        title=title,
        url=url,
        locations=locations,
        posted_at=posted_at,
        sponsorship=sponsorship,
        sponsorship_evidence=sponsorship_evidence,
        terms=terms,
        degrees=degrees,
        curated=curated,
    )
