"""JSON-LD JobPosting extraction and mapping tests (synthetic HTML only)."""

import datetime as dt
import json

from interninbox.config import Filters
from interninbox.filters import matches
from interninbox.jsonld import extract_job_postings, normalize_page_url, posting_to_listing

DOMAIN = "careers.example-co.test"
# Mixed-case host and a tracking query: normalization must strip both.
PAGE_URL = "https://Careers.Example-Co.test/roles/1234-pipeline-intern?src=sitemap"


def _page(*payloads: object) -> str:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps(payload)}</script>'
        for payload in payloads
    )
    return f"<html><head>{blocks}</head><body>app shell</body></html>"


def _posting(**overrides: object) -> dict:
    data: dict = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": "Pipeline Engineering Intern (Summer 2027)",
        "datePosted": "2026-08-01",
        "employmentType": "FULL_TIME",
        "description": "<p>Build pipelines. We are unable to sponsor visas for this role.</p>",
        "jobLocation": [
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "State College",
                    "addressRegion": "PA",
                    "addressCountry": "US",
                },
            }
        ],
    }
    data.update(overrides)
    return data


# ---- extract_job_postings ----


def test_extract_single_top_level_object() -> None:
    found = extract_job_postings(_page(_posting()))
    assert len(found) == 1
    assert found[0]["title"] == "Pipeline Engineering Intern (Summer 2027)"


def test_extract_tolerates_extra_script_attributes() -> None:
    body = json.dumps(_posting())
    html = f"<script data-page='1' type='application/ld+json' async>{body}</script>"
    assert len(extract_job_postings(html)) == 1


def test_extract_from_graph_wrapper() -> None:
    page = _page(
        {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "Organization", "name": "Example Co"},
                {"@type": "JobPosting", "title": "Data Intern"},
            ],
        }
    )
    assert [posting["title"] for posting in extract_job_postings(page)] == ["Data Intern"]


def test_extract_from_array_and_type_lists() -> None:
    page = _page(
        [
            {"@type": ["JobPosting", "Thing"], "title": "Robotics Intern"},
            {"@type": "WebPage", "name": "About"},
        ]
    )
    assert [posting["title"] for posting in extract_job_postings(page)] == ["Robotics Intern"]


def test_malformed_block_never_hides_a_valid_one() -> None:
    html = '<script type="application/ld+json">{not json at all</script>' + _page(
        {"@type": "JobPosting", "title": "Survivor Intern"}
    )
    assert [posting["title"] for posting in extract_job_postings(html)] == ["Survivor Intern"]


def test_plain_scripts_and_other_types_are_ignored() -> None:
    html = "<script>var data = {\"@type\": \"JobPosting\"};</script>"
    assert extract_job_postings(html) == []
    assert extract_job_postings(_page({"@type": "Organization", "name": "X"})) == []


def test_hostile_deep_array_never_crashes_or_hides_a_valid_block() -> None:
    # A ~3KB pathological payload: nesting deeper than the interpreter
    # recursion limit but shallow enough that json.loads still parses it.
    # Flattening must not raise RecursionError, and the valid block on the
    # same page must survive (a hostile site aborts nothing).
    depth = 1500
    hostile = "[" * depth + "]" * depth
    html = (
        f'<script type="application/ld+json">{hostile}</script>'
        + _page({"@type": "JobPosting", "title": "Survivor Intern"})
    )
    assert [posting["title"] for posting in extract_job_postings(html)] == ["Survivor Intern"]


def test_posting_inside_a_deeply_nested_array_is_still_found() -> None:
    depth = 1500
    body = "[" * depth + json.dumps({"@type": "JobPosting", "title": "Deep Intern"})
    body += "]" * depth
    html = f'<script type="application/ld+json">{body}</script>'
    assert [posting["title"] for posting in extract_job_postings(html)] == ["Deep Intern"]


# ---- posting_to_listing ----


def test_full_mapping() -> None:
    listing = posting_to_listing(_posting(), PAGE_URL, DOMAIN)
    assert listing is not None
    assert listing.source == "website"
    assert listing.company == DOMAIN
    assert listing.title == "Pipeline Engineering Intern (Summer 2027)"
    assert listing.url == PAGE_URL
    assert listing.locations == ("State College, PA, US",)
    assert listing.posted_at == dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    assert listing.terms == ("Summer 2027",)
    assert listing.sponsorship == "no-sponsorship"
    assert listing.sponsorship_evidence is not None
    assert "unable to sponsor" in listing.sponsorship_evidence
    assert listing.employment_intern is False
    # Identity: host lowercased, query dropped, so reruns and dedup agree.
    assert listing.key == "website:https://careers.example-co.test/roles/1234-pipeline-intern"


def test_expired_valid_through_drops_the_listing() -> None:
    assert posting_to_listing(_posting(validThrough="2020-01-01"), PAGE_URL, DOMAIN) is None
    kept = posting_to_listing(_posting(validThrough="2100-01-01T00:00:00Z"), PAGE_URL, DOMAIN)
    assert kept is not None
    # An unparseable validThrough never drops a listing (unknown keeps).
    assert posting_to_listing(_posting(validThrough="whenever"), PAGE_URL, DOMAIN) is not None


def test_telecommute_adds_remote() -> None:
    listing = posting_to_listing(
        _posting(jobLocationType="TELECOMMUTE", jobLocation=None), PAGE_URL, DOMAIN
    )
    assert listing is not None
    assert listing.locations == ("Remote",)


def test_job_location_object_and_country_dict() -> None:
    listing = posting_to_listing(
        _posting(
            jobLocation={
                "@type": "Place",
                "address": {
                    "addressLocality": "London",
                    "addressCountry": {"@type": "Country", "name": "UK"},
                },
            }
        ),
        PAGE_URL,
        DOMAIN,
    )
    assert listing is not None
    assert listing.locations == ("London, UK",)


def test_missing_title_returns_none() -> None:
    assert posting_to_listing({"@type": "JobPosting"}, PAGE_URL, DOMAIN) is None
    assert posting_to_listing(_posting(title=""), PAGE_URL, DOMAIN) is None


def test_missing_optional_fields_survive() -> None:
    listing = posting_to_listing({"@type": "JobPosting", "title": "Lab Intern"}, PAGE_URL, DOMAIN)
    assert listing is not None
    assert listing.locations == ()
    assert listing.posted_at is None
    assert listing.sponsorship is None
    assert listing.sponsorship_evidence is None


def test_unparseable_date_posted_left_unset() -> None:
    listing = posting_to_listing(_posting(datePosted="soon"), PAGE_URL, DOMAIN)
    assert listing is not None
    assert listing.posted_at is None


def test_employment_type_intern_feeds_the_intern_signal() -> None:
    # No intern word in the title: only the source's own declaration keeps it.
    listing = posting_to_listing(
        _posting(title="Early Careers Programme", employmentType="INTERN"), PAGE_URL, DOMAIN
    )
    assert listing is not None
    assert listing.employment_intern is True
    assert matches(listing, Filters()) is True

    as_list = posting_to_listing(
        _posting(title="Early Careers Programme", employmentType=["FULL_TIME", "INTERNSHIP"]),
        PAGE_URL,
        DOMAIN,
    )
    assert as_list is not None
    assert as_list.employment_intern is True


def test_staff_role_exclusion_still_applies() -> None:
    listing = posting_to_listing(
        _posting(title="Internship Program Manager", employmentType="INTERN"), PAGE_URL, DOMAIN
    )
    assert listing is not None
    assert matches(listing, Filters()) is False


def test_page_identity_keeps_meaningful_query_params() -> None:
    # Two jobs on the same path distinguished only by query must not collide.
    a = normalize_page_url("https://ex.com/careers?id=1&utm_source=x")
    b = normalize_page_url("https://ex.com/careers?id=2")
    assert a != b
    # Tracking params never change identity; param order never changes identity.
    assert normalize_page_url("https://ex.com/careers?b=2&a=1&utm_campaign=z") == \
        normalize_page_url("https://EX.com/careers?a=1&b=2")
