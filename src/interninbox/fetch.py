"""Polite HTTP fetching — the politeness is baked in, not optional.

Rules, enforced centrally so no adapter can forget them:
  - sequential requests, with at least `MIN_HOST_DELAY` seconds between any
    two requests to the same host;
  - a 15 second timeout per request;
  - exactly one retry on a transient failure (network error or 5xx);
  - an honest User-Agent identifying this tool (USAJOBS overrides it with
    the registered email its API contract requires).
"""

from __future__ import annotations

import time
import urllib.parse
from collections.abc import Callable

import httpx

from interninbox import USER_AGENT
from interninbox.models import AdapterError

MIN_HOST_DELAY = 0.5
TIMEOUT_SECONDS = 15.0


class Fetcher:
    """One shared, host-aware, rate-limited HTTP client for a whole scan."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        min_host_delay: float = MIN_HOST_DELAY,
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
                response = self._client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc}"
                continue  # transient — retry once
            if response.status_code >= 500:
                last_error = f"server error HTTP {response.status_code}"
                continue  # transient — retry once
            if response.status_code >= 400:
                raise AdapterError(
                    f"HTTP {response.status_code} from {host}: check the slug exists"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise AdapterError(f"response from {host} is not valid JSON: {exc}") from exc
        raise AdapterError(f"{last_error} (after retry)")
