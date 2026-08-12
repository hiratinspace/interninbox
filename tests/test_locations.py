"""US-state / country alias expansion for location filters."""

from conftest import make_listing

from interninbox.config import Filters
from interninbox.filters import matches
from interninbox.locations import expand_location_terms


def test_state_abbreviation_gains_full_name() -> None:
    expanded = expand_location_terms(("CA",))
    assert "California" in expanded
    assert expanded[0] == "CA"  # original term kept, first


def test_common_aliases() -> None:
    assert "New York" in expand_location_terms(("NYC",))
    assert "United Kingdom" in expand_location_terms(("UK",))
    assert "United States" in expand_location_terms(("USA",))


def test_unknown_terms_pass_through_unchanged() -> None:
    assert expand_location_terms(("Germany",)) == ("Germany",)


def test_no_duplicates_and_order_preserved() -> None:
    expanded = expand_location_terms(("CA", "California", "Berlin"))
    assert expanded[0] == "CA"
    assert len([t for t in expanded if t.lower() == "california"]) == 1
    assert expanded[-1] == "Berlin"


def test_empty_input_is_empty() -> None:
    assert expand_location_terms(()) == ()


# Behavioral contracts through the real matcher, these are the tests that
# would catch an unsafe expansion, so do not weaken them.

def test_full_state_name_matches_abbreviated_board_location() -> None:
    filters = Filters(locations=expand_location_terms(("California",)))
    assert matches(make_listing(locations=("San Francisco, CA",)), filters)


def test_abbreviation_matches_full_name_board_location() -> None:
    filters = Filters(locations=expand_location_terms(("CA",)))
    assert matches(make_listing(locations=("Sacramento, California",)), filters)


def test_state_expansion_never_matches_english_words() -> None:
    # "Oregon" -> ", OR" (comma-anchored), NOT the bare word "or".
    filters = Filters(locations=expand_location_terms(("Oregon",)))
    assert not matches(make_listing(locations=("in USA or Canada",)), filters)
    assert matches(make_listing(locations=("Portland, OR",)), filters)


def test_indiana_does_not_match_the_word_in() -> None:
    filters = Filters(locations=expand_location_terms(("Indiana",)))
    assert not matches(make_listing(locations=("in Germany",)), filters)
    assert matches(make_listing(locations=("Indianapolis, IN",)), filters)


def test_country_alias_us_never_matches_the_pronoun() -> None:
    # "United States"/"USA"/"US" must not inject a bare "US" that whole-word
    # matches the pronoun "us", same English-word hazard as the state codes.
    for term in ("United States", "USA", "US"):
        filters = Filters(locations=expand_location_terms((term,)))
        assert not matches(make_listing(locations=("Come build with us",)), filters), term
        assert matches(make_listing(locations=("New York, US",)), filters), term
