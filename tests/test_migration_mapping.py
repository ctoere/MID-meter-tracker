"""The seed-vocabulary mapping. Every case here is a real row from the tracker."""

import pytest

from migrate.mapping import map_status


def test_plain_seed_values_map_across():
    assert map_status("Yes").status == "Integrated"
    assert map_status("No").status == "None"
    assert map_status("Maybe").status == "Optional"
    assert map_status("Unknown").status == "Unknown"
    assert map_status("N/A").status == "Unknown"


def test_blank_seed_is_unknown_never_none():
    assert map_status("").status == "Unknown"
    assert map_status(None).status == "Unknown"


@pytest.mark.parametrize("seed,note,expected", [
    # The rows that matter most: seeded "No" but in fact eligible. Reading these
    # literally tells a paying customer they cannot book their kWh into the REV.
    ("No", "No built-in MID; external accessory option", "External"),
    ("No", "No built-in MID meter; supports an EXTERNAL MID-certified meter via TIC/pulse input", "External"),
    ("No", "Base SKU XEV1R22T2 has NO integrated MID meter -- MID is an optional add-on kit.", "Optional"),
    ("No", "MID as option (Class B)", "Optional"),
    ("No", "Available with/without MID option", "Optional"),
])
def test_notes_rescue_wrongly_rejected_rows(seed, note, expected):
    assert map_status(seed, note).status == expected


@pytest.mark.parametrize("note", [
    "No MID in any variant",
    "No built-in MID meter | no meter option at all (not just 'no MID' - no metering hardware whatsoever)",
    "No MID variant at 7kW -- MID only on the 11kW 3-phase unit.",
])
def test_negated_optionality_is_not_an_option(note):
    """'No MID in any variant' is a rejection, not an option."""
    assert map_status("No", note).status == "None"


def test_a_utility_meter_is_not_an_external_mid_meter():
    note = ("Confirmed NOT itself an MID-certified charger meter - Sense reads consumption "
            "from the site's EXISTING external utility/smart meter to throttle charger output")
    assert map_status("No", note).status == "None"


def test_product_line_variants_do_not_imply_a_mid_option():
    """'wall-mounted variant' is product-line language and says nothing about metering."""
    note = ("Integrated MID meter | SPLIT from combined seed row -- wall-mounted variant of "
            "Business Solo/Duo. MID confirmed via 2023 spec PDF")
    assert map_status("Yes", note).status == "Integrated"


def test_disagreement_between_seed_and_notes_becomes_unknown():
    """Not a guess in either direction — the disagreement stays visible."""
    result = map_status("No", "Available with/without MID option | Non-MID tier per third-party brochure.")
    assert result.status == "Unknown"
    assert "not established" in result.rule


def test_eichrecht_alone_is_not_mid_evidence():
    """German calibration law is a related but separate regime from 2014/32/EU."""
    result = map_status("Yes", "Public specs say 'eichrechtskonform' per the manufacturer page")
    assert result.status == "Unknown"
    assert result.eichrecht
    assert "separate regime" in result.rule


def test_eichrecht_alongside_a_real_mid_claim_is_kept():
    result = map_status("Yes", "MID-certified meter fitted; optional Eichrecht module B/D available")
    assert result.status in {"Integrated", "Optional"}
    assert result.eichrecht  # recorded separately, not treated as the MID evidence


def test_no_note_can_invent_a_rejection():
    """Nothing in the mapper may turn a non-'No' seed into None."""
    notes = ["no MID anywhere", "not MID-certified", "external accessory option",
             "MID option", "eichrecht only", "", "CE marked"]
    for seed in ("Yes", "Maybe", "Unknown", "N/A", ""):
        for note in notes:
            assert map_status(seed, note).status != "None", (seed, note)


def test_every_result_carries_a_reason():
    """The Change Log entry has to say why, or an audit cannot follow it."""
    for seed in ("Yes", "No", "Maybe", "Unknown", "N/A", ""):
        assert map_status(seed, "some note").rule.strip()
