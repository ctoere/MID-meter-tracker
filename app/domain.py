"""Domain rules that outlive any particular screen.

Read CLAUDE.md alongside this file — the rules encoded here are compliance
rules, not UI preferences, and getting them wrong has a cost measured in
wrongly-booked kWh or wrongly-refused customers.
"""

from __future__ import annotations

import getpass
import re
from datetime import datetime
from typing import Any, Iterable

from . import schema

Row = dict[str, Any]


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r"^([a-z]{3})_(\d+)$")


def next_id(rows: Iterable[Row], prefix: str) -> str:
    """Allocate the next free ``<prefix>_NNNN``.

    IDs are stable and never reused: we take max+1 rather than count+1, so
    deleting a row does not hand its ID to a different piece of hardware.
    """
    highest = 0
    for row in rows:
        match = _ID_RE.match(str(row.get("ID", "")).strip())
        if match and match.group(1) == prefix:
            highest = max(highest, int(match.group(2)))
    return f"{prefix}_{highest + 1:04d}"


def current_user() -> str:
    """OS username — good enough for an internal, ~20 person tool."""
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - depends on the host
        return "unknown"


def now_stamp() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


# ---------------------------------------------------------------------------
# eligibility
# ---------------------------------------------------------------------------

def needs_review(row: Row) -> bool:
    """A non-empty 'Review Needed' means the row is NOT safe to quote to a client."""
    return str(row.get("Review Needed", "") or "").strip() != ""


def status_of(row: Row) -> str:
    return str(row.get("MID Status", "") or "").strip() or schema.DEFAULT_STATUS


def summarise(rows: list[Row]) -> dict[str, int]:
    """The stat tiles, computed in one place so the numbers can't drift apart.

    'eligible_check_unit' deliberately sums Optional AND External: both mean the
    model qualifies and the individual unit must be verified. Neither is a no.
    """
    counts = {status: 0 for status in schema.MID_STATUSES}
    for row in rows:
        status = status_of(row)
        counts[status if status in counts else "Unknown"] += 1
    return {
        "total": len(rows),
        "brands": len({str(r.get("Brand", "")).strip() for r in rows if r.get("Brand")}),
        "eligible_as_sold": counts["Integrated"],
        "eligible_check_unit": counts["Optional"] + counts["External"],
        "not_eligible": counts["None"],
        "unknown": counts["Unknown"],
        "needs_review": sum(1 for r in rows if needs_review(r)),
        "by_status": counts,
    }


# ---------------------------------------------------------------------------
# Drive tree + filenames
# ---------------------------------------------------------------------------

def charge_type_folder(charge_type: Any) -> str:
    """'DC' for anything that starts with a D, otherwise 'AC'.

    The register has a handful of 'N/A' charge types on meter-ish rows; those
    file under AC rather than inventing a third tree.
    """
    return "DC" if str(charge_type or "").strip().upper().startswith("D") else "AC"


def charger_subfolder(row: Row) -> str:
    """Manifest SubFolder for a charger row — backslashes, mirrors Drive."""
    return f"Chargers\\{charge_type_folder(row.get('Charge Type'))} Chargers\\{row.get('Brand', '').strip()}"


def meter_subfolder(row: Row) -> str:
    return f"Meters\\{str(row.get('Brand', '')).strip()}"


def model_slug(model: Any) -> str:
    """'Eve Single Plus' -> 'EveSinglePlus'.

    The filename convention is <Brand>_<ModelNoSpaces>_datasheet.pdf, so spaces
    and punctuation come out and the rest is left alone.
    """
    return re.sub(r"[^0-9A-Za-z]+", "", str(model or ""))


def brand_slug(brand: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", str(brand or ""))


def datasheet_filename(brand: Any, model: Any, extension: str = ".pdf") -> str:
    return f"{brand_slug(brand)}_{model_slug(model)}_datasheet{extension}"


# ---------------------------------------------------------------------------
# note handling
# ---------------------------------------------------------------------------

def append_note(existing: Any, addition: str) -> str:
    """Append to a note, never overwrite.

    Notes carry quoted source language. Losing an earlier quote to make room for
    a newer one destroys the evidence trail, so edits always accumulate.
    """
    current = str(existing or "").strip()
    addition = addition.strip()
    if not addition:
        return current
    if not current:
        return addition
    if addition in current:
        return current
    return f"{current}\n\n{addition}"
