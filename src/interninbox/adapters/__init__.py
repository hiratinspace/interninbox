"""ATS adapters, one module per documented public job-board API."""

from __future__ import annotations

from collections.abc import Callable

from interninbox.adapters import (
    ashby,
    greenhouse,
    lever,
    recruitee,
    smartrecruiters,
    website,
    workable,
)
from interninbox.models import Listing

# ats name -> fetch(fetcher, slug) -> list[Listing]
# fetch(fetcher, slug, *, content=False) -> list[Listing]; `content` asks for
# job descriptions where they cost an opt-in (Greenhouse, Workable).
# "website" is the pseudo-ATS whose slug is a bare domain: it reads the
# site's own sitemaps and JobPosting JSON-LD instead of an ATS API.
ADAPTERS: dict[str, Callable[..., list[Listing]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "smartrecruiters": smartrecruiters.fetch,
    "workable": workable.fetch,
    "recruitee": recruitee.fetch,
    "website": website.fetch,
}
