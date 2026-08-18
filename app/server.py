"""Local web UI over the register.

Routes only — the domain logic lives in domain.py, manifest.py and storage.py.
The register is held in memory and written through storage.save() on every
change, so the workbook on disk is always the current state.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import domain, manifest as manifest_mod, schema, storage
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
        "conflicts": reg.conflicts,
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
