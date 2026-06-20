"""Pure-Python rule recognisers — no spaCy / Presidio dependency.

These give NoteGuard a transparent, auditable baseline that runs anywhere, and
let the evaluation harness work even before the (heavier) NER engine is wired up.
The NHS-number recogniser validates the mod-11 check digit so random 10-digit
strings (dose volumes, IDs) aren't flagged as patient identifiers.

The NHS staff / organisation rules below (GMC & NMC clinician IDs, ODS org codes,
record UUIDs) were folded in from the Presidio branch so the rule layer also
covers people who aren't patients — Caldicott/DPA apply to anyone identifiable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .data import DATE, LOCATION, PERSON, UK_NHS  # noqa: F401  (re-exported types)

EMAIL = "EMAIL_ADDRESS"
PHONE = "PHONE_NUMBER"
POSTCODE = "UK_POSTCODE"
GMC = "GMC"              # General Medical Council number (UK doctors)
NMC = "NMC"              # Nursing & Midwifery Council PIN
NHS_ODS = "NHS_ODS"      # NHS Organisation Data Service codes (GP practices, trusts)
RECORD_ID = "RECORD_ID"  # record/document UUIDs that act as quasi-identifiers
UK_NINO = "UK_NINO"                    # National Insurance Number
UK_VEHICLE_REGISTRATION = "UK_VEHICLE_REGISTRATION"  # current-format UK plate


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    entity_type: str
    text: str
    score: float = 1.0
    needs_review: bool = False  # True for detections below the auto-confirm threshold


def nhs_number_is_valid(digits: str) -> bool:
    """Validate a 10-digit NHS number using the Modulus 11 check-digit algorithm."""
    d = re.sub(r"\D", "", digits)
    if len(d) != 10:
        return False
    total = sum(int(d[i]) * (10 - i) for i in range(9))
    remainder = total % 11
    check = 11 - remainder
    if check == 11:
        check = 0
    if check == 10:
        return False  # never valid
    return check == int(d[9])


# Real NHS numbers are 10 digits with a mod-11 check digit, optionally grouped.
# Dataset writes them with space, comma, or hyphen separators (e.g. 272,733,208).
_NHS_RE = re.compile(r"\b\d{3}[ ,\-]?\d{3}[ ,\-]?\d{4}\b")
# Context-anchored: an "NHS ..." label followed by a 9-10 digit number. Needed
# because this synthetic dataset uses 9-digit NHS numbers (no valid checksum),
# which neither the checksum rule nor Presidio's UK_NHS recogniser would catch.
_NHS_CTX_RE = re.compile(
    r"NHS\s*(?:Number|No\.?|#)?\s*[:\-]?\s*(\d{3}[ ,\-]?\d{3}[ ,\-]?\d{2,4})",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\b(?:\+?44\s?|0)(?:\d\s?){9,10}\b")
# UK postcode (simplified but standard) e.g. SW1A 1AA, M1 1AE
_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)
_DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{2,4})\b",
    re.IGNORECASE,
)
# --- NHS staff / organisation identifiers (context-anchored to avoid noise) ---
_GMC_RE = re.compile(r"(?i)\bGMC(?:\s*(?:no|number|#))?[:\s#]*(\d{7})\b")
_NMC_RE = re.compile(r"(?i)\bNMC(?:\s*pin)?[:\s#]*(\d{2}[A-Z]\d{4}[A-Z])\b")
_NMC_BARE_RE = re.compile(r"\b(\d{2}[A-Z]\d{4}[A-Z])\b")  # specific enough to stand alone
_ODS_RE = re.compile(r"(?i)\b(?:ODS|practice\s*code)[:\s]*([A-Z]\d{5})\b")
_UUID_RE = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", re.IGNORECASE
)
# 2 letters, 6 digits in pairs, A-D suffix — specific enough to fire without context anchoring
_NINO_RE = re.compile(r"\b[A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-Da-d]\b", re.IGNORECASE)
# Current-format UK plate: 2 letters, 2 digits, optional space, 3 letters (e.g. AB12 CDE)
_VEHICLE_RE = re.compile(r"\b[A-Z]{2}\d{2}\s?[A-Z]{3}\b")
# UK NHS site names: "X Hospital / Infirmary / NHS Trust / Medical Centre / Clinic"
# One-to-four leading title-cased words followed by a known NHS facility suffix.
# Context-anchored to title-case to avoid flagging generic lowercase mentions.
_SITE_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z']+\s+){1,4}"
    r"(?:Hospital|Infirmary|NHS\s+Trust|Medical\s+Centre|Health\s+Centre|Clinic|Surgery)\b"
)

# (regex, entity_type, capture_group): group 0 = whole match, 1 = inner capture
_PLAIN = [
    (_EMAIL_RE, EMAIL, 0),
    (_PHONE_RE, PHONE, 0),
    (_POSTCODE_RE, POSTCODE, 0),
    (_DATE_RE, DATE, 0),
    (_GMC_RE, GMC, 1),
    (_NMC_RE, NMC, 1),
    (_NMC_BARE_RE, NMC, 1),
    (_ODS_RE, NHS_ODS, 1),
    (_UUID_RE, RECORD_ID, 1),
    (_NINO_RE, UK_NINO, 0),
    (_VEHICLE_RE, UK_VEHICLE_REGISTRATION, 0),
]


def find_rule_spans(text: str) -> list[Span]:
    spans: list[Span] = []

    for m in _NHS_RE.finditer(text):
        if nhs_number_is_valid(m.group()):
            spans.append(Span(m.start(), m.end(), UK_NHS, m.group()))
    # context-anchored NHS numbers (catches the 9-digit synthetic ones)
    for m in _NHS_CTX_RE.finditer(text):
        spans.append(Span(m.start(1), m.end(1), UK_NHS, m.group(1)))

    for regex, etype, grp in _PLAIN:
        for m in regex.finditer(text):
            spans.append(Span(m.start(grp), m.end(grp), etype, m.group(grp)))

    for m in _SITE_RE.finditer(text):
        spans.append(Span(m.start(), m.end(), LOCATION, m.group()))

    return _dedupe(spans)


def _dedupe(spans: list[Span]) -> list[Span]:
    """Drop spans fully contained within another (keep the longer match)."""
    spans = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
    kept: list[Span] = []
    for s in spans:
        if any(k.start <= s.start and s.end <= k.end for k in kept):
            continue
        kept.append(s)
    return kept


if __name__ == "__main__":
    # quick check: 9434765919 is a documented valid NHS test number
    assert nhs_number_is_valid("943 476 5919"), "valid NHS number rejected"
    assert not nhs_number_is_valid("943 476 5918"), "bad check digit accepted"
    demo = ("NHS no 943 476 5919, ring 07700 900123, dob 12/03/1981, SW1A 1AA, "
            "seen by Dr Lee GMC 1234567, nurse NMC 12A3456B.")
    for sp in find_rule_spans(demo):
        print(sp)
