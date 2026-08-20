"""Import the Zeres laadpalen list (v19 Aug 2026) into the register.

Two jobs, both one-time and both reviewable before they write anything:

  1. Where the list and the register disagree about a model we already hold,
     open a Conflict. Nothing is auto-resolved — a person picks a side and says
     why, and the reasoning goes into the Change Log.
  2. Where the list has a model the register does not, add it.

Why the list needs reading rather than copying
----------------------------------------------
The list records MID status as Ja / Misschien / Nee. That binary cannot express
"eligible, but the individual unit must be checked", which is exactly the
distinction the register exists to preserve — so its own free-text notes
contradict its verdict in 19 of 185 rows. Seven Wallbox models are marked Nee
while their notes say an external MID meter is available; taken at face value
those rows refuse customers who qualify.

So the Dutch notes are read the same way the seed migration reads English ones:
an affirmative mention of an external meter or an option beats the headline
verdict, a negated one does not, and a verdict its own note contradicts becomes
Unknown rather than a guess in either direction.

The Dutch patterns live here rather than in app/evidence.py on purpose. That
module is shared with the intake pipeline and its behaviour is pinned by the
migration's golden test; a one-off import must not shift it.

Run:  python -m migrate.import_laadpalen_list [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from app import changelog, domain, schema, storage
from app.config import PROJECT_ROOT

SOURCE = PROJECT_ROOT / "data" / "source" / "Zeres_laadpalen_met_MIDmeter_v19aug2026.xlsx"
SOURCE_NAME = "Zeres laadpalen list v19 Aug 2026"
REGISTER_NAME = "MID Register"

#: Ja / Misschien / Nee, before the notes are consulted.
BASE = {"Ja": "Integrated", "Misschien": "Optional", "Nee": "None", "": "Unknown"}

# Dutch evidence language. Anchored on MID or "meter" for the same reason the
# English patterns are: "variant" on its own is product-line language.
EXTERNAL_NL = (
    r"extern\w*\s+(?:MID[- ]?)?(?:power\s+)?meter",
    r"externe\s+accessoire",
    r"als\s+extern\w*",
    r"aparte\s+(?:power\s+)?meter",
    r"\bseparate\s+meter\b",
    r"\bdeze\s+is\s+separaat\b",
    r"MID[^.;|]{0,40}\bextern",
)
OPTIONAL_NL = (
    r"\bals\s+optie\b",
    r"MID[^.;|]{0,40}\boptie\b",
    r"\boptie\b[^.;|]{0,40}MID",
    r"niet\s+standaard",
    r"MID[^.;|]{0,30}\+\s*variant",
    r"MID[^.;|]{0,40}\bvariant\b",
    r"\bvariant\b[^.;|]{0,40}MID",
    r"soms\s+een\s+ingebouwde",
)
#: The verdict is contradicted by its own note.
NO_BUILTIN_NL = (r"geen\s+ingebouwde", r"heeft\s+geen", r"\bgeen\s+\w*\s*MID\b",
                 r"geen\s+Europese\s+MID")

#: The product is not sold in the EU. This outranks the metering question
#: entirely: a charger that cannot be bought here cannot be booked into the REV,
#: and reading "an external MID meter is available" off such a row would offer an
#: eligibility that does not exist. Wallbox Quasar 2 is the live example — its
#: note offers an external Power Meter and, in the same sentence, says only the
#: North American version is on the market.
NOT_EU_MARKET_NL = (
    r"EU[- ]versie\s+is\s+niet\s+beschikbaar",
    r"niet\s+beschikbaar\s+in\s+(?:de\s+)?EU",
    r"alleen\s+de\s+NA[- ]versie",
    r"Noord[- ]Amerikaan\w*\s+markt",
    r"North\s+America",
    r"niet\s+(?:op\s+de\s+)?EU[- ]markt",
)

NEGATORS_NL = re.compile(r"\b(?:geen|niet|nooit|zonder)\b", re.IGNORECASE)
CLAUSE = re.compile(r"[;|]|\.\s|--")
WINDOW = 34


def _hit(patterns, text: str):
    for pattern in patterns:
        found = re.search(pattern, text, re.IGNORECASE)
        if found:
            before = text[max(0, found.start() - WINDOW):found.start()]
            before = CLAUSE.split(before)[-1]
            if not NEGATORS_NL.search(before):
                return found.group(0)
    return None


@dataclass
class Reading:
    status: str
    reason: str


def read_dutch(verdict: str, note: str) -> Reading:
    """Map one row of the list, letting its own note override the verdict."""
    note = note or ""
    base = BASE.get(verdict.strip(), "Unknown")

    # Market scope first — it decides whether the metering question even applies.
    for pattern in NOT_EU_MARKET_NL:
        found = re.search(pattern, note, re.IGNORECASE)
        if found:
            return Reading("Unknown",
                           f"the note says this is not on the EU market ({found.group(0).strip()!r}); "
                           f"a charger that cannot be bought here cannot be booked into the REV, "
                           f"whatever its metering")

    external = _hit(EXTERNAL_NL, note)
    optional = _hit(OPTIONAL_NL, note)
    no_builtin = _hit(NO_BUILTIN_NL, note)

    if external:
        return Reading("External", f"note describes a separate external meter ({external.strip()!r})")
    if optional:
        return Reading("Optional", f"note describes an option or variant ({optional.strip()!r})")
    if no_builtin and base == "Integrated":
        return Reading("Unknown",
                       f"listed {verdict!r} but the note says {no_builtin.strip()!r} — "
                       f"the list contradicts itself, so this is not established")
    return Reading(base, f"list says {verdict!r} and the note does not qualify it")


def normalise(text) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text or "").lower())


def eligibility(status: str) -> str:
    if status == "Integrated":
        return "eligible"
    if status in ("Optional", "External"):
        return "eligible-check"
    if status == "None":
        return "not eligible"
    return "unknown"


def load_list(path: Path) -> list[dict]:
    text = lambda v: "" if v is None else str(v).strip()
    ws = openpyxl.load_workbook(path, data_only=True)["Sheet1"]
    rows = list(ws.iter_rows(values_only=True))[1:]        # row 0 is a title banner
    out, seen = [], set()
    for raw in rows:
        record = {"brand": text(raw[0]), "model": text(raw[1]), "verdict": text(raw[2]),
                  "note": text(raw[3]), "url": text(raw[4]) if len(raw) > 4 else ""}
        if not (record["brand"] or record["model"]):
            continue
        key = (normalise(record["brand"]), normalise(record["model"]))
        if key in seen:                                    # the file repeats 3 rows verbatim
            continue
        seen.add(key)
        out.append(record)
    return out


def plan(register, listed: list[dict]) -> tuple[list, list]:
    """(conflicts to open, models to add) — computed, not applied."""
    by_key = {(normalise(c["Brand"]), normalise(c["Model"])): c for c in register.chargers}
    conflicts, additions = [], []

    for record in listed:
        reading = read_dutch(record["verdict"], record["note"])
        existing = by_key.get((normalise(record["brand"]), normalise(record["model"])))
        if existing is None:
            additions.append((record, reading))
            continue
        if eligibility(existing["MID Status"]) != eligibility(reading.status):
            conflicts.append((record, reading, existing))

    return conflicts, additions


def apply(register, conflicts, additions) -> dict:
    stamp = domain.now_stamp()
    user = domain.current_user()
    issued = [e.get("Row ID", "") for e in register.change_log]

    for record, reading, existing in conflicts:
        conflict_id = domain.next_id(register.conflicts,
                                     schema.ID_PREFIX[schema.SHEET_CONFORMITY].replace("cfm", "cfl"),
                                     issued=issued)
        issued.append(conflict_id)
        register.conflicts.append({
            "ID": conflict_id,
            "Charger ID": existing["ID"],
            "Brand": existing["Brand"],
            "Model": existing["Model"],
            "Source A": REGISTER_NAME,
            "Source B": SOURCE_NAME,
            "Tracker says": existing["MID Status"],
            "Tracker note": (existing.get("Notes (EN)") or "")[:600],
            "Zite says": reading.status,
            "Zite original value": record["verdict"],
            "Zite note": f"{record['note']} [read as {reading.status}: {reading.reason}]"[:600],
            "Decision": "", "Decided By": "", "Decided At": "",
        })
        changelog.record(register.change_log, conflict_id,
                         [("conflict", "", f"opened: {REGISTER_NAME} says "
                                           f"{existing['MID Status']}, {SOURCE_NAME} says "
                                           f"{record['verdict']} ({reading.status})")],
                         reason=f"Imported from {SOURCE_NAME}. {reading.reason}", user=user)

    for record, reading in additions:
        row_id = domain.next_id(register.chargers, schema.ID_PREFIX[schema.SHEET_CHARGERS],
                                issued=issued)
        issued.append(row_id)
        note = (f"{record['note']}\n\n[imported {stamp[:10]} from {SOURCE_NAME}] "
                f"Listed as {record['verdict']!r}; recorded as {reading.status} because "
                f"{reading.reason}.")
        row = {column: "" for column in schema.CHARGER_COLUMNS}
        row.update({
            "ID": row_id,
            "Brand": record["brand"],
            "Model": record["model"],
            "Charge Type": "AC",
            "MID Status": reading.status,
            "Datasheet Link": record["url"],
            "Drive Folder": f"Technical/Chargers/AC Chargers/{record['brand']}",
            "Research Status": "Needs Research",
            "Source": SOURCE_NAME,
            "In Tracker": "", "In Zite": "",
            "Review Needed": (f"Added {stamp[:10]} from {SOURCE_NAME}; not manufacturer-verified "
                              f"and not previously in the register. Confirm against a primary "
                              f"source before quoting a client."),
            "Notes (EN)": note,
        })
        register.chargers.append(row)
        changelog.record(register.change_log, row_id,
                         [("row", "", f"created {record['brand']} {record['model']}")],
                         reason=f"Imported from {SOURCE_NAME}: listed {record['verdict']!r}. "
                                f"{reading.reason}", user=user)

    return {"conflicts": len(conflicts), "added": len(additions)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = parser.parse_args(argv)

    register = storage.load()
    listed = load_list(SOURCE)
    conflicts, additions = plan(register, listed)

    print(f"Source   : {SOURCE.name}  ({len(listed)} unique rows)")
    print(f"Register : {len(register.chargers)} chargers, {len(register.conflicts)} conflicts\n")

    print(f"CONFLICTS TO OPEN: {len(conflicts)}")
    opposed = 0
    for record, reading, existing in conflicts:
        sides = {eligibility(existing["MID Status"]), eligibility(reading.status)}
        mark = ""
        if "not eligible" in sides and {"eligible", "eligible-check"} & sides:
            mark = "  ** OPPOSED **"
            opposed += 1
        print(f"  {existing['ID']}  {existing['Brand']} {existing['Model'][:34]:36}"
              f" register={existing['MID Status']:10} list={record['verdict']:9}"
              f"->{reading.status:10}{mark}")
    print(f"  ({opposed} opposed — one side says eligible, the other does not)\n")

    print(f"MODELS TO ADD: {len(additions)}")
    print("  " + str(dict(Counter(r.status for _, r in additions))))

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    result = apply(register, conflicts, additions)
    storage.save(register)
    after = storage.load()
    print(f"\nWritten. Chargers {len(after.chargers)}, conflicts {len(after.conflicts)}, "
          f"change log {len(after.change_log)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
