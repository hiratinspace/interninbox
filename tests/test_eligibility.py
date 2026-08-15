"""Sponsorship classification, term derivation, HTML-to-text."""

import pytest

from interninbox.eligibility import (
    CITIZENSHIP_REQUIRED,
    NO_SPONSORSHIP,
    OFFERS_SPONSORSHIP,
    classify_sponsorship,
    derive_terms,
    text_from_html,
)


@pytest.mark.parametrize(
    "text",
    [
        "We are unable to sponsor visas for this role.",
        "Applicants must not require visa sponsorship now or in the future.",
        "This position does not offer sponsorship.",
        "We cannot sponsor or take over sponsorship of an employment visa.",
        "No visa sponsorship is available for this position.",
        "We will not sponsor applicants for work visas.",
    ],
)
def test_negative_sponsorship_phrases(text: str) -> None:
    assert classify_sponsorship(text) == NO_SPONSORSHIP


@pytest.mark.parametrize(
    "text",
    [
        "U.S. citizenship is required for this position.",
        "Applicants must be a US citizen due to contract requirements.",
        "An active security clearance is required.",
        "This role is subject to ITAR restrictions.",
    ],
)
def test_citizenship_phrases(text: str) -> None:
    assert classify_sponsorship(text) == CITIZENSHIP_REQUIRED


@pytest.mark.parametrize(
    "text",
    [
        "Visa sponsorship is available for this role.",
        "We are able to sponsor work visas.",
        "We will sponsor H-1B for qualified candidates.",
    ],
)
def test_positive_sponsorship_phrases(text: str) -> None:
    assert classify_sponsorship(text) == OFFERS_SPONSORSHIP


def test_silence_is_unknown() -> None:
    assert classify_sponsorship("A great internship on a friendly team.") is None
    assert classify_sponsorship("") is None


def test_restrictive_signal_wins_over_positive() -> None:
    # If a posting says both, the restrictive read is the safe one.
    both = "Visa sponsorship available for some roles; this role requires US citizenship."
    assert classify_sponsorship(both) == CITIZENSHIP_REQUIRED


def test_derive_terms_from_titles() -> None:
    assert derive_terms("Software Engineering Intern (Summer 2027)") == ("Summer 2027",)
    assert derive_terms("Fall 2026 Data Intern") == ("Fall 2026",)
    assert derive_terms("SUMMER 2027 intern") == ("Summer 2027",)  # normalized
    assert derive_terms("Software Engineering Intern") == ()


def test_text_from_html_plain_and_escaped() -> None:
    raw = "<h2>About</h2><p>We are <strong>unable to sponsor</strong> visas.</p>"
    assert "unable to sponsor" in text_from_html(raw)
    assert "<" not in text_from_html(raw)
    escaped = "&lt;p&gt;U.S. citizenship is required.&lt;/p&gt;"
    assert "citizenship is required" in text_from_html(escaped, escaped=True)
    # entities inside text decode either way
    assert "R&D" in text_from_html("<p>R&amp;D intern</p>")
