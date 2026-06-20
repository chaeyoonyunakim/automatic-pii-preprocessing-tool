"""Evaluation harness — NoteGuard's 'reliable' pillar.

Because the dataset's PII lives in structured tables, every note has ground-truth
identifiers. We measure two things Presidio alone never reports:

  1. Detection quality  : per-entity precision / recall / F1 against known PII.
  2. Residual leakage   : after sanitisation, how many KNOWN identifiers still
                          appear in the output text. This is the headline number —
                          an honest, measurable re-identification risk.

Caveat we state openly: precision is measured against *structured* PII only.
A note may contain PII not present in the tables (e.g. a clinician's name); a
correct detection of it counts here as a false positive, so reported precision is
a conservative lower bound. Recall and leakage are unaffected.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .data import NoteRecord
from .detect import Detector
from .recognizers import Span
from .transform import REDACTION, PseudonymVault, apply_transform

_DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d %B %Y"]


def _date_variants(value: str) -> list[str]:
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return list({dt.strftime(f) for f in _DATE_FORMATS})
        except ValueError:
            continue
    return [value]


def value_variants(value: str, entity_type: str) -> list[str]:
    """Surface forms of a known PII value as it might appear in free text."""
    value = value.strip()
    if not value:
        return []
    if entity_type == "PERSON":
        parts = value.split()
        out = [value]
        if len(parts) > 1:
            out.append(parts[-1])   # surname alone
            out.append(parts[0])    # forename alone
        return out
    if entity_type == "UK_NHS":
        digits = "".join(ch for ch in value if ch.isdigit())
        out = {value, digits}
        if len(digits) == 10:
            out.add(f"{digits[:3]} {digits[3:6]} {digits[6:]}")
            out.add(f"{digits[:3]}-{digits[3:6]}-{digits[6:]}")
        return list(out)
    if entity_type == "DATE_TIME":
        return _date_variants(value)
    return [value]


def _find_all(haystack: str, needle: str) -> list[tuple[int, int]]:
    """Case-insensitive, word-boundary-aware occurrences of needle in haystack."""
    if not needle:
        return []
    hl, nl = haystack.lower(), needle.lower()
    spots: list[tuple[int, int]] = []
    start = 0
    while True:
        i = hl.find(nl, start)
        if i == -1:
            break
        left_ok = i == 0 or not (hl[i - 1].isalnum())
        right_ok = i + len(nl) == len(hl) or not (hl[i + len(nl)].isalnum())
        if left_ok and right_ok:
            spots.append((i, i + len(nl)))
        start = i + 1
    return spots


def ground_truth_spans(record: NoteRecord) -> list[Span]:
    """Locate each known PII value (and its surface variants) inside the note."""
    occ: list[Span] = []
    for gt in record.ground_truth:
        for variant in value_variants(gt.text, gt.entity_type):
            if len(variant) < 2:
                continue
            for s, e in _find_all(record.text, variant):
                occ.append(Span(s, e, gt.entity_type, record.text[s:e]))
    return _dedupe(occ)


def _dedupe(spans: list[Span]) -> list[Span]:
    seen: set[tuple[int, int]] = set()
    out: list[Span] = []
    for s in sorted(spans, key=lambda x: (x.start, -(x.end - x.start))):
        if any(s.start >= a and s.end <= b for (a, b) in seen):
            continue
        seen.add((s.start, s.end))
        out.append(s)
    return out


def _overlaps(a: Span, b: Span) -> bool:
    return a.start < b.end and b.start < a.end


@dataclass
class Counter:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class EvalResult:
    notes: int = 0
    per_entity: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    overall: Counter = field(default_factory=Counter)
    total_gt_occurrences: int = 0
    residual_leaks: int = 0
    transform_method: str = REDACTION
    detector_name: str = ""

    @property
    def leakage_rate(self) -> float:
        return self.residual_leaks / self.total_gt_occurrences if self.total_gt_occurrences else 0.0

    def to_dict(self) -> dict:
        return {
            "detector": self.detector_name,
            "transform": self.transform_method,
            "notes_evaluated": self.notes,
            "detection": {
                "overall": {
                    "precision": round(self.overall.precision, 4),
                    "recall": round(self.overall.recall, 4),
                    "f1": round(self.overall.f1, 4),
                    "tp": self.overall.tp, "fp": self.overall.fp, "fn": self.overall.fn,
                },
                "per_entity": {
                    et: {
                        "precision": round(c.precision, 4),
                        "recall": round(c.recall, 4),
                        "f1": round(c.f1, 4),
                        "support": c.tp + c.fn,
                    }
                    for et, c in sorted(self.per_entity.items())
                },
            },
            "leakage": {
                "total_known_pii_occurrences": self.total_gt_occurrences,
                "residual_leaks_after_sanitisation": self.residual_leaks,
                "leakage_rate": round(self.leakage_rate, 4),
                "leakage_rate_pct": round(100 * self.leakage_rate, 2),
            },
        }


def evaluate(
    records: list[NoteRecord],
    detector: Detector,
    transform_method: str = REDACTION,
) -> EvalResult:
    res = EvalResult(transform_method=transform_method, detector_name=getattr(detector, "name", "?"))
    for rec in records:
        if not rec.text:
            continue
        res.notes += 1
        gt = ground_truth_spans(rec)
        detected = detector.detect(rec.text)

        # ---- detection precision / recall (overlap-based) ----
        matched_det: set[int] = set()
        for g in gt:
            hit = next((i for i, d in enumerate(detected)
                        if i not in matched_det and _overlaps(g, d)), None)
            if hit is not None:
                matched_det.add(hit)
                res.per_entity[g.entity_type].tp += 1
                res.overall.tp += 1
            else:
                res.per_entity[g.entity_type].fn += 1
                res.overall.fn += 1
        for i, d in enumerate(detected):
            if i not in matched_det:
                res.per_entity[d.entity_type].fp += 1
                res.overall.fp += 1

        # ---- residual leakage after sanitisation ----
        vault = PseudonymVault()
        sanitised, _ = apply_transform(
            rec.text, detected, transform_method, vault, rec.person_id
        )
        res.total_gt_occurrences += len(gt)
        # a known value leaks if any of its surface variants survives in output
        for g in gt:
            leaked = False
            for variant in value_variants(g.text, g.entity_type):
                if len(variant) >= 2 and _find_all(sanitised, variant):
                    leaked = True
                    break
            if leaked:
                res.residual_leaks += 1
    return res
