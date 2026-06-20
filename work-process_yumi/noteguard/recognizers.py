"""Pure-Python rule recognisers — no spaCy / Presidio dependency.

These give NoteGuard a transparent, auditable baseline that runs anywhere, and
let the evaluation harness work even before the (heavier) NER engine is wired up.
The NHS-number recogniser validates the mod-11 check digit so random 10-digit
strings (dose volumes, IDs) aren't flagged as patient identifiers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .data import DATE, LOCATION, PERSON, UK_NHS  # noqa: F401  (re-exported types)

EMAIL = "EMAIL_ADDRESS"
PHONE = "PHONE_NUMBER"
POSTCODE = "UK_POSTCODE"


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    entity_type: str
    text: str
    score: float = 1.0


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
_NHS_RE = re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{4}\b")
# Context-anchored: an "NHS ..." label followed by a 9-10 digit number. Needed
# because this synthetic dataset uses 9-digit NHS numbers (no valid checksum),
# which neither the checksum rule nor Presidio's UK_NHS recogniser would catch.
_NHS_CTX_RE = re.compile(
    r"NHS\s*(?:Number|No\.?|#)?\s*[:\-]?\s*(\d{3}[ -]?\d{3}[ -]?\d{2,4})",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\b(?:\+?44\s?|0)(?:\d\s?){9,10}\b")
# UK postcode (simplified but standard) e.g. SW1A 1AA, M1 1AE
_POSTCODE_RE = re.compile(
    r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE
)
_DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{2,4})\b",
    re.IGNORECASE,
)


def find_rule_spans(text: str) -> list[Span]:
    spans: list[Span] = []

    for m in _NHS_RE.finditer(text):
        if nhs_number_is_valid(m.group()):
            spans.append(Span(m.start(), m.end(), UK_NHS, m.group()))
    # context-anchored NHS numbers (catches the 9-digit synthetic ones)
    for m in _NHS_CTX_RE.finditer(text):
        spans.append(Span(m.start(1), m.end(1), UK_NHS, m.group(1)))

    for regex, etype in (
        (_EMAIL_RE, EMAIL),
        (_PHONE_RE, PHONE),
        (_POSTCODE_RE, POSTCODE),
        (_DATE_RE, DATE),
    ):
        for m in regex.finditer(text):
            spans.append(Span(m.start(), m.end(), etype, m.group()))

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
    demo = "NHS no 943 476 5919, ring 07700 900123, dob 12/03/1981, SW1A 1AA."
    for sp in find_rule_spans(demo):
        print(sp)
