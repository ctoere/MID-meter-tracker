"""Phase 2 — editing, and the audit trail it must leave behind."""

import pytest
from fastapi.testclient import TestClient

from app import changelog, schema, server, storage


@pytest.fixture
def client(sandbox):
    server.reload_register()
    with TestClient(server.app) as c:
        yield c


def test_status_change_without_a_reason_is_refused(client):
    """An unexplained status change is exactly what an NEa audit would query."""
    res = client.patch("/api/chargers/chg_0006", json={"fields": {"MID Status": "Integrated"}})
    assert res.status_code == 422
    assert "requires a source or a note" in res.json()["detail"]
    # and nothing was written
    assert storage.load().charger("chg_0006")["MID Status"] == "External"


def test_status_outside_the_vocabulary_is_refused(client):
    res = client.patch("/api/chargers/chg_0006",
                       json={"fields": {"MID Status": "Yes"}, "reason": "seed data"})
    assert res.status_code == 422
    assert "is not a MID status" in res.json()["detail"]


def test_status_change_with_a_reason_persists_and_is_logged(client):
    res = client.patch("/api/chargers/chg_0006", json={
        "fields": {"MID Status": "Integrated"},
        "reason": "datasheet 1SDC007321L0901 p.2: 'MID' listed as standard"})
    assert res.status_code == 200

    reloaded = storage.load()
    assert reloaded.charger("chg_0006")["MID Status"] == "Integrated"

    entry = [e for e in reloaded.change_log if e["Row ID"] == "chg_0006" and e["User"] != "migration"][-1]
    assert entry["Field"] == "MID Status"
    assert entry["Old Value"] == "External"
    assert entry["New Value"] == "Integrated"
    assert "1SDC007321L0901" in entry["Reason"]
    assert entry["Timestamp"] and entry["User"]


def test_editing_leaves_a_backup(client, sandbox):
    from app.config import get_config
    client.patch("/api/chargers/chg_0006",
                 json={"fields": {"MID Status": "Integrated"}, "reason": "test"})
    assert list(get_config().backup_dir.glob("*.xlsx"))


def test_notes_are_appended_never_overwritten(client):
    before = storage.load().charger("chg_0006")["Notes (EN)"]
    res = client.patch("/api/chargers/chg_0006", json={"appendNote": "A later quoted finding."})
    assert res.status_code == 200

    after = storage.load().charger("chg_0006")["Notes (EN)"]
    assert before in after                       # every earlier word survives
    assert after.endswith("A later quoted finding.")


def test_the_change_log_is_append_only(client):
    before = storage.load().change_log
    client.patch("/api/chargers/chg_0006", json={"appendNote": "one"})
    client.patch("/api/chargers/chg_0007", json={"appendNote": "two"})
    after = storage.load().change_log

    assert len(after) == len(before) + 2
    assert after[:len(before)] == before          # nothing earlier was altered


def test_a_no_op_edit_logs_nothing(client):
    before = len(storage.load().change_log)
    row = storage.load().charger("chg_0006")
    res = client.patch("/api/chargers/chg_0006", json={"fields": {"Brand": row["Brand"]}})
    assert res.json()["changes"] == []
    assert len(storage.load().change_log) == before


def test_new_charger_gets_a_fresh_id_and_defaults_to_unknown(client):
    before = storage.load()
    res = client.post("/api/chargers", json={
        "fields": {"Brand": "Testmerk", "Model": "TM-1", "Charge Type": "AC"},
        "reason": "added during testing"})
    assert res.status_code == 200
    row = res.json()["row"]

    assert row["ID"] == "chg_0448"
    assert row["MID Status"] == "Unknown"          # absence of evidence, never None
    assert row["Review Needed"]                    # not safe to quote
    assert row["Drive Folder"] == "Technical/Chargers/AC Chargers/Testmerk"
    assert len(storage.load().chargers) == len(before.chargers) + 1


def test_new_row_requires_brand_and_model(client):
    assert client.post("/api/chargers", json={"fields": {"Brand": "OnlyBrand"}}).status_code == 422


def test_ids_are_never_reused(client):
    """Deleting a row must not hand its ID to different hardware."""
    reg = storage.load()
    reg.chargers = [r for r in reg.chargers if r["ID"] != "chg_0447"]
    storage.save(reg)
    server.reload_register()

    res = client.post("/api/chargers", json={"fields": {"Brand": "Testmerk", "Model": "TM-2"}})
    assert res.json()["row"]["ID"] == "chg_0448"   # max+1 over the log, not count+1


def test_new_meter_is_created_in_the_meters_sheet(client):
    res = client.post("/api/meters", json={
        "fields": {"Brand": "Inepro", "Model": "PRO380-Mod", "MID Status": "Integrated"},
        "reason": "NMi certificate"})
    assert res.status_code == 200
    assert res.json()["row"]["ID"] == "mtr_0005"
    assert res.json()["row"]["Drive Folder"] == "Technical/Meters/Inepro"
    assert len(storage.load().meters) == 5


def test_id_is_not_editable(client):
    client.patch("/api/chargers/chg_0006", json={"fields": {"ID": "chg_9999"}})
    assert storage.load().charger("chg_0006") is not None


def test_history_returns_this_rows_entries_newest_first(client):
    client.patch("/api/chargers/chg_0006", json={"appendNote": "first"})
    client.patch("/api/chargers/chg_0006", json={"appendNote": "second"})
    entries = client.get("/api/history/chg_0006").json()["entries"]
    assert entries[0]["New Value"] == "second"
    assert all(e["Row ID"] == "chg_0006" for e in entries)


def test_stats_recompute_after_an_edit(client):
    before = client.get("/api/register").json()["stats"]
    res = client.patch("/api/chargers/chg_0006",
                       json={"fields": {"MID Status": "Integrated"}, "reason": "datasheet"})
    after = res.json()["stats"]
    assert after["eligible_as_sold"] == before["eligible_as_sold"] + 1
    # External -> Integrated moves between eligible buckets; the total stays put
    assert after["eligible_check_unit"] == before["eligible_check_unit"] - 1


def test_reason_required_set_is_explicit():
    assert "MID Status" in changelog.REASON_REQUIRED
