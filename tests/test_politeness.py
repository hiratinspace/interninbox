"""Politeness guarantees: same-host delay, timeout config, single retry."""

import httpx
import pytest
from conftest import json_response, make_transport

from interninbox import USER_AGENT
from interninbox.fetch import Fetcher
from interninbox.models import AdapterError


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _fetcher(handler, clock: FakeClock, sleeps: list[float]) -> Fetcher:
    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    return Fetcher(transport=make_transport(handler), sleep=sleep, clock=clock)


def test_same_host_requests_are_delayed() -> None:
    clock = FakeClock()
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now += 0.1  # each request takes 100 ms
        return json_response({})

    with _fetcher(handler, clock, sleeps) as fetcher:
        fetcher.get_json("https://api.lever.co/v0/postings/one")
        fetcher.get_json("https://api.lever.co/v0/postings/two")
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.4)  # 500 ms minimum minus the 100 ms elapsed


def test_different_hosts_are_not_delayed() -> None:
    clock = FakeClock()
    sleeps: list[float] = []
    with _fetcher(lambda _: json_response({}), clock, sleeps) as fetcher:
        fetcher.get_json("https://api.lever.co/v0/postings/one")
        fetcher.get_json("https://boards-api.greenhouse.io/v1/boards/two/jobs")
    assert sleeps == []


def test_honest_user_agent_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response({})

    with Fetcher(transport=make_transport(handler), sleep=lambda _: None) as fetcher:
        fetcher.get_json("https://api.lever.co/v0/postings/one")
    assert seen[0].headers["User-Agent"] == USER_AGENT
    assert "interninbox/" in USER_AGENT


def test_transient_5xx_retried_once_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        return json_response({"ok": True})

    with Fetcher(transport=make_transport(handler), sleep=lambda _: None) as fetcher:
        assert fetcher.get_json("https://api.lever.co/v0/postings/one") == {"ok": True}
    assert len(calls) == 2


def test_persistent_5xx_fails_after_one_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500)

    with Fetcher(transport=make_transport(handler), sleep=lambda _: None) as fetcher:
        with pytest.raises(AdapterError, match="after retry"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")
    assert len(calls) == 2


def test_network_error_retried_once() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("synthetic network failure", request=request)

    with Fetcher(transport=make_transport(handler), sleep=lambda _: None) as fetcher:
        with pytest.raises(AdapterError, match="network error"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")
    assert len(calls) == 2


def test_4xx_is_not_retried_and_mentions_slug_check() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with Fetcher(transport=make_transport(handler), sleep=lambda _: None) as fetcher:
        with pytest.raises(AdapterError, match="check the slug"):
            fetcher.get_json("https://api.lever.co/v0/postings/nope")
    assert len(calls) == 1


def test_non_json_body_raises_adapter_error() -> None:
    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(200, text="Not Found")),
        sleep=lambda _: None,
    ) as fetcher:
        with pytest.raises(AdapterError, match="not valid JSON"):
            fetcher.get_json("https://api.ashbyhq.com/posting-api/job-board/garbage")


def test_401_mentions_key_or_blocking_not_slug() -> None:
    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(401)), sleep=lambda _: None
    ) as fetcher:
        with pytest.raises(AdapterError, match="request refused"):
            fetcher.get_json("https://data.usajobs.gov/api/search")


def test_429_retried_once_honoring_retry_after() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return json_response({"ok": True})

    with Fetcher(transport=make_transport(handler), sleep=sleeps.append) as fetcher:
        assert fetcher.get_json("https://api.lever.co/v0/postings/one") == {"ok": True}
    assert len(calls) == 2
    assert 3.0 in sleeps


def test_persistent_429_reports_rate_limit_not_slug() -> None:
    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(429)), sleep=lambda _: None
    ) as fetcher:
        with pytest.raises(AdapterError, match="rate limited"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")


def test_oversized_response_is_refused() -> None:
    big = b'{"jobs": "' + b"x" * 2048 + b'"}'
    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(200, content=big)),
        sleep=lambda _: None,
        max_response_bytes=1024,
    ) as fetcher:
        with pytest.raises(AdapterError, match="larger than"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")


def test_pathological_nesting_is_an_adapter_error() -> None:
    depth = 100_000
    body = b"[" * depth + b"]" * depth
    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(200, content=body)),
        sleep=lambda _: None,
    ) as fetcher:
        with pytest.raises(AdapterError, match="nested too deeply"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")


def test_dripping_response_hits_read_deadline() -> None:
    clock = FakeClock()

    def drip():
        yield b'{"jobs"'
        clock.now += 61.0  # the second chunk arrives after the deadline
        yield b": []}"

    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(200, content=drip())),
        sleep=lambda _: None,
        clock=clock,
    ) as fetcher:
        with pytest.raises(AdapterError, match="too slowly"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")


def test_per_call_max_response_bytes_override() -> None:
    big = b'{"jobs": "' + b"x" * 2048 + b'"}'
    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(200, content=big)),
        sleep=lambda _: None,
        max_response_bytes=1024,
    ) as fetcher:
        # The instance cap would refuse this body; the per-call override allows it.
        assert fetcher.get_json(
            "https://api.lever.co/v0/postings/one", max_response_bytes=1_000_000
        )
        with pytest.raises(AdapterError, match="larger than"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")


def test_conditional_get_sends_etag_and_handles_304() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.headers.get("If-None-Match") == '"abc"':
            return httpx.Response(304)
        return httpx.Response(200, json={"ok": True}, headers={"ETag": '"abc"'})

    with Fetcher(transport=make_transport(handler), sleep=lambda _: None) as fetcher:
        payload, etag = fetcher.get_json_conditional(
            "https://raw.githubusercontent.com/x/y/z.json", etag=None
        )
        assert payload == {"ok": True} and etag == '"abc"'
        assert "If-None-Match" not in calls[0].headers

        payload, etag = fetcher.get_json_conditional(
            "https://raw.githubusercontent.com/x/y/z.json", etag='"abc"'
        )
        assert payload is None  # 304: caller should use its cache
        assert etag == '"abc"'
        assert calls[1].headers["If-None-Match"] == '"abc"'
