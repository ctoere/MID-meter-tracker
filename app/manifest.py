"""The datasheet download queue, and the gap between it and the register.

A "gap" is a register row that has a Datasheet Link whose URL is not in the
manifest. This has bitten Zeres twice: the register looks complete while the
download queue quietly has holes, so the Drive tree never receives the file and
the evidence behind a compliance claim is a URL on someone else's server that
can change or vanish. Gap detection is therefore a first-class feature, not a
tidy-up.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import domain

Row = dict[str, Any]


def queued_urls(manifest: Iterable[Row]) -> set[str]:
    """Every non-empty URL currently in the queue.

    A manifest row with an empty Url is legitimate — some datasheets came
    directly from the manufacturer and are filed by hand — so blanks are simply
    not part of the URL index rather than an error.
    """
    return {str(row.get("Url", "") or "").strip() for row in manifest} - {""}


def find_gaps(chargers: list[Row], meters: list[Row], manifest: list[Row]) -> list[Row]:
    """Register rows whose datasheet URL never made it into the queue.

    Deliberately keyed on the URL, not on brand/model: the same datasheet can
    legitimately cover several models, and what we care about is whether the
    file gets fetched.
    """
    queued = queued_urls(manifest)
    gaps: list[Row] = []
    seen: set[str] = set()
    for row in list(chargers) + list(meters):
        url = str(row.get("Datasheet Link", "") or "").strip()
        if not url or url in queued or url in seen:
            continue
        seen.add(url)
        gaps.append(row)
    return gaps


def manifest_row_for(row: Row, is_meter: bool = False) -> Row:
    """Build the manifest entry for a register row."""
    url = str(row.get("Datasheet Link", "") or "").strip()
    extension = ".html" if url.lower().endswith((".html", ".htm")) else ".pdf"
    return {
        "Brand": str(row.get("Brand", "") or "").strip(),
        "Model": str(row.get("Model", "") or "").strip(),
        "SubFolder": domain.meter_subfolder(row) if is_meter else domain.charger_subfolder(row),
        "Url": url,
        "Filename": domain.datasheet_filename(row.get("Brand"), row.get("Model"), extension),
    }


def queue_rows(manifest: list[Row], rows: list[Row], is_meter: bool = False) -> list[Row]:
    """Append manifest entries for ``rows``, skipping URLs already queued.

    Returns the rows actually added, so the UI can report a real count.
    """
    queued = queued_urls(manifest)
    added: list[Row] = []
    for row in rows:
        url = str(row.get("Datasheet Link", "") or "").strip()
        if not url or url in queued:
            continue
        entry = manifest_row_for(row, is_meter)
        manifest.append(entry)
        queued.add(url)
        added.append(entry)
    return added
