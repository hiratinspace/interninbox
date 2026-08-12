"""Polite HTTP fetching, the politeness is baked in, not optional.

Rules, enforced centrally so no adapter can forget them:
  - sequential requests, with at least `MIN_HOST_DELAY` seconds between any
    two requests to the same host;
  - a 15 second timeout per request;
  - exactly one retry on a transient failure (network error or 5xx);
  - an honest User-Agent identifying this tool (USAJOBS overrides it with
    the registered email its API contract requires).
"""

from __future__ import annotations

import json
import time
import urllib.parse
from collections.abc import Callable

import httpx

from interninbox import USER_AGENT
from interninbox.models import AdapterError

MIN_HOST_DELAY = 0.5
TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BYTES = 10_000_000  # no board API legitimately sends 10 MB of JSON
READ_DEADLINE_SECONDS = 60.0  # total body-download budget, not per-socket-read


def _client_error(status: int, host: str) -> str:
    if status in (401, 403):
        return (
            f"HTTP {status} from {host}: request refused (an API-key problem, or the "
            "host is blocking automated requests, not a slug problem)"
        )
    if status == 429:
        return f"HTTP 429 from {host}: rate limited, wait a while before rescanning"
    if status in (404, 410):
        return f"HTTP {status} from {host}: board not found, check the slug exists"
    return f"HTTP {status} from {host}"


def _retry_after_seconds(header_value: str | None) -> float:
    """Seconds to wait before the single 429 retry, header value capped at 10 s."""
    try:
        seconds = float(header_value) if header_value is not None else 2.0
    except ValueError:
        seconds = 2.0  # an HTTP-date Retry-After: use the default rather than parse it
    return max(0.0, min(seconds, 10.0))


def _parse_json(body: bytes, host: str) -> object:
    try:
        return json.loads(body)
    except RecursionError:
        raise AdapterError(f"response from {host} is nested too deeply to parse") from None
    except ValueError as exc:
        raise AdapterError(f"response from {host} is not valid JSON: {exc}") from exc


class Fetcher:
    """One shared, host-aware, rate-limited HTTP client for a whole scan."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        min_host_delay: float = MIN_HOST_DELAY,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        self._client = httpx.Client(
            timeout=TIMEOUT_SECONDS,
            transport=transport,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self._sleep = sleep
        self._clock = clock
        self._min_host_delay = min_host_delay
        self._max_response_bytes = max_response_bytes
        self._last_request_at: dict[str, float] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _wait_for_host(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = self._clock() - last
            remaining = self._min_host_delay - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at[host] = self._clock()

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> object:
        """GET `url` and return the decoded JSON body.

        Raises `AdapterError` with a one-line human message on any failure
        (after one retry for transient ones).
        """
        host = urllib.parse.urlsplit(url).netloc
        last_error: str = "unknown error"
        for _attempt in (1, 2):
            self._wait_for_host(host)
            try:
                with self._client.stream(
                    "GET", url, params=params, headers=headers, follow_redirects=follow_redirects
                ) as response:
                    if response.status_code >= 500:
                        last_error = f"server error HTTP {response.status_code}"
                        continue  # transient, retry once
                    if response.status_code == 429 and _attempt == 1:
                        self._sleep(_retry_after_seconds(response.headers.get("Retry-After")))
                        last_error = f"HTTP 429 from {host} (rate limited)"
                        continue  # one polite retry, then _client_error below reports it
                    if response.status_code >= 400:
                        raise AdapterError(_client_error(response.status_code, host))
                    if response.status_code >= 300:
                        raise AdapterError(
                            f"unexpected redirect (HTTP {response.status_code}) from {host}"
                        )
                    body = self._read_limited(response, host)
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc}"
                continue  # transient, retry once
            return _parse_json(body, host)
        raise AdapterError(f"{last_error} (after retry)")

    def _read_limited(self, response: httpx.Response, host: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        started = self._clock()
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self._max_response_bytes:
                raise AdapterError(
                    f"response from {host} is larger than {self._max_response_bytes} bytes, "
                    "refusing it"
                )
            if self._clock() - started > READ_DEADLINE_SECONDS:
                raise AdapterError(f"response from {host} is downloading too slowly, gave up")
            chunks.append(chunk)
        return b"".join(chunks)
