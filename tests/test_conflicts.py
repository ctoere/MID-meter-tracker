"""Phase 3 — conflicts.

The register's Conflicts sheet is empty, so these build their own rows. That is
the point: the behaviour has to be right before the 25 real disagreements land.
"""

import pytest
from fastapi.testclient import TestClient

from app import conflicts, server, storage


def make_conflict(tracker, zite, cid="cfl_0001", charger_id="chg_0006", **extra):
    return {"ID": cid, "Charger ID": charger_id, "Brand": "ABB", "Model": "Terra AC Wallbox",
            "Tracker says": tracker, "Tracker note": "datasheet lists a MID meter",
            "Zite says": zite, "Zite original value": "nee", "Zite note": "marked no in 2023",
            "Decision": "", "Decided By": "", "Decided At": "", **extra}


@pytest.fixture
def client(sandbox):
    reg = storage.load()
    reg.conflicts = [
        make_conflict("Optional", "None", "cfl_0001"),
        make_conflict("Integrated", "Optional", "cfl_0002", charger_id="chg_0007"),
        make_conflict("External", "None", "cfl_0003", charger_id="chg_0008"),
    ]
    storage.save(reg)
    server.reload_register()
    with TestClient(server.app) as c:
        yield c


# ── opposed detection ──────────────────────────────────────────────────────

@pytest.mark.parametrize("tracker,zite", [
    ("Integrated", "None"), ("Optional", "None"), ("External", "None"),
    ("None", "Integrated"), ("None", "Optional"), ("None", "External"),
])
def test_eligible_versus_none_is_opposed(tracker, zite):
    """The serious ones: the client's answer depended on which system was opened."""
    assert conflicts.is_opposed(make_conflict(tracker, zite))


@pytest.mark.parametrize("tracker,zite", [
    ("Integrated", "Optional"),   # both eligible — a precision problem, not a yes/no
    ("Optional", "External"),
    ("None", "Unknown"),          # neither asserts eligibility
    ("Unknown", "Integrated"),
])
def test_other_disagreements_are_not_opposed(tracker, zite):
    assert not conflicts.is_opposed(make_conflict(tracker, zite))


def test_summary_counts_open_and_opposed(client):
    stats = client.get("/api/register").json()["conflictStats"]
    assert stats == {"total": 3, "open": 3, "resolved": 0, "opposed": 2, "opposed_open": 2}


# ── resolution ─────────────────────────────────────────────────────────────

def test_nothing_is_auto_resolved(client):
    """Loading the register must never decide anything."""
    for c in client.get("/api/register").json()["conflicts"]:
        assert c["open"] and not c["Decision"]


def test_resolving_requires_a_reason(client):
    res = client.post("/api/conflicts/cfl_0001/resolve", json={"decision": "Optional"})
    assert res.status_code == 422
    assert "requires a reason" in res.json()["detail"]
    assert storage.load().conflicts[0]["Decision"] == ""


def test_resolving_writes_the_decision_into_the_charger_row(client):
    res = client.post("/api/conflicts/cfl_0001/resolve", json={
        "decision": "Optional", "reason": "datasheet confirms the MID variant"})
    assert res.status_code == 200

    reloaded = storage.load()
    assert reloaded.charger("chg_0006")["MID Status"] == "Optional"
    conflict = reloaded.conflicts[0]
    assert conflict["Decision"] == "Optional"
    assert conflict["Decided By"] and conflict["Decided At"]


def test_resolving_clears_the_conflict_marker_on_the_row(client):
    reg = storage.load()
    reg.charger("chg_0006")["Conflict"] = "tracker says Optional, Zite says None"
    storage.save(reg)
    server.reload_register()

    client.post("/api/conflicts/cfl_0001/resolve",
                json={"decision": "Optional", "reason": "checked the datasheet"})
    assert storage.load().charger("chg_0006")["Conflict"] == ""


def test_resolving_does_not_clear_review_needed(client):
    """Adjudicating a source disagreement is not the same as verifying the row.

    The Review Needed flags mostly say the row came from the unverified seed
    import; clearing them here would silently mark rows as safe to quote.
    """
    before = storage.load().charger("chg_0006")["Review Needed"]
    assert before
    client.post("/api/conflicts/cfl_0001/resolve",
                json={"decision": "Optional", "reason": "datasheet"})
    assert storage.load().charger("chg_0006")["Review Needed"] == before


def test_resolution_is_logged_with_its_reasoning(client):
    client.post("/api/conflicts/cfl_0001/resolve", json={
        "decision": "Optional", "reason": "ABB doc 1SDC007321L0901 covers both variants"})
    log = storage.load().change_log
    entries = [e for e in log if e["Row ID"] in {"chg_0006", "cfl_0001"} and e["User"] != "migration"]
    assert entries
    assert any("1SDC007321L0901" in e["Reason"] for e in entries)
    assert any("the research tracker" in e["Reason"] for e in entries)


def test_resolution_appends_both_sides_to_the_notes(client):
    client.post("/api/conflicts/cfl_0001/resolve",
                json={"decision": "Optional", "reason": "datasheet"})
    note = storage.load().charger("chg_0006")["Notes (EN)"]
    assert "said Optional" in note
    assert "said None" in note


def test_the_notes_name_the_actual_sources_that_disagreed(client):
    """Whoever reads the row later needs to know which two things disagreed."""
    reg = storage.load()
    reg.conflicts[0]["Source A"] = "MID Register"
    reg.conflicts[0]["Source B"] = "Zeres laadpalen list v19 Aug 2026"
    storage.save(reg)
    server.reload_register()

    client.post("/api/conflicts/cfl_0001/resolve",
                json={"decision": "Optional", "reason": "datasheet confirms the variant"})
    note = storage.load().charger("chg_0006")["Notes (EN)"]
    assert "MID Register said Optional" in note
    assert "Zeres laadpalen list v19 Aug 2026 said None" in note


def test_a_resolved_conflict_cannot_be_silently_redecided(client):
    client.post("/api/conflicts/cfl_0001/resolve",
                json={"decision": "Optional", "reason": "first call"})
    res = client.post("/api/conflicts/cfl_0001/resolve",
                      json={"decision": "None", "reason": "second call"})
    assert res.status_code == 422
    assert "already decided" in res.json()["detail"]
    assert storage.load().charger("chg_0006")["MID Status"] == "Optional"


def test_decision_must_be_in_the_vocabulary(client):
    res = client.post("/api/conflicts/cfl_0001/resolve",
                      json={"decision": "Maybe", "reason": "x"})
    assert res.status_code == 422
    assert "is not a MID status" in res.json()["detail"]


def test_choosing_neither_side_is_allowed_and_recorded(client):
    """Sometimes research shows both systems were wrong."""
    res = client.post("/api/conflicts/cfl_0001/resolve", json={
        "decision": "Unknown", "reason": "neither source cites a document; needs research"})
    assert res.status_code == 200
    log = storage.load().change_log
    assert any("neither source" in e["Reason"] for e in log if e["User"] != "migration")


def test_conflict_pointing_at_a_missing_charger_is_refused(client):
    reg = storage.load()
    reg.conflicts.append(make_conflict("Integrated", "None", "cfl_0009",
                                       charger_id="chg_9999", Brand="Ghost", Model="Nonexistent"))
    storage.save(reg)
    server.reload_register()
    res = client.post("/api/conflicts/cfl_0009/resolve",
                      json={"decision": "Integrated", "reason": "x"})
    assert res.status_code == 422
    assert "not in the register" in res.json()["detail"]


def test_charger_is_found_by_brand_and_model_when_id_is_missing(client):
    reg = storage.load()
    reg.conflicts.append(make_conflict("Integrated", "None", "cfl_0010", charger_id=""))
    storage.save(reg)
    server.reload_register()
    res = client.post("/api/conflicts/cfl_0010/resolve",
                      json={"decision": "Integrated", "reason": "datasheet"})
    assert res.status_code == 200
    assert res.json()["charger"]["ID"] == "chg_0006"
