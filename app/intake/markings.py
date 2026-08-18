"""Detecting actual metrology markings in extracted document text.

The whole value of this module is what it REFUSES to conclude.

A CE mark is not MID evidence. Every electrical product sold in the EU carries
CE; it covers safety and EMC, not metrology. Reading CE as MID is the single most
common false positive on this job, so CE is detected explicitly and recorded as
*not* evidence, precisely so the UI can show that it was seen and discounted.

Accuracy Class 1 / Class 2 under IEC 62053 is the older, non-MID scheme. Classes
A / B / C under EN 50470-3 are the MID ones. Confusing them turns an uncertified
meter into a certified one.

Eichrecht / PTB / BAM is German calibration law — related to MID, but a separate
regime. It is recorded in its own right and never counted as MID evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import evidence


@dataclass
class Marking:
    kind: str
    matched: str          # the exact text that matched
    detail: str           # what it means, in plain language
    sentence: str = ""    # the sentence it was found in, quoted verbatim
    is_mid_evidence: bool = False


@dataclass
class Findings:
    markings: list[Marking] = field(default_factory=list)
    optionality: evidence.Optionality = field(default_factory=lambda: evidence.Optionality("none"))

    def of_kind(self, kind: str) -> list[Marking]:
        return [m for m in self.markings if m.kind == kind]

    @property
    def mid_evidence(self) -> list[Marking]:
        return [m for m in self.markings if m.is_mid_evidence]

    @property
    def has_mid_evidence(self) -> bool:
        return bool(self.mid_evidence)

    @property
    def ce_only(self) -> bool:
        """CE seen, and nothing metrological anywhere. The classic false positive."""
        return bool(self.of_kind("ce")) and not self.has_mid_evidence

    @property
    def eichrecht_only(self) -> bool:
        return bool(self.of_kind("eichrecht")) and not self.has_mid_evidence


# --------------------------------------------------------------------------
# patterns
# --------------------------------------------------------------------------

#: Supplementary metrology marking: 'M' plus the two-digit year it was affixed,
#: normally inside a rectangle. Text extraction loses the rectangle, so the year
#: is bounded to a plausible range to avoid matching dimensions like "M 12 bolt".
_M_MARKING = re.compile(r"\bM\s?[-–]?\s?([0-9]{2})\b")
_PLAUSIBLE_YEARS = range(4, 41)          # MID applied from 2004; allow a margin

#: A four-digit notified body number, normally immediately after the M marking.
_NOTIFIED_BODY_AFTER_M = re.compile(r"\bM\s?[-–]?\s?[0-9]{2}\s*[-–]?\s*([0-9]{4})\b")
_NOTIFIED_BODY_NAMED = re.compile(
    r"\b(?:notified\s+body|aangemelde\s+instantie|benannte\s+stelle)\b[^.\n]{0,40}?\b([0-9]{4})\b",
    re.IGNORECASE)

_MI_003 = re.compile(r"\bMI[\s\-–]?003\b", re.IGNORECASE)
_DIRECTIVE = re.compile(r"\b2014\s?/\s?32\s?/\s?EU\b", re.IGNORECASE)

_EN_50470 = re.compile(r"\bEN\s?50470(?:\s?[-–]\s?[13])?\b", re.IGNORECASE)
_EN_CLASS = re.compile(r"\b(?:accuracy\s+)?class\s+([ABC])\b", re.IGNORECASE)

#: The OLDER, non-MID scheme. Detected so it can be shown and discounted.
_IEC_62053 = re.compile(r"\bIEC\s?62053(?:\s?[-–]\s?\d+)?\b", re.IGNORECASE)
_IEC_CLASS = re.compile(r"\bclass\s+([12])\b", re.IGNORECASE)

_MID_PHRASE = re.compile(
    r"\bMID[\s\-–]?(?:certified|certificate|gecertificeerd|compliant|conform\w*|approved)\b"
    r"|\bgecertificeerde?\s+MID\b|\bMID[\s\-–]?meter\b|\bMID\b",
    re.IGNORECASE)

#: Never MID evidence. Detected so the UI can say "CE seen, and discounted".
_CE = re.compile(r"\bCE[\s\-–]?(?:mark|marking|marked|conformity)\b|(?<![A-Za-z])CE(?![A-Za-z])")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}|\r?\n(?=[A-Z•\-–])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def _sentence_for(text: str, offset: int) -> str:
    """The sentence containing ``offset``, quoted verbatim.

    Claims have to be traceable, so the proposal shows the source's own wording
    rather than a paraphrase.
    """
    position = 0
    for sentence in sentences(text):
        found = text.find(sentence, position)
        if found == -1:
            continue
        if found <= offset < found + len(sentence):
            return " ".join(sentence.split())
        position = found + len(sentence)
    window = text[max(0, offset - 90):offset + 90]
    return " ".join(window.split())


def detect(text: str) -> Findings:
    """Find every metrology marking in ``text`` and say which ones are MID evidence."""
    text = text or ""
    found = Findings()

    def add(kind, match, detail, is_evidence):
        # A marking inside a negation is not evidence of that marking. "This model
        # has no MID meter" contains the word MID, and reading it as a MID claim
        # would book kWh into the REV on the strength of a sentence saying the
        # opposite — the costliest direction to get this wrong.
        if is_evidence and evidence.is_negated(text, match.start(), match.group(0)):
            is_evidence = False
            detail = f"negated in the source — {detail}"
        found.markings.append(Marking(kind, match.group(0).strip(), detail,
                                      _sentence_for(text, match.start()), is_evidence))

    # M-marking plus, where present, the notified body immediately after it.
    seen_bodies: set[str] = set()
    for match in _M_MARKING.finditer(text):
        year = int(match.group(1))
        if year not in _PLAUSIBLE_YEARS:
            continue
        add(match=match, kind="metrology_m", is_evidence=True,
            detail=f"supplementary metrology marking — affixed in 20{match.group(1)}")
    for match in _NOTIFIED_BODY_AFTER_M.finditer(text):
        seen_bodies.add(match.group(1))
        add(match=match, kind="notified_body", is_evidence=True,
            detail=f"notified body {match.group(1)}, following the M marking")
    for match in _NOTIFIED_BODY_NAMED.finditer(text):
        if match.group(1) in seen_bodies:
            continue
        seen_bodies.add(match.group(1))
        add(match=match, kind="notified_body", is_evidence=True,
            detail=f"notified body {match.group(1)}")

    for match in _MI_003.finditer(text):
        add(match=match, kind="mi_003", is_evidence=True,
            detail="MID category for active electrical energy meters")
    for match in _DIRECTIVE.finditer(text):
        add(match=match, kind="directive", is_evidence=True,
            detail="the Measuring Instruments Directive itself")

    # Accuracy class only counts as MID when the MID standard is what is cited.
    has_en_50470 = bool(_EN_50470.search(text))
    for match in _EN_50470.finditer(text):
        add(match=match, kind="en_50470", is_evidence=True,
            detail="EN 50470 — the MID standard for electricity meters")
    for match in _EN_CLASS.finditer(text):
        add(match=match, kind="accuracy_class", is_evidence=has_en_50470,
            detail=(f"accuracy class {match.group(1).upper()} under EN 50470-3"
                    if has_en_50470 else
                    f"accuracy class {match.group(1).upper()} claimed, but EN 50470 is not cited"))

    for match in _IEC_62053.finditer(text):
        add(match=match, kind="iec_62053", is_evidence=False,
            detail="IEC 62053 — the OLDER, non-MID accuracy scheme")
    if _IEC_62053.search(text):
        for match in _IEC_CLASS.finditer(text):
            add(match=match, kind="iec_class", is_evidence=False,
                detail=f"class {match.group(1)} under IEC 62053 — not the MID scheme")

    for match in _MID_PHRASE.finditer(text):
        add(match=match, kind="mid_phrase", is_evidence=True, detail="explicit MID wording")

    hit = evidence.find_eichrecht(text)
    if hit:
        match = re.search(re.escape(hit), text, re.IGNORECASE)
        if match:
            add(match=match, kind="eichrecht", is_evidence=False,
                detail="German calibration law — a separate regime, not MID")

    for match in _CE.finditer(text):
        add(match=match, kind="ce", is_evidence=False,
            detail="CE covers safety and EMC, not metrology — never MID evidence")

    found.optionality = evidence.classify_optionality(text)
    return found
