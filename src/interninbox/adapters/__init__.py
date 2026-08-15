"""ATS adapters, one module per documented public job-board API."""

from __future__ import annotations

from collections.abc import Callable

from interninbox.adapters import ashby, greenhouse, lever
from interninbox.models import Listing

# ats name -> fetch(fetcher, slug) -> list[Listing]
# fetch(fetcher, slug, *, content=False) -> list[Listing]; `content` asks for
# job descriptions where they cost an opt-in (Greenhouse).
ADAPTERS: dict[str, Callable[..., list[Listing]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
}
