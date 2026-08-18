"""Conflicts — rows where the two old source systems disagreed.

The research tracker and the Zite dashboard were maintained separately, and where
they disagree the answer a client got depended on which one the helpdesk happened
to open. Each disagreement needs a human decision.

Nothing in this module resolves a conflict on its own. There is no "prefer the
newer source" rule, no tie-break, no bulk apply — a person picks a side and says
why, and that reasoning goes into the Change Log.
"""

from __future__ import annotations

from typing import Any

from . import changelog, domain, schema

Row = dict[str, Any]


class ConflictError(ValueError):
    """The conflict cannot be resolved as asked."""


def sides(conflict: Row) -> tuple[str, str]:
    """(what the tracker says, what Zite says)."""
    return (str(conflict.get("Tracker says", "") or "").strip(),
            str(conflict.get("Zite says", "") or "").strip())


def is_opposed(conflict: Row) -> bool:
    """True when one source says eligible and the other says None.

    These are the serious ones. A disagreement between Integrated and Optional is
    a precision problem; a disagreement between Optional and None decides whether
    a customer was told yes or no.
    """
    tracker, zite = sides(conflict)
    return ((schema.is_eligible(tracker) and zite == "None") or
            (schema.is_eligible(zite) and tracker == "None"))


def is_open(conflict: Row) -> bool:
    return str(conflict.get("Decision", "") or "").strip() == ""


def summarise(conflict_rows: list[Row]) -> dict[str, int]:
    open_rows = [c for c in conflict_rows if is_open(c)]
    return {
        "total": len(conflict_rows),
        "open": len(open_rows),
        "resolved": len(conflict_rows) - len(open_rows),
        "opposed": sum(1 for c in conflict_rows if is_opposed(c)),
        "opposed_open": sum(1 for c in open_rows if is_opposed(c)),
    }


def find_charger(chargers: list[Row], conflict: Row) -> Row | None:
    """The register row a conflict refers to.

    Prefers the explicit Charger ID; falls back to brand+model for conflict rows
    written before IDs existed.
    """
    charger_id = str(conflict.get("Charger ID", "") or "").strip()
    if charger_id:
        match = next((r for r in chargers if r.get("ID") == charger_id), None)
        if match:
            return match

    brand = str(conflict.get("Brand", "") or "").strip().casefold()
    model = str(conflict.get("Model", "") or "").strip().casefold()
    if not brand or not model:
        return None
    return next((r for r in chargers
                 if str(r.get("Brand", "")).strip().casefold() == brand
                 and str(r.get("Model", "")).strip().casefold() == model), None)


def resolve(register, conflict_id: str, decision: str, reason: str,
            user: str | None = None) -> dict:
    """Apply a human's decision to a conflict.

    Writes the chosen status onto the charger row, clears the row's Conflict
    marker, stamps the conflict with who decided and when, and logs both the
    status change and the resolution.

    'Review Needed' is deliberately NOT cleared. Resolving a source disagreement
    is not the same as verifying the row against a primary source, and those
    flags usually say something else entirely (most say the row came from the
    unverified seed import). Clearing it here would silently mark rows as safe to
    quote that nobody has checked.
    """
    conflict = next((c for c in register.conflicts if c.get("ID") == conflict_id), None)
    if conflict is None:
        raise ConflictError(f"No conflict {conflict_id}")
    if not is_open(conflict):
        raise ConflictError(
            f"Conflict {conflict_id} was already decided by {conflict.get('Decided By')} "
            f"on {conflict.get('Decided At')}. Reopen it by clearing the Decision column."
        )

    decision = schema.validate_status(decision)
    reason = str(reason or "").strip()
    if not reason:
        raise ConflictError(
            "Resolving a conflict requires a reason — which source you followed and why. "
            "This is the record an NEa audit would ask for."
        )

    charger = find_charger(register.chargers, conflict)
    if charger is None:
        raise ConflictError(
            f"Conflict {conflict_id} points at {conflict.get('Brand')} {conflict.get('Model')}, "
            f"which is not in the register. Add the charger row first."
        )

    tracker, zite = sides(conflict)
    if decision == tracker == zite:
        chose = "both sources"
    elif decision == tracker:
        chose = "the research tracker"
    elif decision == zite:
        chose = "Zite"
    else:
        chose = "neither source"
    full_reason = f"Conflict {conflict_id} resolved in favour of {chose} ({decision}). {reason}"

    changes = []
    if str(charger.get("MID Status", "")).strip() != decision:
        changes.append(("MID Status", str(charger.get("MID Status", "")).strip(), decision))
    if str(charger.get("Conflict", "")).strip():
        changes.append(("Conflict", str(charger.get("Conflict", "")).strip(), ""))

    who = user or domain.current_user()
    if changes:
        changelog.record(register.change_log, charger["ID"], changes, full_reason, who)

    charger["MID Status"] = decision
    charger["Conflict"] = ""
    charger["Notes (EN)"] = domain.append_note(
        charger.get("Notes (EN)"),
        f"[conflict {conflict_id} resolved {domain.now_stamp()[:10]} by {who}] "
        f"Tracker said {tracker or '(blank)'}, Zite said {zite or '(blank)'}; "
        f"followed {chose} — {decision}. {reason}")

    conflict["Decision"] = decision
    conflict["Decided By"] = who
    conflict["Decided At"] = domain.now_stamp()

    changelog.record(register.change_log, conflict_id,
                     [("Decision", "", decision)], full_reason, who)

    return {"conflict": conflict, "charger": charger, "changes": changes}
