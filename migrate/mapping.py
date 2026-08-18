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

import re
from dataclasses import dataclass

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

#: A separate external meter is fitted or offered.
#:
#: Anchored to MID like the optional patterns. "Sense reads consumption from the
#: site's EXISTING external utility/smart meter" describes a household utility
#: meter used to throttle output — it is not a MID meter on the charge point, and
#: an unanchored /external.*meter/ read it as External.
EXTERNAL_PATTERNS: tuple[str, ...] = (
    r"\bexternal\b[^.|]{0,60}\bMID\b",
    r"\bMID\b[^.|]{0,60}\bexternal\b",
    r"\bexternal\s+(?:MID[\s-]*)?(?:energy\s+|power\s+|kWh\s+|DIN[\s-]?rail\s+)?meter\b",
    r"\bseparate\s+MID\b",
    r"\bmay\s+be\s+separate\b",
)

#: Available as a variant, an option, or a distinct SKU.
#:
#: These are anchored to a MID reference on purpose. A bare "variant" matches
#: "wall-mounted variant of Business Solo/Duo" and "socket variant", which are
#: product-line language and say nothing about metering; requiring MID within a
#: clause of the option word keeps those rows Integrated. [^.|] stops a match
#: from crossing a sentence break or the ' | ' separator the seed notes use.
OPTIONAL_PATTERNS: tuple[str, ...] = (
    r"\bMID\b[^.|]{0,40}\b(?:optional|option|variant|version)\b",
    r"\b(?:optional|option|variant|version)\b[^.|]{0,40}\bMID\b",
    r"\bwith\s*/?\s*without\s+MID\b",
    r"\bmodel\s+ends\s+in\b",
    r"\bseparate\s+SKU\b",
    r"\bdepend(?:s|ing)?\s+on\b[^.|]{0,30}\b(?:variant|option|serial)\b",
)

#: German calibration law. Related to, but NOT, MID — it is a separate regime and
#: must never be read as evidence of 2014/32/EU conformity.
EICHRECHT_PATTERNS: tuple[str, ...] = (
    r"\beichrecht",
    r"\bPTB\b",
    r"\bBAM\b",
    r"\bkalibrier",
)

@dataclass(frozen=True)
class Mapping:
    status: str
    rule: str
    """Human-readable justification, written into the Change Log and Review Needed."""
    eichrecht: bool = False


def _matches(patterns: tuple[str, ...], text: str) -> str | None:
    """First match of any pattern, ignoring position."""
    for pattern in patterns:
        found = re.search(pattern, text, re.IGNORECASE)
        if found:
            return found.group(0)
    return None


_MID_REFERENCE = re.compile(r"\bMID\b|2014/32/EU|\bMI-?003\b", re.IGNORECASE)

#: Words that flip the meaning of an optionality phrase in the same clause.
#: "No MID in any variant" and "no meter option at all" are rejections, not
#: options — without this they migrate to Optional and the register would claim
#: a customer qualifies when the note says the opposite.
_NEGATORS = re.compile(r"\b(?:no|not|never|geen|zonder|nooit)\b|\bnon[- ]?MID\b", re.IGNORECASE)

#: "available with/without MID" is the definition of Optional, so the "without"
#: in it must not be read as a negation.
_WITH_OR_WITHOUT = re.compile(r"\bwith\s*/?\s*(?:or\s+)?without\b", re.IGNORECASE)

#: A source positively ruling MID out.
_STRONG_NEGATIVE = re.compile(
    r"\bno\s+(?:built[- ]?in\s+)?MID\b"
    r"|\bno\s+MID\s+(?:meter|certification)\b"
    r"|\bnot\s+MID[\s-]*certified\b"
    r"|\bno\s+mention\s+of\s+MID\b"
    r"|\bnot\s+ERE[- ]eligible\b"
    r"|\bno\s+certified\s+meter\b"
    r"|\bnon[- ]?MID\b",
    re.IGNORECASE,
)

#: A negative specifically about a meter *inside* the unit. It is compatible with
#: an external MID meter — "No built-in MID; external accessory option" is an
#: External row, not a rejection — so it must not downgrade an External result.
_BUILT_IN_NEGATIVE = re.compile(r"\bno\s+(?:built[- ]?in|integrated|internal)\b", re.IGNORECASE)

#: Clause boundaries. The seed notes separate assertions with ' | ', ';' and '--',
#: and a negation does not carry across one: in "No built-in MID; external
#: accessory option" the 'No' governs the built-in meter, not the accessory.
_CLAUSE_BREAK = re.compile(r"\||;|--|—")

#: The word inside a match that carries its meaning. Negation is judged relative
#: to this word, not to the start of the match, because the patterns are anchored
#: on 'MID' which often sits in the previous clause.
_CARRIER = re.compile(r"external|separate|optional|option|variant|version|SKU|without|ends", re.IGNORECASE)

#: How far back to look for a negator — one clause, not the whole note.
_NEGATION_WINDOW = 30


def _find(patterns: tuple[str, ...], text: str) -> list[tuple[int, str]]:
    """All matches of any pattern, as (start offset, matched text)."""
    found = []
    for pattern in patterns:
        for hit in re.finditer(pattern, text, re.IGNORECASE):
            found.append((hit.start(), hit.group(0)))
    return sorted(found)


def _is_negated(text: str, offset: int, matched: str) -> bool:
    """True when a negator governs the meaning-carrying word of the match."""
    carrier = _CARRIER.search(matched)
    if carrier:
        offset += carrier.start()
    window = text[max(0, offset - _NEGATION_WINDOW):offset]
    window = _CLAUSE_BREAK.split(window)[-1]      # stay inside the clause
    if _WITH_OR_WITHOUT.search(window):
        return False
    return bool(_NEGATORS.search(window))


def _classify(patterns: tuple[str, ...], text: str) -> tuple[str | None, bool]:
    """Return (affirmative match, saw_negated_match)."""
    saw_negated = False
    for offset, matched in _find(patterns, text):
        if _is_negated(text, offset, matched):
            saw_negated = True
        else:
            return matched, saw_negated
    return None, saw_negated


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
