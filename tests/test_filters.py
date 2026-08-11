"""Filtering rules: internship signal, staff exclusion, keywords, locations."""

import pytest
from conftest import make_listing

from interninbox.config import Filters
from interninbox.filters import has_internship_signal, is_staff_role, matches


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineering Intern",
        "INTERNSHIP - Data Platform",
        "Hardware Co-op (Spring)",
        "Engineering Coop Student",
        "Investment Banking Summer Analyst",
        "Summer Associate, Strategy",
        "Machinist Apprentice",
        "Student Trainee (Information Technology)",
        "Pathways Intern - Data Analysis",
        "Working Student, QA",
    ],
)
def test_internship_signal_positives(title: str) -> None:
    assert has_internship_signal(title)


@pytest.mark.parametrize(
    "title",
    [
        "International Program Manager",  # \bintern\b must not match inside words
        "Internal Tools Engineer",
        "Operations Associate, Cooper",  # "coop" inside "Cooper"
        "Software Engineer",
        "Interniship",  # typo — no boundary match
    ],
)
def test_internship_signal_negatives(title: str) -> None:
    assert not has_internship_signal(title)


def test_include_keywords_extend_the_signal() -> None:
    assert not has_internship_signal("Software Engineer, Early Career")
    assert has_internship_signal("Software Engineer, Early Career", ("early career",))


@pytest.mark.parametrize(
    "title",
    [
        "Internship Program Manager",
        "University Recruiter, Intern Programs",
        "Senior Software Engineer, Intern Tools",
        "Staff Engineer",
        "Director of Intern Experience",
        "Software Engineer II",
    ],
)
def test_staff_role_exclusion(title: str) -> None:
    assert is_staff_role(title)


def test_lowercase_ii_is_not_a_level_marker() -> None:
    assert not is_staff_role("Data Intern (wii games team)")


def test_matches_requires_signal_and_no_staff_role() -> None:
    filters = Filters()
    assert matches(make_listing(title="Software Engineering Intern"), filters)
    assert not matches(make_listing(title="Software Engineer"), filters)
    assert not matches(make_listing(title="Internship Program Manager"), filters)


def test_exclude_keywords_drop_matches() -> None:
    filters = Filters(exclude_keywords=("mechanical",))
    assert not matches(make_listing(title="Mechanical Engineering Intern"), filters)
    assert matches(make_listing(title="Software Engineering Intern"), filters)


def test_locations_substring_match_case_insensitive() -> None:
    filters = Filters(locations=("new york",))
    assert matches(make_listing(locations=("New York, NY",)), filters)
    assert not matches(make_listing(locations=("Austin, TX",)), filters)


def test_no_location_listing_passes_only_without_location_filter() -> None:
    assert matches(make_listing(locations=()), Filters())
    assert not matches(make_listing(locations=()), Filters(locations=("Austin",)))


def test_remote_ok_true_passes_location_filter() -> None:
    filters = Filters(locations=("Austin",), remote_ok=True)
    assert matches(make_listing(locations=("Remote",)), filters)


def test_remote_ok_false_drops_remote_only() -> None:
    filters = Filters(remote_ok=False)
    assert not matches(make_listing(locations=("Remote",)), filters)
    # A listing with a physical location alongside remote survives.
    assert matches(make_listing(locations=("New York, NY", "Remote")), filters)
