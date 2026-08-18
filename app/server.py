"""Local web UI over the register.

Routes only — the domain logic lives in domain.py, manifest.py and storage.py.
The register is held in memory and written through storage.save() on every
change, so the workbook on disk is always the current state.
"""

from __future__ import annotations

from pathlib import Path

import asyncio

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import (changelog, conflicts as conflicts_mod, domain, downloader,
               manifest as manifest_mod, schema, storage)
from .config import get_config

HERE = Path(__file__).resolve().parent

app = FastAPI(title="Zeres MID Register", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

_register: storage.Register | None = None


def register() -> storage.Register:
    """The loaded register, reading it from disk on first use."""
    global _register
    if _register is None:
        _register = storage.load()
    return _register


def reload_register() -> storage.Register:
    global _register
    _register = storage.load()
    return _register


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "templates" / "index.html")


@app.get("/api/register")
def get_register() -> dict:
    """Everything the UI needs for a full render."""
    reg = register()
    gaps = manifest_mod.find_gaps(reg.chargers, reg.meters, reg.manifest)
    return {
        "chargers": reg.chargers,
        "meters": reg.meters,
        "conflicts": [
            {**c, "opposed": conflicts_mod.is_opposed(c), "open": conflicts_mod.is_open(c)}
            for c in reg.conflicts
        ],
        "conflictStats": conflicts_mod.summarise(reg.conflicts),
        "manifest": reg.manifest,
        "changeLog": reg.change_log[-200:],
        "gaps": [
            {"id": g.get("ID"), "brand": g.get("Brand"), "model": g.get("Model"),
             "chargeType": g.get("Charge Type"), "url": g.get("Datasheet Link")}
            for g in gaps
        ],
        "stats": domain.summarise(reg.chargers),
        "vocabulary": {
            "statuses": list(schema.MID_STATUSES),
            "eligibility": schema.ELIGIBILITY_TEXT,
            "eligible": sorted(schema.ELIGIBLE_STATUSES),
            "checkUnit": sorted(schema.CHECK_UNIT_STATUSES),
        },
        "meta": {
            "path": str(reg.path),
            "user": domain.current_user(),
            "driveRoot": str(get_config().drive_root),
            "chargerColumns": list(schema.CHARGER_COLUMNS),
            "meterColumns": list(schema.METER_COLUMNS),
        },
    }


@app.post("/api/reload")
def post_reload() -> dict:
    reg = reload_register()
    return {"ok": True, "chargers": len(reg.chargers), "meters": len(reg.meters)}


@app.get("/api/health")
def health() -> dict:
    try:
        reg = register()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "chargers": len(reg.chargers), "meters": len(reg.meters)}


# ---------------------------------------------------------------------------
# editing
#
# Notes are never overwritten through this API. They carry quoted source
# language, and replacing an earlier quote with a newer one destroys the
# evidence trail — so callers send text to APPEND, and the note fields
# themselves are not directly writable.
# ---------------------------------------------------------------------------

CHARGER_EDITABLE = frozenset({
    "Brand", "Model", "Charge Type", "Max kW", "MID Status", "Meter Brand", "Meter Model",
    "Datasheet Link", "Certificate Link", "Drive Folder", "Research Status", "Source",
    "In Tracker", "In Zite", "Review Needed",
})
METER_EDITABLE = frozenset({
    "Brand", "Model", "MID Status", "Datasheet Link", "Certificate Link", "Drive Folder",
    "Research Status", "Source", "Review Needed",
})
NOTE_FIELD = {"charger": "Notes (EN)", "meter": "Notes"}


def _issued_ids(reg: storage.Register) -> list[str]:
    """Every ID the Change Log has ever seen, so a deleted ID is never reissued."""
    return [str(entry.get("Row ID", "")) for entry in reg.change_log]


def _persist(reg: storage.Register) -> None:
    try:
        storage.save(reg)
    except storage.StaleRegisterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _apply_edit(reg, row, kind, payload):
    """Validate, diff, log, apply and save one edit. Returns the change entries."""
    editable = CHARGER_EDITABLE if kind == "charger" else METER_EDITABLE
    fields = {k: v for k, v in (payload.get("fields") or {}).items() if k in editable}
    reason = str(payload.get("reason") or "").strip()
    append_en = str(payload.get("appendNote") or "").strip()
    append_nl = str(payload.get("appendNoteNl") or "").strip()

    if "MID Status" in fields:
        try:
            fields["MID Status"] = schema.validate_status(fields["MID Status"])
        except schema.StatusVocabularyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    proposed = {**row, **fields}
    changes = changelog.diff(row, proposed, editable)

    # Appended notes are logged too, so the audit trail shows what was added.
    note_field = NOTE_FIELD[kind]
    if append_en:
        merged = domain.append_note(row.get(note_field), append_en)
        if merged != str(row.get(note_field) or ""):
            proposed[note_field] = merged
            changes.append((note_field, "", append_en))
    if append_nl and kind == "charger":
        merged = domain.append_note(row.get("Notes (NL)"), append_nl)
        if merged != str(row.get("Notes (NL)") or ""):
            proposed["Notes (NL)"] = merged
            changes.append(("Notes (NL)", "", append_nl))

    if not changes:
        return []

    # A status change needs a stated reason; an appended note counts as one.
    try:
        entries = changelog.record(reg.change_log, row["ID"], changes, reason or append_en)
    except changelog.ChangeRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except schema.StatusVocabularyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row.update(proposed)
    _persist(reg)
    return entries


@app.patch("/api/chargers/{row_id}")
def patch_charger(row_id: str, payload: dict = Body(...)) -> dict:
    reg = register()
    row = reg.charger(row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No charger {row_id}")
    entries = _apply_edit(reg, row, "charger", payload)
    return {"ok": True, "row": row, "changes": entries,
            "stats": domain.summarise(reg.chargers)}


@app.patch("/api/meters/{row_id}")
def patch_meter(row_id: str, payload: dict = Body(...)) -> dict:
    reg = register()
    row = reg.meter(row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No meter {row_id}")
    entries = _apply_edit(reg, row, "meter", payload)
    return {"ok": True, "row": row, "changes": entries}


def _new_row(payload: dict, columns, editable, row_id: str) -> dict:
    fields = {k: str(v).strip() for k, v in (payload.get("fields") or {}).items() if k in editable}
    if not fields.get("Brand") or not fields.get("Model"):
        raise HTTPException(status_code=422, detail="Brand and Model are required.")
    try:
        status = schema.validate_status(fields.get("MID Status"))
    except schema.StatusVocabularyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row = {column: "" for column in columns}
    row.update(fields)
    row["ID"] = row_id
    row["MID Status"] = status
    if not row.get("Review Needed"):
        row["Review Needed"] = "Added by hand; not yet confirmed against a primary source."
    return row


@app.post("/api/chargers")
def post_charger(payload: dict = Body(...)) -> dict:
    reg = register()
    row = _new_row(payload, schema.CHARGER_COLUMNS, CHARGER_EDITABLE,
                   domain.next_id(reg.chargers, schema.ID_PREFIX[schema.SHEET_CHARGERS],
                                  issued=_issued_ids(reg)))
    note = str(payload.get("appendNote") or "").strip()
    if note:
        row["Notes (EN)"] = note
    if not row.get("Drive Folder"):
        row["Drive Folder"] = (f"Technical/Chargers/{domain.charge_type_folder(row['Charge Type'])}"
                               f" Chargers/{row['Brand']}")
    reg.chargers.append(row)
    changelog.record(reg.change_log, row["ID"],
                     [("row", "", f"created {row['Brand']} {row['Model']}")],
                     reason=str(payload.get("reason") or "").strip() or note)
    _persist(reg)
    return {"ok": True, "row": row, "stats": domain.summarise(reg.chargers)}


@app.post("/api/meters")
def post_meter(payload: dict = Body(...)) -> dict:
    reg = register()
    row = _new_row(payload, schema.METER_COLUMNS, METER_EDITABLE,
                   domain.next_id(reg.meters, schema.ID_PREFIX[schema.SHEET_METERS],
                                  issued=_issued_ids(reg)))
    note = str(payload.get("appendNote") or "").strip()
    if note:
        row["Notes"] = note
    if not row.get("Drive Folder"):
        row["Drive Folder"] = f"Technical/Meters/{row['Brand']}"
    reg.meters.append(row)
    changelog.record(reg.change_log, row["ID"],
                     [("row", "", f"created {row['Brand']} {row['Model']}")],
                     reason=str(payload.get("reason") or "").strip() or note)
    _persist(reg)
    return {"ok": True, "row": row}


@app.get("/api/history/{row_id}")
def get_history(row_id: str) -> dict:
    return {"entries": changelog.history(register().change_log, row_id)}


@app.post("/api/conflicts/{conflict_id}/resolve")
def post_resolve_conflict(conflict_id: str, payload: dict = Body(...)) -> dict:
    """Apply a human's decision. There is no auto-resolve anywhere in this app."""
    reg = register()
    try:
        result = conflicts_mod.resolve(reg, conflict_id,
                                       str(payload.get("decision") or ""),
                                       str(payload.get("reason") or ""))
    except conflicts_mod.ConflictError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except schema.StatusVocabularyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except changelog.ChangeRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _persist(reg)
    return {"ok": True, "conflict": result["conflict"], "charger": result["charger"],
            "conflictStats": conflicts_mod.summarise(reg.conflicts),
            "stats": domain.summarise(reg.chargers)}


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------

@app.post("/api/manifest")
def post_manifest_row(payload: dict = Body(...)) -> dict:
    """Add one queue row by hand."""
    reg = register()
    row = {column: str(payload.get(column, "") or "").strip()
           for column in schema.MANIFEST_COLUMNS}
    if not row["Brand"] or not row["Filename"]:
        raise HTTPException(status_code=422, detail="Brand and Filename are required.")
    reg.manifest.append(row)
    _persist(reg)
    return {"ok": True, "row": row, "manifest": reg.manifest}


@app.delete("/api/manifest/{index}")
def delete_manifest_row(index: int) -> dict:
    reg = register()
    if not 0 <= index < len(reg.manifest):
        raise HTTPException(status_code=404, detail=f"No manifest row at {index}")
    removed = reg.manifest.pop(index)
    _persist(reg)
    return {"ok": True, "removed": removed, "manifest": reg.manifest}


@app.post("/api/manifest/queue-gaps")
def post_queue_gaps(payload: dict = Body(default={})) -> dict:
    """Queue register rows whose datasheet link never reached the manifest.

    Optionally limited to specific register IDs; with none given, queues them all.
    """
    reg = register()
    wanted = set(payload.get("ids") or [])
    gaps = manifest_mod.find_gaps(reg.chargers, reg.meters, reg.manifest)
    if wanted:
        gaps = [g for g in gaps if g.get("ID") in wanted]

    meter_ids = {m["ID"] for m in reg.meters}
    added = []
    for row in gaps:
        added += manifest_mod.queue_rows(reg.manifest, [row],
                                         is_meter=row.get("ID") in meter_ids)
    if added:
        _persist(reg)
    remaining = manifest_mod.find_gaps(reg.chargers, reg.meters, reg.manifest)
    return {"ok": True, "added": added, "manifest": reg.manifest,
            "gaps": [{"id": g.get("ID"), "brand": g.get("Brand"), "model": g.get("Model"),
                      "chargeType": g.get("Charge Type"), "url": g.get("Datasheet Link")}
                     for g in remaining]}


# ---------------------------------------------------------------------------
# downloader
# ---------------------------------------------------------------------------

_job: downloader.Job | None = None


@app.post("/api/download")
async def post_download(payload: dict = Body(default={})) -> dict:
    """Start a download run over the queue. Returns immediately; poll for progress."""
    global _job
    if _job is not None and _job.running:
        raise HTTPException(status_code=409, detail="A download is already running.")

    reg = register()
    rows = reg.manifest
    if payload.get("filenames"):
        wanted = set(payload["filenames"])
        rows = [m for m in rows if m.get("Filename") in wanted]

    _job = downloader.Job()
    asyncio.create_task(downloader.run(rows, _job))
    return {"ok": True, "started": len(rows), "driveRoot": str(get_config().technical_root)}


@app.get("/api/download/status")
def get_download_status() -> dict:
    if _job is None:
        return {"idle": True}
    return {"idle": False, **_job.summary()}
