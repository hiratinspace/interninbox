"""ATS adapters, one module per documented public job-board API."""

from __future__ import annotations

from collections.abc import Callable

from interninbox.adapters import ashby, greenhouse, lever
from interninbox.fetch import Fetcher
from interninbox.models import Listing

# ats name -> fetch(fetcher, slug) -> list[Listing]
ADAPTERS: dict[str, Callable[[Fetcher, str], list[Listing]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
}
