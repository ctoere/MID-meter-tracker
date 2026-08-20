"""Turning extracted text into a PROPOSED register row.

Nothing here is applied. Every proposal is shown as a diff against the current
row with the exact sentence that supports it, and a person clicks apply.

The rules that decide a status are the expensive ones to get wrong:

  - CE alone is never MID. A document mentioning CE but carrying no metrology
    marking proposes Unknown, not Integrated and not None.
  - A photo of a charger's exterior nameplate is not evidence of absence. On most
    wallboxes the meter sits behind the cover, so the outside plate carries no
    metrology marking either way. An exterior photo can only ever propose
    Unknown — never None, no matter what is missing from it.
  - A declaration of conformity that does not cite 2014/32/EU is not MID evidence
    at all, however official it looks.
  - Eichrecht / PTB is recorded, never counted.
  - None is proposed only when a source positively rules MID out. Absence of
    evidence is Unknown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .. import evidence, schema
from . import markings as markings_mod

Row = dict[str, Any]

#: What surface a photo shows. Only the meter's own face can carry a marking.
SURFACE_EXTERIOR = "exterior"       # the enclosure / outside nameplate
SURFACE_METER = "meter"             # the meter itself, cover removed
SURFACE_UNKNOWN = "unsure"

_CERT_NUMBER = re.compile(
    r"\b(?:certificate|certificaat|zertifikat|type[\s-]?examination|EU[\s-]?type)\b"
    r"[^\n:]{0,30}[:\s]\s*([A-Z]{1,4}[\-\s]?[A-Z0-9][A-Z0-9\-./]{2,24})", re.IGNORECASE)
_CERT_LOOSE = re.compile(r"\b(T\d{4,6}|DE-\d{2}-MI\d{3}-[A-Z0-9]+|[A-Z]{2}\d{2}-MI\d{3}-[A-Z0-9]+)\b")

#: Notified bodies that actually issue MID electricity-meter certificates.
_BODIES = re.compile(r"\b(NMi(?:\s+Certin)?|PTB|DEKRA|T[ÜU]V\s?(?:Rheinland|S[ÜU]D|NORD)?|"
                     r"SGS|Bureau\s+Veritas|METAS|RISE|Cesi|IMQ|LNE)\b", re.IGNORECASE)
#: Markers of a NON-EU conformity regime. These matter because a UKCA or US
#: declaration reads almost exactly like an EU one — same layout, same
#: "declaration of conformity" heading, often the same product — while resting
#: on an entirely different legal framework. Great Britain replaced the MID with
#: its own Measuring Instruments Regulations 2016; the US uses NTEP certificates
#: against NIST Handbook 44. Neither has any standing with the NEa.
#:
#: Only 2014/32/EU makes a declaration usable for the REV. These patterns exist
#: so a non-EU document is named as such instead of being quietly filed as
#: "no directive found".
NON_EU_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bUKCA\b", "UKCA marking — Great Britain, not the EU"),
    (r"\bUK\s+Conformity\s+Assessed\b", "UK Conformity Assessed — not the EU"),
    (r"\bMeasuring\s+Instruments\s+Regulations\s+2016\b",
     "UK Measuring Instruments Regulations 2016 — Great Britain's replacement for the MID"),
    (r"\bS\.?I\.?\s*2016/1153\b", "UK statutory instrument 2016/1153, not 2014/32/EU"),
    (r"\bUK\s+Approved\s+Body\b", "UK Approved Body, not an EU notified body"),
    (r"\bGreat\s+Britain\b(?![^.]{0,40}\bEU\b)", "scoped to Great Britain"),
    (r"\bNTEP\b", "US NTEP certificate — National Type Evaluation Program"),
    (r"\bNIST\s+Handbook\s+44\b", "US NIST Handbook 44, not EN 50470"),
    (r"\bHandbook\s+44\b", "US NIST Handbook 44, not EN 50470"),
    (r"\bNational\s+Type\s+Evaluation\b", "US type evaluation, not EU"),
    (r"\bANSI\s?C12\b", "US ANSI C12 metering standard, not EN 50470"),
    (r"\bCertificate\s+of\s+Conformance\b", "US 'Certificate of Conformance' wording"),
    (r"\bUL\s?2594\b", "UL 2594 — US/Canada EVSE safety standard"),
    (r"\bFCC\b", "US FCC — a United States document"),
    (r"\bCSA\b", "CSA — Canada/US certification"),
)

_MODELS = re.compile(r"\b(?:model|models|type|types|modell|typen|artikel)\b\s*(?:\(s\))?\s*[:\-]\s*([^\n]{3,120})",
                     re.IGNORECASE)


@dataclass
class DocDetails:
    """What a declaration of conformity actually says."""
    certificate_number: str = ""
    issuing_body: str = ""
    directive_cited: bool = False
    models_covered: list[str] = field(default_factory=list)
    non_eu_markers: list[str] = field(default_factory=list)

    @property
    def is_non_eu(self) -> bool:
        """A UK or US declaration, with no EU directive cited alongside it."""
        return bool(self.non_eu_markers) and not self.directive_cited

    @property
    def is_mid_evidence(self) -> bool:
        return self.directive_cited


@dataclass
class Proposal:
    status: str = schema.DEFAULT_STATUS
    reasoning: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    matched: list[dict] = field(default_factory=list)
    discounted: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    doc: DocDetails | None = None
    fields: Row = field(default_factory=dict)
    diff: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "eligibility": schema.ELIGIBILITY_TEXT[self.status],
            "reasoning": self.reasoning,
            "quotes": self.quotes,
            "matched": self.matched,
            "discounted": self.discounted,
            "warnings": self.warnings,
            "doc": self.doc.__dict__ if self.doc else None,
            "fields": self.fields,
            "diff": self.diff,
        }


def read_doc(text: str) -> DocDetails:
    """Pull the four things that make a DoC meaningful."""
    details = DocDetails()
    match = _CERT_NUMBER.search(text) or _CERT_LOOSE.search(text)
    if match:
        details.certificate_number = match.group(1).strip(" .:-")
    body = _BODIES.search(text)
    if body:
        details.issuing_body = body.group(1).strip()
    details.directive_cited = bool(re.search(r"\b2014\s?/\s?32\s?/\s?EU\b", text, re.IGNORECASE))
    for pattern, explanation in NON_EU_PATTERNS:
        found = re.search(pattern, text, re.IGNORECASE)
        if found and explanation not in details.non_eu_markers:
            details.non_eu_markers.append(explanation)
    for hit in _MODELS.finditer(text):
        value = hit.group(1).strip(" .;")
        if value and value not in details.models_covered:
            details.models_covered.append(value)
    return details


def decide(text: str, kind: str, surface: str = SURFACE_UNKNOWN) -> Proposal:
    """Propose a MID status from a document's text. Never applies anything."""
    found = markings_mod.detect(text or "")
    proposal = Proposal()
    proposal.matched = [
        {"kind": m.kind, "matched": m.matched, "detail": m.detail, "sentence": m.sentence}
        for m in found.mid_evidence]
    proposal.discounted = [
        {"kind": m.kind, "matched": m.matched, "detail": m.detail, "sentence": m.sentence}
        for m in found.markings if not m.is_mid_evidence]
    proposal.quotes = list(dict.fromkeys(m.sentence for m in found.mid_evidence if m.sentence))

    if kind == "doc":
        proposal.doc = read_doc(text or "")

    # ---- photos: what surface, and the rule that follows from it ----------
    if kind == "photo":
        if surface == SURFACE_EXTERIOR:
            proposal.status = "Unknown"
            proposal.reasoning.append(
                "This photo shows the enclosure's exterior nameplate. On most wallboxes the kWh "
                "meter sits behind the cover, so the outside plate carries no metrology marking "
                "either way — its absence proves nothing. Unknown, never None.")
            if found.has_mid_evidence:
                # Markings on the outside are still worth something.
                proposal.reasoning.append(
                    "Metrology markings were found on it even so — see the matches below; "
                    "confirm against the meter itself or the datasheet.")
            return _finish(proposal, found, text)
        if surface != SURFACE_METER:
            proposal.status = "Unknown"
            proposal.reasoning.append(
                "It is not recorded what surface this photo shows. Only the meter's own face can "
                "carry a metrology marking, so nothing can be concluded until that is known.")
            return _finish(proposal, found, text)

    # ---- declarations of conformity --------------------------------------
    # A UK or US declaration first: it looks like an EU one and is the easier
    # mistake to make, so it gets named rather than reported as "no directive".
    if kind == "doc" and proposal.doc and proposal.doc.is_non_eu:
        proposal.status = "Unknown"
        proposal.reasoning.append(
            "This is a UK or US declaration, not an EU one — "
            + "; ".join(proposal.doc.non_eu_markers) + ". "
            "Great Britain and the United States run their own conformity regimes, and neither "
            "has standing with the NEa. Only a declaration citing 2014/32/EU supports an ERE "
            "eligibility claim. File it if it is useful, but it cannot back a MID status.")
        proposal.warnings.append("Non-EU declaration — cannot be used as MID evidence")
        return _finish(proposal, found, text)

    if kind == "doc" and proposal.doc and not proposal.doc.directive_cited:
        proposal.status = "Unknown"
        proposal.reasoning.append(
            "This declaration of conformity does not cite Directive 2014/32/EU, so it is not MID "
            "evidence — whatever else it certifies. A DoC covering 'the EVSE' under the Low "
            "Voltage or EMC directives says nothing about metrology.")
        proposal.warnings.append("DoC does not cite 2014/32/EU")
        return _finish(proposal, found, text)

    # ---- positive metrology evidence -------------------------------------
    if found.has_mid_evidence:
        optionality = found.optionality
        if optionality.kind == "external":
            proposal.status = "External"
            proposal.reasoning.append(
                f"MID markings found, and the text describes a separate external meter "
                f"({optionality.matched!r}). Eligible if that meter is actually fitted.")
        elif optionality.kind == "optional":
            proposal.status = "Optional"
            proposal.reasoning.append(
                f"MID markings found, and the text describes an option or variant "
                f"({optionality.matched!r}). Eligible — the individual unit must be checked.")
        else:
            proposal.status = "Integrated"
            proposal.reasoning.append(
                "Metrology markings found and nothing describes the meter as optional or "
                "external, so it reads as fitted as standard.")
        kinds = {m.kind for m in found.mid_evidence}
        proposal.reasoning.append("Matched: " + ", ".join(sorted(kinds)) + ".")
        return _finish(proposal, found, text)

    # ---- no metrology evidence -------------------------------------------
    strong = evidence.find_strong_negative(text or "")
    if strong and not evidence.is_built_in_negative(strong.group(0)):
        proposal.status = "None"
        proposal.reasoning.append(
            f"The document positively rules MID out ({strong.group(0).strip()!r}) and no metrology "
            f"marking appears anywhere.")
        proposal.quotes.append(markings_mod._sentence_for(text, strong.start()))
        return _finish(proposal, found, text)

    proposal.status = "Unknown"
    if found.ce_only:
        proposal.reasoning.append(
            "A CE mark was found and nothing else. CE covers safety and EMC, not metrology — every "
            "electrical product in the EU carries it. This is not evidence of MID either way, so "
            "the status is Unknown, not Integrated and not None.")
    elif found.eichrecht_only:
        proposal.reasoning.append(
            "Only Eichrecht/PTB calibration-law wording was found. German calibration law is a "
            "related but separate regime from Directive 2014/32/EU and does not establish MID.")
    else:
        proposal.reasoning.append(
            "No metrology marking, MID wording or directive reference was found. Absence of "
            "evidence is Unknown — it is not a finding that the meter is uncertified.")
    return _finish(proposal, found, text)


def _finish(proposal: Proposal, found, text: str) -> Proposal:
    if found.of_kind("eichrecht"):
        proposal.warnings.append(
            "Eichrecht/PTB wording present — recorded separately, not counted as MID evidence.")
    if found.of_kind("iec_62053") or found.of_kind("iec_class"):
        proposal.warnings.append(
            "IEC 62053 Class 1/2 present — that is the older, non-MID accuracy scheme, "
            "not EN 50470-3 Class A/B/C.")
    if found.of_kind("ce") and proposal.status != "Unknown":
        proposal.warnings.append("CE mark present — noted and discounted; CE is never MID evidence.")
    if not (text or "").strip():
        proposal.warnings.append(
            "No text could be read from this file, so nothing was detected. Read it by hand.")
    return proposal


def build(text: str, kind: str, brand: str, model: str, current: Row | None = None,
          surface: str = SURFACE_UNKNOWN) -> Proposal:
    """A full proposal: status, evidence, proposed fields, and the diff."""
    proposal = decide(text, kind, surface)
    proposal.fields = {
        "Brand": brand or (current or {}).get("Brand", ""),
        "Model": model or (current or {}).get("Model", ""),
        "MID Status": proposal.status,
    }
    if proposal.doc and proposal.doc.certificate_number:
        proposal.fields["Certificate Link"] = (current or {}).get("Certificate Link", "")

    proposal.diff = diff_against(current, proposal)
    return proposal


def diff_against(current: Row | None, proposal: Proposal) -> list[dict]:
    """Field-by-field comparison, so a human sees exactly what would change."""
    rows = []
    for name, proposed in proposal.fields.items():
        existing = str((current or {}).get(name, "") or "")
        rows.append({
            "field": name,
            "current": existing,
            "proposed": str(proposed or ""),
            "changed": existing.strip() != str(proposed or "").strip(),
        })
    if current and str(current.get("MID Status", "")) != proposal.status:
        rows.append({
            "field": "⚠ contradiction",
            "current": f"register says {current.get('MID Status')}",
            "proposed": f"this document reads as {proposal.status}",
            "changed": True,
        })
    return rows
