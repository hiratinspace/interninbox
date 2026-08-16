"""website: adapter tests, sitemap walking plus JSON-LD pages, all offline."""

import json
from pathlib import Path

import httpx
import pytest
from conftest import make_transport

from interninbox.adapters import ADAPTERS, website
from interninbox.config import KNOWN_ATS
from interninbox.models import AdapterError

DOMAIN = "careers.example-co.test"
BASE = f"https://{DOMAIN}"

ROBOTS = f"""User-agent: *
Disallow: /private/
Sitemap: {BASE}/sitemap-index.xml
"""

SITEMAP_INDEX = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>{BASE}/job-sitemap.xml</loc></sitemap>
  <sitemap><loc>{BASE}/pages-sitemap.xml</loc></sitemap>
</sitemapindex>
"""


def _urlset(*entries: tuple[str, str | None]) -> str:
    rows = "".join(
        f"<url><loc>{loc}</loc>" + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "") + "</url>"
        for loc, lastmod in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>'
    )


# The sitemap filename says "job", so ALL its URLs are candidates, including
# the /private/ one (which robots.txt then blocks, with an honest warning).
JOB_SITEMAP = _urlset(
    (f"{BASE}/roles/1234-pipeline-intern", "2026-08-01"),
    (f"{BASE}/private/roles/9999-hidden", None),
)
# A generic sitemap: only job-looking paths are candidates.
PAGES_SITEMAP = _urlset(
    (f"{BASE}/about", None),
    (f"{BASE}/careers/opening-42", "2026-07-15"),
)

POSTING = {
    "@context": "https://schema.org/",
    "@type": "JobPosting",
    "title": "Pipeline Engineering Intern (Summer 2027)",
    "datePosted": "2026-08-01",
    "employmentType": "INTERN",
    "description": "<p>Build pipelines. We are unable to sponsor visas for this role.</p>",
    "jobLocation": [
        {
            "@type": "Place",
            "address": {"addressLocality": "State College", "addressRegion": "PA"},
        }
    ],
}

JOB_PAGE = (
    "<html><head>"
    f'<script type="application/ld+json">{json.dumps(POSTING)}</script>'
    "</head><body>rendered page</body></html>"
)
SHELL_PAGE = "<html><body><div id='app'>client-side shell, no structured data</div></body></html>"


def _routes() -> dict[str, str]:
    return {
        "/robots.txt": ROBOTS,
        "/sitemap-index.xml": SITEMAP_INDEX,
        "/job-sitemap.xml": JOB_SITEMAP,
        "/pages-sitemap.xml": PAGES_SITEMAP,
        "/roles/1234-pipeline-intern": JOB_PAGE,
        "/careers/opening-42": SHELL_PAGE,
    }


def _handler(routes: dict[str, str], log: list[str] | None = None):
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if log is not None:
            log.append(path)
        body = routes.get(path)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, text=body)

    return handle


@pytest.fixture
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    return tmp_path / "cache" / "interninbox" / "website" / f"{DOMAIN}.json"


# ---- iter_job_urls (the sitemap walker) ----


def test_walker_discovers_job_urls_and_counts_robots_skips(instant_fetcher) -> None:
    warnings: list[str] = []
    with instant_fetcher(make_transport(_handler(_routes()))) as fetcher:
        found = website.iter_job_urls(fetcher, DOMAIN, warnings.append)
    assert found == [
        (f"{BASE}/roles/1234-pipeline-intern", "2026-08-01"),
        (f"{BASE}/careers/opening-42", "2026-07-15"),
    ]
    # The /private/ candidate was skipped because robots.txt disallows it.
    assert any("robots" in warning and "1" in warning for warning in warnings)


def test_walker_missing_robots_falls_back_to_default_sitemap(instant_fetcher) -> None:
    routes = {
        "/sitemap.xml": _urlset((f"{BASE}/jobs/velvet-otter-intern", None)),
        "/jobs/velvet-otter-intern": JOB_PAGE,
    }
    warnings: list[str] = []
    with instant_fetcher(make_transport(_handler(routes))) as fetcher:
        found = website.iter_job_urls(fetcher, DOMAIN, warnings.append)
    assert found == [(f"{BASE}/jobs/velvet-otter-intern", None)]


def test_walker_refuses_a_site_whose_robots_cannot_be_read(instant_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with instant_fetcher(make_transport(handler)) as fetcher:
        with pytest.raises(AdapterError, match="robots"):
            website.iter_job_urls(fetcher, DOMAIN, lambda message: None)


def test_walker_no_sitemap_anywhere_warns_and_returns_nothing(instant_fetcher) -> None:
    routes = {"/robots.txt": "User-agent: *\nDisallow: /admin/\n"}
    warnings: list[str] = []
    with instant_fetcher(make_transport(_handler(routes))) as fetcher:
        found = website.iter_job_urls(fetcher, DOMAIN, warnings.append)
    assert found == []
    assert any("sitemap" in warning.lower() for warning in warnings)


def test_walker_child_sitemap_cap_truncates_honestly(
    instant_fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The cap counts every sitemap fetch (robots-listed entry points AND
    # index children), so 2 = the index itself plus its first child.
    monkeypatch.setattr(website, "MAX_CHILD_SITEMAPS", 2)
    warnings: list[str] = []
    with instant_fetcher(make_transport(_handler(_routes()))) as fetcher:
        found = website.iter_job_urls(fetcher, DOMAIN, warnings.append)
    # Only the first child sitemap was read; the truncation is announced.
    assert found == [(f"{BASE}/roles/1234-pipeline-intern", "2026-08-01")]
    assert any("sitemap" in warning and "truncat" in warning for warning in warnings)


def test_walker_ignores_indexes_nested_too_deep(instant_fetcher) -> None:
    index_at = "<?xml version=\"1.0\"?><sitemapindex " \
        'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' \
        "<sitemap><loc>{child}</loc></sitemap></sitemapindex>"
    routes = {
        "/robots.txt": f"User-agent: *\nSitemap: {BASE}/level0.xml\n",
        "/level0.xml": index_at.format(child=f"{BASE}/level1.xml"),
        "/level1.xml": index_at.format(child=f"{BASE}/level2.xml"),
        # Depth 2 is the floor: an index here is not recursed into.
        "/level2.xml": index_at.format(child=f"{BASE}/level3.xml"),
        "/level3.xml": _urlset((f"{BASE}/jobs/too-deep", None)),
    }
    warnings: list[str] = []
    with instant_fetcher(make_transport(_handler(routes))) as fetcher:
        found = website.iter_job_urls(fetcher, DOMAIN, warnings.append)
    assert found == []


# ---- fetch (adapter wiring plus the incremental cache) ----


def test_fetch_end_to_end_maps_pages_to_listings(instant_fetcher, isolated_cache: Path) -> None:
    log: list[str] = []
    warnings: list[str] = []
    with instant_fetcher(make_transport(_handler(_routes(), log))) as fetcher:
        listings = website.fetch(fetcher, DOMAIN, warn=warnings.append)
    assert len(listings) == 1
    listing = listings[0]
    assert listing.source == "website"
    assert listing.company == DOMAIN
    assert listing.title == "Pipeline Engineering Intern (Summer 2027)"
    assert listing.url == f"{BASE}/roles/1234-pipeline-intern"
    assert listing.locations == ("State College, PA",)
    assert listing.employment_intern is True
    assert listing.sponsorship == "no-sponsorship"
    # Politeness: robots first, then sitemaps, then only allowed job pages.
    assert log == [
        "/robots.txt",
        "/sitemap-index.xml",
        "/job-sitemap.xml",
        "/pages-sitemap.xml",
        "/roles/1234-pipeline-intern",
        "/careers/opening-42",
    ]
    assert isolated_cache.is_file()


def test_fetch_reuses_the_cache_until_lastmod_changes(
    instant_fetcher, isolated_cache: Path
) -> None:
    routes = _routes()
    first_log: list[str] = []
    with instant_fetcher(make_transport(_handler(routes, first_log))) as fetcher:
        first = website.fetch(fetcher, DOMAIN)
    assert len(first) == 1

    # Second scan, nothing changed: sitemaps are re-read, pages are not.
    second_log: list[str] = []
    with instant_fetcher(make_transport(_handler(routes, second_log))) as fetcher:
        second = website.fetch(fetcher, DOMAIN)
    assert [listing.title for listing in second] == [listing.title for listing in first]
    assert second[0].key == first[0].key
    assert "/roles/1234-pipeline-intern" not in second_log
    assert "/careers/opening-42" not in second_log

    # The job page's lastmod moves: exactly that page is refetched.
    routes["/job-sitemap.xml"] = _urlset(
        (f"{BASE}/roles/1234-pipeline-intern", "2026-08-09"),
        (f"{BASE}/private/roles/9999-hidden", None),
    )
    third_log: list[str] = []
    with instant_fetcher(make_transport(_handler(routes, third_log))) as fetcher:
        third = website.fetch(fetcher, DOMAIN)
    assert len(third) == 1
    assert third_log.count("/roles/1234-pipeline-intern") == 1
    assert "/careers/opening-42" not in third_log


def test_fetch_survives_a_corrupt_cache(instant_fetcher, isolated_cache: Path) -> None:
    isolated_cache.parent.mkdir(parents=True, exist_ok=True)
    isolated_cache.write_text("{not json", encoding="utf-8")
    with instant_fetcher(make_transport(_handler(_routes()))) as fetcher:
        listings = website.fetch(fetcher, DOMAIN)
    assert len(listings) == 1
    # The corrupt cache was replaced by a fresh one.
    assert json.loads(isolated_cache.read_text(encoding="utf-8"))


def test_fetch_page_cap_truncates_with_a_warning(
    instant_fetcher, isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(website, "WEBSITE_PAGE_CAP", 1)
    log: list[str] = []
    warnings: list[str] = []
    with instant_fetcher(make_transport(_handler(_routes(), log))) as fetcher:
        listings = website.fetch(fetcher, DOMAIN, warn=warnings.append)
    assert len(listings) == 1  # the first candidate was the job page
    assert "/careers/opening-42" not in log
    assert any("cap" in warning for warning in warnings)


def test_fetch_counts_broken_pages_without_aborting(
    instant_fetcher, isolated_cache: Path
) -> None:
    routes = _routes()
    del routes["/careers/opening-42"]  # that page now answers 404
    warnings: list[str] = []
    with instant_fetcher(make_transport(_handler(routes))) as fetcher:
        listings = website.fetch(fetcher, DOMAIN, warn=warnings.append)
    assert len(listings) == 1
    assert any("failed" in warning for warning in warnings)


def test_registered_as_a_known_ats() -> None:
    assert "website" in KNOWN_ATS
    assert ADAPTERS["website"] is website.fetch


def test_robots_listed_sitemaps_count_against_the_cap(instant_fetcher) -> None:
    import httpx
    from conftest import make_transport

    from interninbox.adapters import website

    robots = "User-agent: *\nAllow: /\n" + "\n".join(
        f"Sitemap: https://caps.test/map{i}.xml" for i in range(50)
    )
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        return httpx.Response(
            200,
            text='<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://caps.test/jobs/x</loc></url></urlset>',
        )

    warnings: list[str] = []
    with instant_fetcher(make_transport(handler)) as fetcher:
        website.iter_job_urls(fetcher, "caps.test", warnings.append)
    sitemap_fetches = [u for u in fetched if u.endswith(".xml")]
    assert len(sitemap_fetches) <= website.MAX_CHILD_SITEMAPS
    assert any("sitemap" in w.lower() for w in warnings)  # honest truncation


def test_offsite_sitemap_urls_are_skipped(instant_fetcher) -> None:
    import httpx
    from conftest import make_transport

    from interninbox.adapters import website

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        assert host != "evil.test", "scanner must never fetch out-of-scope hosts"
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\nSitemap: https://scope.test/sitemap.xml")
        if path == "/sitemap.xml":
            return httpx.Response(
                200,
                text='<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<url><loc>https://evil.test/jobs/steal</loc></url>"
                "<url><loc>https://careers.scope.test/jobs/ok</loc></url>"
                "<url><loc>https://scope.test/jobs/fine</loc></url></urlset>",
            )
        return httpx.Response(200, text="<html></html>")

    with instant_fetcher(make_transport(handler)) as fetcher:
        urls = [u for u, _ in website.iter_job_urls(fetcher, "scope.test", lambda _m: None)]
    assert "https://evil.test/jobs/steal" not in urls
    assert "https://careers.scope.test/jobs/ok" in urls  # subdomains are in scope
    assert "https://scope.test/jobs/fine" in urls
