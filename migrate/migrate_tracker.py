"""One-time migration: Zeres_EV_Charger_MID_Meter_Tracker.xlsx -> Zeres_MID_Register.xlsx

The uploaded tracker predates the register schema. It has one 'Master Tracker'
sheet holding both chargers and meters, no stable IDs, and the older
Yes/No/Maybe vocabulary. This script produces the register the app expects:

    Read Me      carried over, with a migration section appended
    Chargers     from Master Tracker where Record Type = Charger, IDs chg_NNNN
    Meters       from Master Tracker where Record Type = Meter,   IDs mtr_NNNN
    Conflicts    created empty with headers (no conflict data exists yet)
    Manifest     from manifest.csv, unchanged
    Change Log   one entry per migrated MID Status, so the remap is auditable

Every migrated row gets 'Review Needed' set. Nothing in the seed data was
manufacturer-verified — the source Read Me calls it "a strong starting signal,
not a manufacturer-verified fact" — so no row is safe to quote to a client until
a human has confirmed it against a primary source.

Run:  python -m migrate.migrate_tracker [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import openpyxl

from app import schema, storage
from app.config import PROJECT_ROOT, get_config
from app.domain import now_stamp
from migrate.mapping import map_status

SOURCE_WORKBOOK = PROJECT_ROOT / "data" / "source" / "Zeres_EV_Charger_MID_Meter_Tracker.xlsx"
SOURCE_MANIFEST = PROJECT_ROOT / "data" / "source" / "manifest.csv"
SOURCE_SHEET = "Master Tracker"

MIGRATION_TAG = f"[migrated {date.today().isoformat()}]"


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def read_master_tracker(path: Path) -> list[dict[str, str]]:
    wb = openpyxl.load_workbook(path, data_only=True)
    rows = list(wb[SOURCE_SHEET].iter_rows(values_only=True))
    wb.close()
    header = [_text(c) for c in rows[0]]
    out = []
    for raw in rows[1:]:
        if all(c is None or _text(c) == "" for c in raw):
            continue
        out.append({k: _text(v) for k, v in zip(header, raw)})
    return out


def build_register(records: list[dict[str, str]], manifest_rows: list[dict[str, str]]):
    """Return (Register, report) — report is a dict of counters for the console."""
    chargers_src = [r for r in records if r.get("Record Type", "").lower() != "meter"]
    meters_src = [r for r in records if r.get("Record Type", "").lower() == "meter"]

    # Stable ordering so IDs are reproducible if this ever has to be re-run.
    sort_key = lambda r: (r.get("Brand", "").casefold(), r.get("Model", "").casefold())
    chargers_src.sort(key=sort_key)
    meters_src.sort(key=sort_key)

    report = {
        "seed_counts": Counter(r.get("MID Status", "") or "(blank)" for r in records),
        "mapped_counts": Counter(),
        "overrides": [],       # rows the notes moved away from the base mapping
        "eichrecht": 0,
    }
    change_log: list[dict[str, str]] = []
    stamp = now_stamp()

    def migrate_row(src: dict[str, str], row_id: str, is_meter: bool) -> dict[str, str]:
        seed = src.get("MID Status", "")
        notes = src.get("Notes", "")
        source = src.get("Source", "")
        mapped = map_status(seed, notes, source)
        report["mapped_counts"][mapped.status] += 1
        if mapped.eichrecht:
            report["eichrecht"] += 1

        base_direct = mapped.rule.startswith("seed value")
        if not base_direct:
            report["overrides"].append(
                (row_id, src.get("Brand", ""), src.get("Model", ""), seed, mapped.status, mapped.rule)
            )

        # Notes are appended to, never overwritten: the original wording is the
        # evidence, and the migration note records how the status was derived.
        provenance = (
            f"{MIGRATION_TAG} Seed MID Status was {seed or '(blank)'!r}; "
            f"migrated to {mapped.status!r} because {mapped.rule}. "
            f"Original seed source: {source or '(none recorded)'}."
        )
        combined_notes = f"{notes}\n\n{provenance}".strip() if notes else provenance

        review = (
            f"Migrated from the seed tracker on {date.today().isoformat()} "
            f"({seed or '(blank)'} -> {mapped.status}); not manufacturer-verified. "
            f"Confirm against a primary source before quoting a client."
        )

        change_log.append({
            "Timestamp": stamp,
            "User": "migration",
            "Row ID": row_id,
            "Field": "MID Status",
            "Old Value": seed,
            "New Value": mapped.status,
            "Reason": mapped.rule,
        })

        if is_meter:
            return {
                "ID": row_id,
                "Brand": src.get("Brand", ""),
                "Model": src.get("Model", ""),
                "MID Status": mapped.status,
                "Datasheet Link": src.get("Datasheet Link", ""),
                "Certificate Link": src.get("Certificate Link", ""),
                "Drive Folder": src.get("Drive Folder Path", ""),
                "Research Status": src.get("Research Status", ""),
                "Source": source,
                "Review Needed": review,
                "Notes": combined_notes,
            }
        return {
            "ID": row_id,
            "Brand": src.get("Brand", ""),
            "Model": src.get("Model", ""),
            "Charge Type": src.get("Charge Type", ""),
            "Max kW": "",                       # not present in the seed tracker
            "MID Status": mapped.status,
            "Meter Brand": src.get("Meter Brand", ""),
            "Meter Model": src.get("Meter Model", ""),
            "Datasheet Link": src.get("Datasheet Link", ""),
            "Certificate Link": src.get("Certificate Link", ""),
            "Drive Folder": src.get("Drive Folder Path", ""),
            "Research Status": src.get("Research Status", ""),
            "Source": source,
            "In Tracker": "yes",                # every row here came from the tracker
            "In Zite": "",                      # Zite state unknown at migration time
            "Conflict": "",
            "Review Needed": review,
            "Notes (EN)": combined_notes,
            "Notes (NL)": "",
        }

    chargers = [migrate_row(src, f"chg_{i:04d}", False) for i, src in enumerate(chargers_src, 1)]
    meters = [migrate_row(src, f"mtr_{i:04d}", True) for i, src in enumerate(meters_src, 1)]

    register = storage.Register(
        chargers=chargers,
        meters=meters,
        conflicts=[],
        manifest=manifest_rows,
        change_log=change_log,
    )
    return register, report


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [
            {col: _text(row.get(col, "")) for col in schema.MANIFEST_COLUMNS}
            for row in csv.DictReader(fh)
        ]


def write_read_me(target: Path, source: Path, report: dict) -> None:
    """Create the destination workbook carrying the original Read Me across."""
    src_wb = openpyxl.load_workbook(source, data_only=True)
    lines = [_text(row[0]) for row in src_wb["Read Me"].iter_rows(values_only=True)]
    src_wb.close()

    lines += [
        "",
        f"MIGRATION TO THE REGISTER SCHEMA ({date.today().isoformat()})",
        "This workbook was migrated from Zeres_EV_Charger_MID_Meter_Tracker.xlsx by",
        "migrate/migrate_tracker.py. What changed:",
        "- 'Master Tracker' was split into 'Chargers' and 'Meters', each with a stable ID",
        "  (chg_0001 / mtr_0001). IDs are never renumbered and never reused.",
        "- MID Status moved from Yes/No/Maybe/Unknown/N-A to the five-value vocabulary:",
        "    Integrated  MID meter built in as standard        -> eligible as sold",
        "    Optional    available as a variant or paid option -> ELIGIBLE, check the unit",
        "    External    uses a separate external MID meter    -> ELIGIBLE, check the unit",
        "    None        no MID metering                       -> not eligible as sold",
        "    Unknown     not established                       -> needs research",
        "  Optional and External are NOT rejections. Both mean the customer qualifies and",
        "  the individual unit has to be verified.",
        f"- Where a row's Notes described a MID option or an external MID meter, the notes won",
        f"  over the seed value. {len(report['overrides'])} rows moved this way. The important ones are seed 'No'",
        "  rows that in fact offer an optional or external MID meter: read literally they would",
        "  have told a qualifying customer they were ineligible.",
        "- Where seed and notes point in opposite directions the result is Unknown rather than a",
        "  guess, so the disagreement stays visible instead of being resolved silently.",
        "- Eichrecht/PTB markings are recorded but never counted as MID evidence. German",
        "  calibration law is a related but separate regime from Directive 2014/32/EU.",
        "- Every migrated row has 'Review Needed' set. The seed data was never",
        "  manufacturer-verified, so no row is safe to quote to a client until someone has",
        "  confirmed it against a primary source and cleared the flag.",
        "- The original Notes text is preserved verbatim; a provenance line was appended.",
        "- 'Change Log' records every status remap. It is append-only.",
        "- 'Conflicts' was created empty: the tracker held no Zite-vs-tracker conflict data.",
        "- 'Manifest' was imported from manifest.csv (265 rows) unchanged.",
    ]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = schema.SHEET_READ_ME
    for line in lines:
        ws.append([line])
    ws.column_dimensions["A"].width = 110
    target.parent.mkdir(parents=True, exist_ok=True)
    wb.save(target)
    wb.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    parser.add_argument("--out", type=Path, default=None, help="destination workbook")
    args = parser.parse_args(argv)

    target = args.out or get_config().register_path

    records = read_master_tracker(SOURCE_WORKBOOK)
    manifest_rows = read_manifest(SOURCE_MANIFEST)
    register, report = build_register(records, manifest_rows)

    print(f"Source      : {SOURCE_WORKBOOK.relative_to(PROJECT_ROOT)}  ({len(records)} rows)")
    print(f"Manifest    : {SOURCE_MANIFEST.relative_to(PROJECT_ROOT)}  ({len(manifest_rows)} rows)")
    print(f"Destination : {target}")
    print()
    print("Seed MID Status      ->  Migrated MID Status")
    for value, count in report["seed_counts"].most_common():
        print(f"  {value:<10} {count:>4}")
    print("  " + "-" * 20)
    for value in schema.MID_STATUSES:
        count = report["mapped_counts"].get(value, 0)
        note = "  <- ELIGIBLE, check the unit" if value in schema.CHECK_UNIT_STATUSES else ""
        print(f"  {value:<12} {count:>4}{note}")
    print()
    print(f"Rows whose Notes overrode the seed value: {len(report['overrides'])}")
    print(f"Rows mentioning Eichrecht/PTB (recorded, never treated as MID): {report['eichrecht']}")
    print()
    print("Reclassifications (seed -> migrated), for review:")
    for row_id, brand, model, seed, status, rule in report["overrides"]:
        flag = "  ** was read as ineligible **" if seed == "No" and status != "None" else ""
        print(f"  {row_id}  {brand} {model}".ljust(58) + f"{seed:>7} -> {status:<10}{flag}")
        print(f"      {rule}")
    print()
    print(f"Chargers: {len(register.chargers)}   Meters: {len(register.meters)}   "
          f"Manifest: {len(register.manifest)}   Change Log: {len(register.change_log)}   "
          f"Conflicts: {len(register.conflicts)}")
    print(f"Review Needed set on: {sum(1 for r in register.chargers + register.meters if r.get('Review Needed'))} rows")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    write_read_me(target, SOURCE_WORKBOOK, report)
    storage.save(register, target, force=True)
    print(f"\nWritten: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
