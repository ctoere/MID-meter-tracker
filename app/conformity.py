"""Hunting down declarations of conformity, and fanning one out across the rows it covers.

A DoC is the strongest evidence this register can hold — it names the notified
body and the models in scope, which a datasheet does not. It is also the most
commonly over-read document on this job: a declaration covering "the EVSE" under
the Low Voltage and EMC directives looks entirely official and says nothing
whatsoever about metrology. Only a DoC citing 2014/32/EU is MID evidence.

Two things shape this module:

  - **A DoC is per brand or product family, not per model.** One Alfen
    declaration typically lists the whole Eve line. So the work is organised by
    brand, and one document can clear a dozen register rows at once. That
    fan-out is the point; searching is just the tedious part in front of it.

  - **Discovery stays human.** There is no EU registry of declarations. Each
    manufacturer publishes on their own site, often behind a portal or an email
    request, with no standard path. This module builds the searches and reads
    what comes back; a person decides which document is the right one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus, urlparse

from . import domain, schema

Row = dict[str, Any]

#: Hosts that are not the manufacturer, so a datasheet URL pointing at one tells
#: us nothing about where that brand publishes its declarations. CDNs, document
#: mirrors, resellers and test houses all show up in the register's links.
NOT_MANUFACTURER = (
    "contentstack.com", "cloudfront.net", "amazonaws.com", "akamaized.net",
    "azureedge.net", "cdn.shopify.com", "shopify.com", "googleusercontent.com",
    "manualslib.com", "elaad.nl", "scribd.com", "yumpu.com", "docplayer.net",
    "wallboxdiscounter.nl", "autoladen.nl", "plugnet.be", "thundergrid.net",
)

#: "Declaration of conformity" in the languages this market actually publishes in.
DOC_PHRASES = (
    '"declaration of conformity"',
    '"verklaring van overeenstemming"',       # NL
    '"Konformitätserklärung"',                # DE
    '"déclaration de conformité"',            # FR
)

#: Paths manufacturers commonly park downloads under, worth trying directly.
COMMON_PATHS = ("/downloads", "/support/downloads", "/en/downloads", "/service/downloads",
                "/documentation", "/downloads/certificates", "/support")


@dataclass
class BrandTarget:
    """One brand's worth of outstanding conformity work."""
    brand: str
    rows: list[Row] = field(default_factory=list)
    domain: str = ""
    domain_is_guess: bool = True

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def models(self) -> list[str]:
        return sorted({str(r.get("Model", "")).strip() for r in self.rows if r.get("Model")})


# ---------------------------------------------------------------------------
# the backlog
# ---------------------------------------------------------------------------

def needs_certificate(row: Row) -> bool:
    """True for a row that ought to have a declaration and does not.

    Only eligible rows qualify. A charger with no MID metering does not need a
    MID declaration, and an Unknown row needs research before it needs paperwork.
    """
    return (schema.is_eligible(row.get("MID Status"))
            and not str(row.get("Certificate Link", "") or "").strip())


def backlog(chargers: list[Row]) -> list[Row]:
    return [r for r in chargers if needs_certificate(r)]


def derive_domain(brand: str, chargers: list[Row]) -> tuple[str, bool]:
    """Best guess at a brand's own domain, from datasheet links already on file.

    Returns (domain, is_guess). Hosts on NOT_MANUFACTURER are skipped: a link to
    a CDN or a reseller says nothing about where the manufacturer publishes.
    """
    counts: dict[str, int] = {}
    for row in chargers:
        if str(row.get("Brand", "")).strip() != brand:
            continue
        url = str(row.get("Datasheet Link", "") or "").strip()
        if not url:
            continue
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if not host or any(bad in host for bad in NOT_MANUFACTURER):
            continue
        counts[host] = counts.get(host, 0) + 1
    if not counts:
        return "", True
    return max(counts, key=lambda h: counts[h]), True


def targets(chargers: list[Row], overrides: dict[str, str] | None = None) -> list[BrandTarget]:
    """The backlog grouped by brand, busiest first — the order to work in."""
    overrides = overrides or {}
    grouped: dict[str, BrandTarget] = {}
    for row in backlog(chargers):
        brand = str(row.get("Brand", "")).strip() or "(no brand)"
        grouped.setdefault(brand, BrandTarget(brand)).rows.append(row)

    for brand, target in grouped.items():
        if brand in overrides and overrides[brand]:
            target.domain, target.domain_is_guess = overrides[brand], False
        else:
            target.domain, target.domain_is_guess = derive_domain(brand, chargers)

    return sorted(grouped.values(), key=lambda t: (-t.count, t.brand.casefold()))


# ---------------------------------------------------------------------------
# the searches
# ---------------------------------------------------------------------------

def _google(query: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(query)}"


def _duckduckgo(query: str) -> str:
    return f"https://duckduckgo.com/?q={quote_plus(query)}"


def search_links(brand: str, domain_hint: str = "", models: list[str] | None = None) -> list[dict]:
    """Ready-made searches for one brand's declaration of conformity.

    Ordered most-likely-first. The directive number is the highest-signal term
    there is — a declaration citing 2014/32/EU is the only kind worth having, so
    it goes in the first query rather than being filtered out afterwards.
    """
    links: list[dict] = []
    phrases = " OR ".join(DOC_PHRASES)

    if domain_hint:
        links.append({
            "label": f"On {domain_hint} — declaration citing the directive",
            "url": _google(f'site:{domain_hint} ({phrases}) "2014/32/EU"'),
            "note": "the highest-signal query: their own site, the right document, the right directive",
        })
        links.append({
            "label": f"On {domain_hint} — any conformity document",
            "url": _google(f'site:{domain_hint} ({phrases} OR "MI-003" OR MID) filetype:pdf'),
            "note": "wider net on the same site, in case the directive is only in the PDF body",
        })

    links.append({
        "label": f"{brand} — declaration citing 2014/32/EU",
        "url": _google(f'"{brand}" ({phrases}) "2014/32/EU" filetype:pdf'),
        "note": "whole web; catches documents hosted on a distributor's site",
    })
    links.append({
        "label": f"{brand} — MID certificate / MI-003",
        "url": _google(f'"{brand}" (MID OR "MI-003") (certificate OR conformity) filetype:pdf'),
        "note": "sometimes the meter's certificate is published instead of the charger's DoC",
    })
    links.append({
        "label": f"{brand} — DuckDuckGo (no personalised results)",
        "url": _duckduckgo(f'"{brand}" ({phrases}) "2014/32/EU"'),
        "note": "a second opinion when Google returns only shop listings",
    })

    if models:
        first = models[0]
        links.append({
            "label": f"Specific model — {first}",
            "url": _google(f'"{brand}" "{first}" ({phrases} OR "MI-003")'),
            "note": "use when the brand-level search returns a declaration that omits this model",
        })

    if domain_hint:
        for path in COMMON_PATHS[:4]:
            links.append({
                "label": f"Browse {domain_hint}{path}",
                "url": f"https://{domain_hint}{path}",
                "note": "manufacturers often keep declarations on a downloads page rather than indexed",
                "browse": True,
            })

    return links


# ---------------------------------------------------------------------------
# fan-out: one document, many rows
# ---------------------------------------------------------------------------

def _normalise(text: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text or "").lower())


#: Below this, a normalised model string is too generic to match on safely —
#: "S" or "Pro" would otherwise attach a certificate to half a brand's range.
MIN_MATCH_LENGTH = 4


def split_models(covered: Any) -> list[str]:
    """Split a DoC's 'models covered' text into individual model strings."""
    text = str(covered or "")
    parts = re.split(r"[;,/\n]| and | en |&", text)
    return [p.strip(" .()-") for p in parts if p.strip(" .()-")]


def match_rows(chargers: list[Row], brand: str, covered: Any) -> list[dict]:
    """Register rows a declaration appears to cover, with why each matched.

    Deliberately conservative. Attaching a certificate to a model it does not
    cover manufactures evidence, which is worse than leaving a row unlinked for
    someone to do by hand — so a match needs the brand to agree and the model
    strings to genuinely correspond, and every match says how it was reached.
    """
    wanted = _normalise(brand)
    covered_models = split_models(covered)
    normalised = [(m, _normalise(m)) for m in covered_models]

    matches: list[dict] = []
    for row in chargers:
        if _normalise(row.get("Brand")) != wanted:
            continue
        model_raw = str(row.get("Model", "")).strip()
        model = _normalise(model_raw)
        if len(model) < MIN_MATCH_LENGTH:
            continue

        for original, candidate in normalised:
            if len(candidate) < MIN_MATCH_LENGTH:
                continue
            if model == candidate:
                reason, confidence = f"model matches {original!r} exactly", "exact"
            elif candidate in model:
                # The declaration names "Eve Mini"; the register spells the same
                # product "Eve Mini (ICU)". The document's name is the broader
                # one, so it covers this row.
                reason, confidence = f"{original!r} names this model", "likely"
            elif model in candidate:
                # The other direction is NOT the same thing. A declaration for
                # "Pulsar Plus" does not cover the base "Pulsar" — it names a
                # more specific product, and the register row is a different one.
                # Surfaced, but never as a confident match.
                reason, confidence = (
                    f"the declaration names {original!r}, which is more specific than this "
                    f"model — check whether it is the same product before linking", "check")
            else:
                continue
            matches.append({
                "id": row.get("ID"), "brand": row.get("Brand"), "model": model_raw,
                "status": row.get("MID Status"),
                "currentCertificate": str(row.get("Certificate Link", "") or ""),
                "matchedOn": original, "reason": reason, "confidence": confidence,
            })
            break

    return matches


def new_record(register, brand: str, doc: dict, stored: dict | None = None,
               link: str = "", user: str | None = None) -> Row:
    """Build a Conformity sheet row from an intake proposal's DoC details."""
    directive = "2014/32/EU" if doc.get("directive_cited") else ""
    non_eu = doc.get("non_eu_markers") or []
    if directive:
        review = ""
    elif non_eu:
        # Named explicitly: a UK or US declaration is not a near-miss EU one, it
        # is a different regime, and someone reading this row later needs to know
        # that chasing the "missing" directive would be wasted effort.
        review = (
            "NOT EU — this is a UK or US declaration (" + "; ".join(non_eu) + "). "
            "Great Britain and the United States run their own conformity regimes and neither "
            "has standing with the NEa. It cannot support an ERE eligibility claim. An EU "
            "declaration citing 2014/32/EU is still needed for these models.")
    else:
        review = (
            "This declaration does not cite 2014/32/EU, so it is NOT MID evidence. "
            "Keep it on file, but do not use it to support an eligibility claim.")
    return {
        "ID": domain.next_id(register.conformity, schema.ID_PREFIX[schema.SHEET_CONFORMITY],
                             issued=[e.get("Row ID", "") for e in register.change_log]),
        "Brand": brand,
        "Certificate Number": doc.get("certificate_number", ""),
        "Issuing Body": doc.get("issuing_body", ""),
        "Directive Cited": directive,
        "Models Covered": "; ".join(doc.get("models_covered", []) or []),
        "Document Link": link,
        "Drive File": (stored or {}).get("relative", ""),
        "SHA-256": (stored or {}).get("sha256", ""),
        "Date Added": domain.now_stamp(),
        "Added By": user or domain.current_user(),
        "Review Needed": review,
        "Notes": "; ".join(non_eu) if non_eu else "",
    }


def summarise(chargers: list[Row], conformity: list[Row]) -> dict:
    outstanding = backlog(chargers)
    mid_evidence = [c for c in conformity if str(c.get("Directive Cited", "")).strip()]
    return {
        "eligible": sum(1 for r in chargers if schema.is_eligible(r.get("MID Status"))),
        "outstanding": len(outstanding),
        "brands": len({str(r.get("Brand", "")).strip() for r in outstanding}),
        "held": len(conformity),
        "midEvidence": len(mid_evidence),
        "notMidEvidence": len(conformity) - len(mid_evidence),
    }
