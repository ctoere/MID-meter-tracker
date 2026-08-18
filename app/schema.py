"""Sheet schemas and the MID status vocabulary.

The workbook is the database. Everything that knows a column name knows it
from here, so that adding a column is a one-line change and a typo in a
column name is a test failure rather than a silently empty cell.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# MID status vocabulary — five values, no others.
#
# The commercial meaning of each value is the whole point of this tool, so it
# is encoded here rather than left to the UI:
#
#   Integrated  MID meter built in as standard        -> eligible as sold
#   Optional    available as a variant or paid option -> ELIGIBLE, verify the unit
#   External    uses a separate external MID meter    -> ELIGIBLE, verify the unit
#   None        no MID metering                       -> not eligible as sold
#   Unknown     not established                       -> needs research
#
# Optional and External are NOT rejections. Collapsing either into None tells a
# paying customer they do not qualify for the ERE when in fact they do — the
# most expensive mistake this codebase can make. See ELIGIBLE_STATUSES below and
# the domain rules in CLAUDE.md.
# --------------------------------------------------------------------------

MID_STATUSES: tuple[str, ...] = ("Integrated", "Optional", "External", "None", "Unknown")

#: Statuses that mean the charge point can be booked into the REV in some form.
ELIGIBLE_STATUSES: frozenset[str] = frozenset({"Integrated", "Optional", "External"})

#: Statuses that mean "eligible, but the individual unit must be checked".
CHECK_UNIT_STATUSES: frozenset[str] = frozenset({"Optional", "External"})

#: One-line commercial consequence, shown beside every status in the UI so the
#: colour is never the only carrier of meaning.
ELIGIBILITY_TEXT: dict[str, str] = {
    "Integrated": "eligible as sold",
    "Optional": "eligible — check the individual unit",
    "External": "eligible if an external MID meter is fitted",
    "None": "not eligible as sold",
    "Unknown": "not established",
}

#: Absence of evidence is Unknown, never None.
DEFAULT_STATUS = "Unknown"


class StatusVocabularyError(ValueError):
    """Raised when a value outside the five-term vocabulary reaches the register."""


def validate_status(value: object) -> str:
    """Return ``value`` if it is one of the five statuses, else raise.

    Empty/missing is deliberately NOT coerced to ``None`` (the status) — an
    unset status is ``Unknown``.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return DEFAULT_STATUS
    if text not in MID_STATUSES:
        raise StatusVocabularyError(
            f"{text!r} is not a MID status. Allowed: {', '.join(MID_STATUSES)}"
        )
    return text


def is_eligible(status: object) -> bool:
    """True when the status means the charge point qualifies in some form."""
    return str(status or "").strip() in ELIGIBLE_STATUSES


# --------------------------------------------------------------------------
# Sheets. Column order is part of the contract: a load/save round trip must not
# reorder columns, so these tuples are the authority on order.
# --------------------------------------------------------------------------

SHEET_READ_ME = "Read Me"
SHEET_CHARGERS = "Chargers"
SHEET_METERS = "Meters"
SHEET_CONFLICTS = "Conflicts"
SHEET_MANIFEST = "Manifest"
SHEET_CHANGE_LOG = "Change Log"

CHARGER_COLUMNS: tuple[str, ...] = (
    "ID",                # stable, chg_0001 — never renumbered, never reused
    "Brand",
    "Model",
    "Charge Type",
    "Max kW",
    "MID Status",
    "Meter Brand",
    "Meter Model",
    "Datasheet Link",
    "Certificate Link",
    "Drive Folder",
    "Research Status",
    "Source",
    "In Tracker",
    "In Zite",
    "Conflict",
    "Review Needed",     # non-empty => NOT safe to quote to a client
    "Notes (EN)",
    "Notes (NL)",
)

METER_COLUMNS: tuple[str, ...] = (
    "ID",                # mtr_0001
    "Brand",
    "Model",
    "MID Status",
    "Datasheet Link",
    "Certificate Link",
    "Drive Folder",
    "Research Status",
    "Source",
    "Review Needed",
    "Notes",
)

CONFLICT_COLUMNS: tuple[str, ...] = (
    "ID",                # cfl_0001
    "Charger ID",
    "Brand",
    "Model",
    "Tracker says",
    "Tracker note",
    "Zite says",
    "Zite original value",
    "Zite note",
    "Decision",          # empty while open
    "Decided By",
    "Decided At",
)

MANIFEST_COLUMNS: tuple[str, ...] = (
    "Brand",
    "Model",
    "SubFolder",         # backslashes, mirrors the Drive tree below Technical\
    "Url",               # legitimately empty for hand-filed datasheets
    "Filename",
)

CHANGE_LOG_COLUMNS: tuple[str, ...] = (
    "Timestamp",
    "User",
    "Row ID",
    "Field",
    "Old Value",
    "New Value",
    "Reason",            # required when Field is "MID Status"
)

#: Sheets this app owns and rewrites on save. Any other sheet in the workbook
#: (Read Me, and anything a colleague adds by hand) is carried through untouched.
MANAGED_SHEETS: dict[str, tuple[str, ...]] = {
    SHEET_CHARGERS: CHARGER_COLUMNS,
    SHEET_METERS: METER_COLUMNS,
    SHEET_CONFLICTS: CONFLICT_COLUMNS,
    SHEET_MANIFEST: MANIFEST_COLUMNS,
    SHEET_CHANGE_LOG: CHANGE_LOG_COLUMNS,
}

#: ID prefixes per sheet.
ID_PREFIX: dict[str, str] = {
    SHEET_CHARGERS: "chg",
    SHEET_METERS: "mtr",
    SHEET_CONFLICTS: "cfl",
}
