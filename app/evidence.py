"""Shared reading of evidence text: is a MID meter standard, optional, or external?

Both the one-time seed migration and the intake pipeline have to answer the same
question from free text, so the patterns live here rather than in either of them.
Encoding "what counts as an optional MID meter" twice is how the two drift apart.

The hard-won details are in the comments below; briefly:
  - every pattern is anchored to a MID reference, because a bare "variant" matches
    product-line language like "wall-mounted variant"
  - negation is judged at the meaning-carrying word and does not cross a clause
    boundary, because "No built-in MID; external accessory option" is an External
    row while "No MID in any variant" is a rejection
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Any reference to MID metrology, used to anchor the optionality patterns.
#: "MI-003 meter available as an option" is an option on a MID meter just as much
#: as "MID meter optional" is — anchoring on the literal word alone missed it.
_ANCHOR = r"(?:\bMID\b|\bMI[\s\-]?003\b|\b2014\s?/\s?32\s?/\s?EU\b)"

#: A separate external meter is fitted or offered.
#:
#: Anchored to MID like the optional patterns. "Sense reads consumption from the
#: site's EXISTING external utility/smart meter" describes a household utility
#: meter used to throttle output — it is not a MID meter on the charge point, and
#: an unanchored /external.*meter/ read it as External.
EXTERNAL_PATTERNS: tuple[str, ...] = (
    r"\bexternal\b[^.|]{0,60}" + _ANCHOR,
    _ANCHOR + r"[^.|]{0,60}\bexternal\b",
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
    _ANCHOR + r"[^.|]{0,40}\b(?:optional|option|variant|version)\b",
    r"\b(?:optional|option|variant|version)\b[^.|]{0,40}" + _ANCHOR,
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

#: Text that refers to MID metrology at all.
_MID_REFERENCE = re.compile(r"\bMID\b|2014/32/EU|\bMI-?003\b", re.IGNORECASE)

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




def _matches(patterns: tuple[str, ...], text: str) -> str | None:
    """First match of any pattern, ignoring position."""
    for pattern in patterns:
        found = re.search(pattern, text, re.IGNORECASE)
        if found:
            return found.group(0)
    return None


@dataclass(frozen=True)
class Optionality:
    """How a piece of text describes the availability of a MID meter."""
    kind: str          # "external" | "optional" | "negated" | "none"
    matched: str = ""

    @property
    def affirmative(self) -> bool:
        return self.kind in {"external", "optional"}


def classify_optionality(text: str) -> Optionality:
    """Read text for an affirmative or negated MID option / external meter."""
    external, external_negated = _classify(EXTERNAL_PATTERNS, text)
    optional, optional_negated = _classify(OPTIONAL_PATTERNS, text)
    if external:
        return Optionality("external", external)
    if optional:
        return Optionality("optional", optional)
    if external_negated or optional_negated:
        return Optionality("negated")
    return Optionality("none")


def find_eichrecht(text: str) -> str | None:
    """German calibration law markings. Related to MID, but a separate regime."""
    return _matches(EICHRECHT_PATTERNS, text)


def has_mid_reference(text: str) -> bool:
    return bool(_MID_REFERENCE.search(text))


def find_strong_negative(text: str):
    return _STRONG_NEGATIVE.search(text)


def is_built_in_negative(text: str) -> bool:
    return bool(_BUILT_IN_NEGATIVE.search(text))


def is_negated(text: str, offset: int, matched: str) -> bool:
    """Public wrapper: is this match governed by a negator in its own clause?"""
    return _is_negated(text, offset, matched)
