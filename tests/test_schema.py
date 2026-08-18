"""The five-value vocabulary is a compliance contract, not a UI convention."""

import pytest

from app import schema


def test_exactly_five_statuses():
    assert schema.MID_STATUSES == ("Integrated", "Optional", "External", "None", "Unknown")


@pytest.mark.parametrize("value", ["Yes", "No", "Maybe", "N/A", "integrated", "INTEGRATED",
                                   "Not eligible", "MID", "Partial", "TBD", 0, 1, True])
def test_rejects_anything_outside_the_vocabulary(value):
    with pytest.raises(schema.StatusVocabularyError):
        schema.validate_status(value)


@pytest.mark.parametrize("value", schema.MID_STATUSES)
def test_accepts_every_valid_status(value):
    assert schema.validate_status(value) == value


@pytest.mark.parametrize("value", ["", "   ", None])
def test_absence_of_evidence_is_unknown_not_none(value):
    # Defaulting a blank to "None" would assert that a charger has no MID meter
    # on the strength of nobody having looked yet.
    assert schema.validate_status(value) == "Unknown"


def test_optional_and_external_are_eligible():
    # The most expensive error this tool can make is reading either as a refusal.
    assert schema.is_eligible("Optional")
    assert schema.is_eligible("External")
    assert schema.is_eligible("Integrated")
    assert not schema.is_eligible("None")
    assert not schema.is_eligible("Unknown")


def test_every_status_has_a_stated_consequence():
    # The UI must never show a colour without words beside it.
    assert set(schema.ELIGIBILITY_TEXT) == set(schema.MID_STATUSES)
    assert all(schema.ELIGIBILITY_TEXT[s] for s in schema.MID_STATUSES)
