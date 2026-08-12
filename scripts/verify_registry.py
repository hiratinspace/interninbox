"""Maintainer tool: live-verify every registry slug against its public API.

Run manually when authoring or updating the registry (never from tests):
    .venv/bin/python scripts/verify_registry.py
Sequential, ~0.6 s between requests, honest User-Agent, the same manners the
tool itself has. Prints PASS/FAIL per entry and exits non-zero on any FAIL.
"""

from __future__ import annotations

import sys
import time

import httpx

from interninbox import USER_AGENT
from interninbox.registry import REGISTRY

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


def main() -> int:
    failures = 0
    with httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT},
                      follow_redirects=True) as client:
        for entry in REGISTRY:
            url = ENDPOINTS[entry.ats].format(slug=entry.slug)
            try:
                response = client.get(url)
                ok = response.status_code == 200
            except httpx.HTTPError:
                ok = False
            status = "PASS" if ok else "FAIL"
            if not ok:
                failures += 1
            print(f"{status}  {entry.ats}:{entry.slug}  ({entry.name})")
            time.sleep(0.6)
    print(f"\n{len(REGISTRY) - failures}/{len(REGISTRY)} verified")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
