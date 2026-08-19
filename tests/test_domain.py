"""Domain helpers — including two bugs found by the Phase 2 tests."""

from app import domain


def test_append_note_keeps_earlier_text():
    assert domain.append_note("first quote", "second quote") == "first quote\n\nsecond quote"
    assert domain.append_note("", "only") == "only"
    assert domain.append_note("existing", "") == "existing"


def test_append_note_does_not_repeat_an_identical_paragraph():
    note = "first quote\n\nsecond quote"
    assert domain.append_note(note, "second quote") == note


def test_append_note_keeps_a_short_note_that_appears_inside_existing_text():
    """Regression: the duplicate check used to be a substring test.

    Appending "one" to a note containing "...variants in one document..." was
    silently discarded. Losing a colleague's note without telling them is worse
    than storing something twice — these notes are evidence.
    """
    existing = "Covers both variants in one document ('MID in alcune varianti')."
    result = domain.append_note(existing, "one")
    assert result.endswith("\n\none")
    assert existing in result


def test_next_id_takes_the_high_water_mark():
    rows = [{"ID": "chg_0001"}, {"ID": "chg_0007"}, {"ID": "chg_0003"}]
    assert domain.next_id(rows, "chg") == "chg_0008"


def test_next_id_ignores_other_prefixes():
    assert domain.next_id([{"ID": "mtr_0009"}, {"ID": "chg_0002"}], "chg") == "chg_0003"


def test_next_id_never_reissues_a_deleted_rows_id():
    """Regression: deleting the highest-numbered row freed its ID for reuse.

    max+1 over live rows alone is not enough — the Change Log is append-only and
    remembers every ID ever issued, so it supplies the real high water mark.
    """
    live = [{"ID": "chg_0001"}, {"ID": "chg_0002"}]          # chg_0003 was deleted
    change_log_ids = ["chg_0001", "chg_0002", "chg_0003"]
    assert domain.next_id(live, "chg", issued=change_log_ids) == "chg_0004"


def test_next_id_starts_at_one_on_an_empty_sheet():
    assert domain.next_id([], "mtr") == "mtr_0001"


def test_summarise_never_groups_optional_or_external_with_none():
    rows = [{"MID Status": s} for s in
            ["Integrated", "Optional", "External", "None", "Unknown", "Optional"]]
    stats = domain.summarise(rows)
    assert stats["eligible_as_sold"] == 1
    assert stats["eligible_check_unit"] == 3      # 2 Optional + 1 External
    assert stats["not_eligible"] == 1             # None only
    assert stats["unknown"] == 1


def test_summarise_treats_a_blank_status_as_unknown():
    assert domain.summarise([{"MID Status": ""}])["unknown"] == 1
    assert domain.summarise([{"MID Status": ""}])["not_eligible"] == 0


def test_charge_type_folder_defaults_to_ac():
    assert domain.charge_type_folder("DC") == "DC"
    assert domain.charge_type_folder("dc fast") == "DC"
    assert domain.charge_type_folder("AC") == "AC"
    assert domain.charge_type_folder("") == "AC"
    assert domain.charge_type_folder("N/A") == "AC"


def test_needs_review_is_any_non_empty_value():
    assert domain.needs_review({"Review Needed": "confirm with the manufacturer"})
    assert not domain.needs_review({"Review Needed": ""})
    assert not domain.needs_review({})
