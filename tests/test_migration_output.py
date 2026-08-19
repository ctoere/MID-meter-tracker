"""The migration's output, pinned.

test_migration_mapping.py covers the rules one at a time. This covers what they
add up to over the real 384 rows, because the failure mode that matters is a
pattern tweak quietly reclassifying rows nobody looked at — and every one of
these numbers is a claim about whether a customer qualifies for the ERE.

If a change here is intended, update the numbers and say why in the commit
message. If it is not intended, this test just saved a compliance error.
"""

from collections import Counter

import pytest

from migrate.migrate_tracker import (SOURCE_MANIFEST, SOURCE_WORKBOOK,
                                     build_register, read_manifest, read_master_tracker)


@pytest.fixture(scope="module")
def migrated():
    if not SOURCE_WORKBOOK.exists():
        pytest.skip("seed tracker not present")
    records = read_master_tracker(SOURCE_WORKBOOK)
    register, report = build_register(records, read_manifest(SOURCE_MANIFEST))
    return register, report


def test_row_counts(migrated):
    register, _ = migrated
    assert len(register.chargers) == 380
    assert len(register.meters) == 4
    assert len(register.manifest) == 265
    assert len(register.conflicts) == 0


def test_status_distribution_is_unchanged(migrated):
    register, _ = migrated
    counts = Counter(r["MID Status"] for r in register.chargers + register.meters)
    assert dict(counts) == {
        "Integrated": 137,
        "Optional": 62,
        "External": 18,
        "None": 109,
        "Unknown": 58,
    }


def test_the_notes_override_the_seed_on_the_expected_number_of_rows(migrated):
    _, report = migrated
    assert len(report["overrides"]) == 66


def test_every_row_is_flagged_for_review(migrated):
    """The seed data was never manufacturer-verified; nothing is safe to quote."""
    register, _ = migrated
    assert all(r["Review Needed"] for r in register.chargers + register.meters)


def test_every_status_change_is_logged(migrated):
    register, _ = migrated
    assert len(register.change_log) == 384
    assert all(e["Field"] == "MID Status" and e["Reason"] for e in register.change_log)


def test_ids_are_unique_and_sequential(migrated):
    register, _ = migrated
    charger_ids = [r["ID"] for r in register.chargers]
    assert len(set(charger_ids)) == len(charger_ids)
    assert charger_ids[0] == "chg_0001" and charger_ids[-1] == "chg_0380"
    assert [r["ID"] for r in register.meters][-1] == "mtr_0004"


def test_the_rows_that_would_otherwise_be_wrongly_refused(migrated):
    """Seeded 'No', but in fact eligible. Getting these wrong refuses a paying customer.

    Spot-checked by hand against the source notes during the migration; pinned
    here so a pattern change cannot quietly send them back to None.
    """
    register, _ = migrated
    by_model = {f'{r["Brand"]} {r["Model"]}': r["MID Status"] for r in register.chargers}
    expected = {
        "Wallbox Pulsar Plus": "External",          # "No built-in MID; external accessory option"
        "Wallbox Pulsar Max": "External",
        "Wallbox Pulsar Pro": "External",
        "Schneider Electric EVlink Home": "External",
        "Hager witty share (base, no MID)": "Optional",         # "MID is an optional add-on kit"
        # The next two are Unknown rather than a guess, because the seed value and
        # the notes point in opposite directions:
        #   Zaptec Pro  — seed 'No', note says MID is a separate SKU, and also that
        #                 the base Pro has NO built-in MID. Not an option on THIS
        #                 SKU, so neither Optional nor a clean rejection.
        #   Cube Smart  — "Available with/without MID option" AND "Non-MID tier".
        "Zaptec Pro": "Unknown",
        "Cube Cube Smart (Standard Fast variant)": "Unknown",
    }
    for model, status in expected.items():
        assert by_model.get(model) == status, f"{model} migrated as {by_model.get(model)}"


def test_no_row_is_wrongly_rejected(migrated):
    """Nothing that a source called eligible may end up as None."""
    register, _ = migrated
    for row in register.chargers:
        if row["MID Status"] == "None":
            notes = row["Notes (EN)"]
            assert "Seed MID Status was 'No'" in notes, (
                f'{row["ID"]} became None without the seed data saying so')
