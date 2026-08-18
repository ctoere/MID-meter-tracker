"""The only module that knows the register is an .xlsx file.

Everything above this line works with plain lists of dicts. Moving the register
into Google Sheets or SharePoint later means rewriting this file and nothing
else, so keep the interface narrow: load(), save(), backup().

Write safety
------------
The workbook lives in a synced folder and may be open in Excel while we write.
So save() never writes in place. It:

  1. copies the current file to backups/Zeres_MID_Register_<timestamp>.xlsx
  2. builds the new workbook from the existing one (so unmanaged sheets such as
     'Read Me' survive byte-for-byte in content)
  3. writes to a temp file in the same directory
  4. os.replace()s it over the original, which is atomic on the same filesystem

A crash at any point leaves either the old file or the new one, never a half
written workbook.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from . import schema
from .config import get_config

Row = dict[str, Any]


class StaleRegisterError(RuntimeError):
    """The workbook changed on disk since it was loaded."""


@dataclass
class Register:
    """An in-memory snapshot of the workbook."""

    chargers: list[Row] = field(default_factory=list)
    meters: list[Row] = field(default_factory=list)
    conflicts: list[Row] = field(default_factory=list)
    manifest: list[Row] = field(default_factory=list)
    change_log: list[Row] = field(default_factory=list)

    path: Path | None = None
    #: mtime at load, used to detect an edit made in Excel behind our back
    loaded_mtime: float | None = None

    def sheet(self, name: str) -> list[Row]:
        return {
            schema.SHEET_CHARGERS: self.chargers,
            schema.SHEET_METERS: self.meters,
            schema.SHEET_CONFLICTS: self.conflicts,
            schema.SHEET_MANIFEST: self.manifest,
            schema.SHEET_CHANGE_LOG: self.change_log,
        }[name]

    def charger(self, row_id: str) -> Row | None:
        return next((r for r in self.chargers if r.get("ID") == row_id), None)

    def meter(self, row_id: str) -> Row | None:
        return next((r for r in self.meters if r.get("ID") == row_id), None)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _cell_to_text(value: Any) -> str:
    """Normalise a cell to a stripped string.

    Everything in the register is text: statuses, links, notes, IDs. Keeping one
    representation end to end is what makes a load/save round trip lossless —
    no float drift on '11.0', no date coercion on a model name.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value).strip()


def _read_sheet(wb: openpyxl.Workbook, name: str, columns: tuple[str, ...]) -> list[Row]:
    """Read a managed sheet into dicts keyed by the schema's column names.

    Columns present in the file but not in the schema are preserved too, so a
    colleague's extra column is never silently dropped on the next save.
    """
    if name not in wb.sheetnames:
        return []
    ws = wb[name]
    rows = ws.iter_rows(values_only=True)
    try:
        header = [_cell_to_text(c) for c in next(rows)]
    except StopIteration:
        return []

    out: list[Row] = []
    for raw in rows:
        if all(c is None or _cell_to_text(c) == "" for c in raw):
            continue  # blank spacer row
        record: Row = {col: "" for col in columns}
        for key, value in zip(header, raw):
            if key:
                record[key] = _cell_to_text(value)
        out.append(record)
    return out


def _column_order(rows: list[Row], columns: tuple[str, ...]) -> list[str]:
    """Schema order first, then any extra columns found in the data."""
    order = list(columns)
    for row in rows:
        for key in row:
            if key not in order:
                order.append(key)
    return order


def _write_sheet(wb: openpyxl.Workbook, name: str, rows: list[Row], columns: tuple[str, ...]) -> None:
    """Replace a managed sheet with ``rows``, keeping its position in the tabs."""
    index = wb.sheetnames.index(name) if name in wb.sheetnames else len(wb.sheetnames)
    if name in wb.sheetnames:
        wb.remove(wb[name])
    ws = wb.create_sheet(title=name, index=index)

    order = _column_order(rows, columns)
    ws.append(order)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"

    for row in rows:
        ws.append([_cell_to_text(row.get(col, "")) for col in order])

    # Readable widths — this file gets opened in Excel by hand.
    widths = {"Notes (EN)": 80, "Notes (NL)": 60, "Notes": 80, "Review Needed": 50,
              "Source": 40, "Research Status": 34, "Datasheet Link": 46,
              "Certificate Link": 46, "Drive Folder": 40, "Url": 46,
              "Tracker note": 60, "Zite note": 60, "Reason": 50}
    for i, col in enumerate(order, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(col, 18)


# ---------------------------------------------------------------------------
# public interface — load / save / backup
# ---------------------------------------------------------------------------

def load(path: str | Path | None = None) -> Register:
    """Read the workbook into memory."""
    target = Path(path) if path else get_config().register_path
    if not target.exists():
        raise FileNotFoundError(
            f"Register not found at {target}. Set [storage].register_path in config.toml, "
            f"or run: python -m migrate.migrate_tracker"
        )

    wb = openpyxl.load_workbook(target, data_only=True)
    reg = Register(
        chargers=_read_sheet(wb, schema.SHEET_CHARGERS, schema.CHARGER_COLUMNS),
        meters=_read_sheet(wb, schema.SHEET_METERS, schema.METER_COLUMNS),
        conflicts=_read_sheet(wb, schema.SHEET_CONFLICTS, schema.CONFLICT_COLUMNS),
        manifest=_read_sheet(wb, schema.SHEET_MANIFEST, schema.MANIFEST_COLUMNS),
        change_log=_read_sheet(wb, schema.SHEET_CHANGE_LOG, schema.CHANGE_LOG_COLUMNS),
        path=target,
        loaded_mtime=target.stat().st_mtime,
    )
    wb.close()
    return reg


def backup(path: str | Path | None = None) -> Path | None:
    """Copy the current workbook into the backup directory. Returns its path.

    Returns None when there is nothing to back up yet (first ever write).
    """
    cfg = get_config()
    target = Path(path) if path else cfg.register_path
    if not target.exists():
        return None

    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = cfg.backup_dir / f"{target.stem}_{stamp}{target.suffix}"

    # Same-second saves must not clobber each other.
    counter = 1
    while dest.exists():
        dest = cfg.backup_dir / f"{target.stem}_{stamp}_{counter}{target.suffix}"
        counter += 1

    shutil.copy2(target, dest)
    _prune_backups(cfg.backup_dir, target.stem, cfg.keep_backups)
    return dest


def _prune_backups(backup_dir: Path, stem: str, keep: int) -> None:
    """Keep only the newest ``keep`` backups."""
    existing = sorted(
        backup_dir.glob(f"{stem}_*.xlsx"),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    for stale in existing[keep:]:
        stale.unlink(missing_ok=True)


def save(register: Register, path: str | Path | None = None, *, force: bool = False) -> Path:
    """Back up, then atomically replace the workbook with ``register``.

    Raises StaleRegisterError if the file changed on disk since load() unless
    ``force`` is set — someone editing in Excel should not lose their work to us.
    """
    target = Path(path) if path else (register.path or get_config().register_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if (
        not force
        and register.loaded_mtime is not None
        and target.exists()
        and target.stat().st_mtime > register.loaded_mtime
    ):
        raise StaleRegisterError(
            f"{target.name} changed on disk since it was loaded — someone may have it open "
            f"in Excel. Reload before saving, or save with force=True to overwrite."
        )

    backup(target)

    # Start from the existing workbook so unmanaged sheets (Read Me, and
    # anything a colleague added) survive untouched.
    if target.exists():
        wb = openpyxl.load_workbook(target)
    else:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

    for name, columns in schema.MANAGED_SHEETS.items():
        _write_sheet(wb, name, register.sheet(name), columns)

    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".{}.".format(target.stem), suffix=".tmp.xlsx")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        wb.save(tmp)
        wb.close()
        os.replace(tmp, target)          # atomic on the same filesystem
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    register.path = target
    register.loaded_mtime = target.stat().st_mtime
    return target
