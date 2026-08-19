"""Mapping the old Yes/No/Maybe seed vocabulary onto the five MID statuses.

Why this is not a lookup table
------------------------------
The seed data came from Zeres's own laadpaal-check list, which only ever
recorded "does this have a MID meter" as Yes / No / Maybe. The register needs
the finer distinction between Integrated, Optional and External, because
Optional and External are *eligible* — the customer qualifies, someone just has
to check the physical unit.

Taking the seed value at face value gets this wrong in both directions. In the
source data, 20 rows marked "No" and 11 marked "Yes" carry note text describing
an optional or external MID meter. For example, Wallbox Commander 2S is seeded
"No" while its note reads "No built-in MID; external accessory option ...
official datasheet explicitly lists 'MID Meter'". That row is External, not
None. Migrating it as None would tell a paying customer they cannot book their
kWh into the REV when in fact they can.

So the note text overrides the seed value, and every migrated row is flagged for
review regardless — see migrate_tracker.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.evidence import (
    _BUILT_IN_NEGATIVE,
    _classify,
    _matches,
    _MID_REFERENCE,
    _STRONG_NEGATIVE,
    EICHRECHT_PATTERNS,
    EXTERNAL_PATTERNS,
    OPTIONAL_PATTERNS,
)

#: Seed value -> starting point, before the notes are consulted.
BASE_MAP: dict[str, str] = {
    "Yes": "Integrated",
    "No": "None",
    "Maybe": "Optional",      # the source Read Me defines Maybe as
                              # "depends on variant/option/serial number",
                              # which is precisely what Optional means here.
    "Unknown": "Unknown",
    "N/A": "Unknown",         # mostly non-EU market rows; not established for us
    "": "Unknown",            # absence of evidence is Unknown, never None
}


@dataclass(frozen=True)
class Mapping:
    status: str
    rule: str
    """Human-readable justification, written into the Change Log and Review Needed."""
    eichrecht: bool = False


def map_status(seed_value: object, notes: object = "", source: object = "") -> Mapping:
    """Map one seed row onto the five-value vocabulary.

    The seed value sets the starting point; the note text can move it. Movement
    is towards a *more precise* answer (Integrated/None -> Optional/External) or
    towards Unknown. Nothing here invents a rejection: a row only becomes None if
    the seed data already said No and the notes did not contradict it.

    Where seed and notes disagree the result is Unknown, not a guess. Unknown
    means "needs research", which is honest; picking a side would either book
    kWh that should not be booked or refuse a customer who qualifies.
    """
    seed = str(seed_value or "").strip()
    base = BASE_MAP.get(seed, "Unknown")
    evidence = f"{notes or ''}\n{source or ''}"

    eichrecht_hit = _matches(EICHRECHT_PATTERNS, evidence)
    status, rule = base, f"seed value {seed or '(blank)'!r} mapped directly"

    external_hit, external_negated = _classify(EXTERNAL_PATTERNS, evidence)
    optional_hit, optional_negated = _classify(OPTIONAL_PATTERNS, evidence)

    if external_hit:
        status = "External"
        rule = f"notes describe a separate external MID meter ({external_hit.strip()!r})"
    elif optional_hit:
        status = "Optional"
        rule = f"notes describe a MID option or variant ({optional_hit.strip()!r})"
    elif external_negated or optional_negated:
        # The notes discuss MID optionality only to rule it out.
        if base == "None":
            rule = "seed value 'No', and the notes confirm no MID option is offered"
        else:
            status = "Unknown"
            rule = (
                f"seed value {seed!r} but the notes rule out the MID option they mention — "
                f"seed and notes disagree, so this is not established"
            )

    # A source that positively rules MID out, against a status that claims it.
    # "No built-in MID" is exempted for External rows: it is exactly what an
    # External row says about itself, and downgrading on it would erase the
    # distinction between "no meter inside" and "no MID meter anywhere".
    strong = _STRONG_NEGATIVE.search(evidence)
    if strong and status in {"Integrated", "Optional", "External"}:
        builtin_only = status == "External" and _BUILT_IN_NEGATIVE.search(strong.group(0))
        if not builtin_only:
            status = "Unknown"
            rule = (
                f"seed value {seed or '(blank)'!r} but the notes state {strong.group(0).strip()!r} — "
                f"the evidence points both ways, so this is not established"
            )

    # Eichrecht guard. German calibration law is a different regime; a row whose
    # only metrology language is Eichrecht has NOT been shown to be MID. Downgrade
    # to Unknown — but only from an eligible status, because a seed 'No' is a
    # positive assertion that we should not soften into "needs research".
    if eichrecht_hit and status in {"Integrated", "Optional", "External"}:
        if not _MID_REFERENCE.search(evidence):
            status = "Unknown"
            rule = (
                f"only Eichrecht/PTB language found ({eichrecht_hit.strip()!r}) and no MID "
                f"reference — German calibration law is a separate regime, not MID evidence"
            )

    return Mapping(status=status, rule=rule, eichrecht=bool(eichrecht_hit))
