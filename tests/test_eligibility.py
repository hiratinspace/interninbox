"""Sponsorship classification, term derivation, HTML-to-text."""

import pytest

from interninbox.eligibility import (
    CITIZENSHIP_REQUIRED,
    NO_SPONSORSHIP,
    OFFERS_SPONSORSHIP,
    classify_sponsorship,
    classify_sponsorship_with_evidence,
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


# Requirement vs mention: a hedged or negated signal must never disqualify.

@pytest.mark.parametrize(
    "text",
    [
        "Security clearance preferred but not required.",
        "Ability to obtain a security clearance is a plus.",
        "A clearance is nice to have for this role.",
        "No security clearance required.",
        "No sponsorship required to apply.",
        "Visa sponsorship is not required for this position.",
    ],
)
def test_hedged_or_negated_signals_stay_unknown(text: str) -> None:
    assert classify_sponsorship(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "An active security clearance is required.",
        "Candidates must hold a TS/SCI security clearance.",
        "This position requires an active security clearance.",
        "This role is subject to ITAR and requires US person status.",
    ],
)
def test_genuine_clearance_requirements_still_classify(text: str) -> None:
    assert classify_sponsorship(text) == CITIZENSHIP_REQUIRED


def test_signals_are_scoped_to_their_sentence() -> None:
    # A hedge in one sentence must not soften a requirement in another.
    text = "Flexible hours preferred. U.S. citizenship is required."
    assert classify_sponsorship(text) == CITIZENSHIP_REQUIRED
    # And a requirement word elsewhere must not harden a hedged clearance.
    text = "A security clearance is a plus. A degree is required."
    assert classify_sponsorship(text) is None


def test_sponsorship_excluded_for_interns_is_negative() -> None:
    text = "Visa sponsorship is available for full-time roles but not for interns."
    assert classify_sponsorship(text) == NO_SPONSORSHIP


# Provenance: classify_sponsorship_with_evidence returns the classification
# plus the sentence that triggered it, so users can audit the verdict.


def test_evidence_is_the_triggering_sentence() -> None:
    text = "A great team. We are unable to sponsor visas for this role. Apply now!"
    assert classify_sponsorship_with_evidence(text) == (
        NO_SPONSORSHIP,
        "We are unable to sponsor visas for this role.",
    )


def test_evidence_for_citizenship_requirement() -> None:
    text = "Flexible hours preferred. This role requires US citizenship."
    assert classify_sponsorship_with_evidence(text) == (
        CITIZENSHIP_REQUIRED,
        "This role requires US citizenship.",
    )


def test_evidence_is_the_fragment_the_splitter_saw() -> None:
    # The sentence splitter refuses to split inside "U.S." (a single-letter
    # abbreviation), so the whole requirement sentence stays intact and the
    # evidence reports it in full.
    text = "Work on maps. U.S. citizenship is required for this position."
    assert classify_sponsorship_with_evidence(text) == (
        CITIZENSHIP_REQUIRED,
        "U.S. citizenship is required for this position.",
    )


def test_dotted_citizenship_phrase_spanning_the_abbreviation() -> None:
    # The most common phrasing puts "U.S." mid-pattern; a splitter that broke
    # at "S." would make this unmatchable.
    assert classify_sponsorship_with_evidence("Applicants must be a U.S. citizen.") == (
        CITIZENSHIP_REQUIRED,
        "Applicants must be a U.S. citizen.",
    )


def test_evidence_for_positive_signal() -> None:
    text = "Visa sponsorship is available for this role."
    assert classify_sponsorship_with_evidence(text) == (
        OFFERS_SPONSORSHIP,
        "Visa sponsorship is available for this role.",
    )


def test_no_evidence_when_unknown() -> None:
    assert classify_sponsorship_with_evidence("A friendly team.") == (None, None)
    assert classify_sponsorship_with_evidence("") == (None, None)


def test_evidence_follows_the_winning_signal() -> None:
    # Positive and restrictive signals in one text: the evidence must belong
    # to the restrictive sentence that decided the classification.
    both = "Visa sponsorship available for some roles; this role requires US citizenship."
    classification, evidence = classify_sponsorship_with_evidence(both)
    assert classification == CITIZENSHIP_REQUIRED
    assert evidence == "this role requires US citizenship."


def test_evidence_for_sponsorship_excluded_for_interns() -> None:
    text = "Great perks. Visa sponsorship is available for full-time roles but not for interns."
    assert classify_sponsorship_with_evidence(text) == (
        NO_SPONSORSHIP,
        "Visa sponsorship is available for full-time roles but not for interns.",
    )


def test_evidence_collapses_whitespace_and_trims_to_160_chars() -> None:
    filler = "for this role in every location we operate " * 5
    text = f"We are unable to  sponsor visas {filler}now."
    classification, evidence = classify_sponsorship_with_evidence(text)
    assert classification == NO_SPONSORSHIP
    assert evidence is not None
    assert len(evidence) == 160
    assert evidence.startswith("We are unable to sponsor visas for this role")
    assert "  " not in evidence


def test_classify_sponsorship_agrees_with_the_evidence_variant() -> None:
    texts = [
        "We cannot sponsor visas.",
        "Visa sponsorship is available for this role.",
        "U.S. citizenship is required.",
        "Nothing about eligibility here.",
    ]
    for text in texts:
        classification, _ = classify_sponsorship_with_evidence(text)
        assert classify_sponsorship(text) == classification
