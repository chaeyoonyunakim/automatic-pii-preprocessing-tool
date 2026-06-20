"""End-to-end single-note pipeline: detect -> de-identify -> audit.

This is the unit the demo UI and the CLI both call.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .detect import Detector, build_detector
from .recognizers import Span
from .transform import REDACTION, PseudonymVault, Replacement, apply_transform


@dataclass
class SanitiseResult:
    original: str
    sanitised: str
    spans: list[Span]
    replacements: list[Replacement]
    method: str
    audit: dict = field(default_factory=dict)

    @property
    def review_items(self) -> list[Span]:
        """Spans flagged for human review (low-confidence detections that were still redacted)."""
        return [s for s in self.spans if s.needs_review]


class Pipeline:
    def __init__(self, detector: Detector | None = None, vault: PseudonymVault | None = None):
        self.detector = detector or build_detector()
        self.vault = vault or PseudonymVault()

    def sanitise(self, text: str, method: str = REDACTION, person_id: str = "") -> SanitiseResult:
        spans = self.detector.detect(text)
        sanitised, repls = apply_transform(text, spans, method, self.vault, person_id)
        by_type = Counter(s.entity_type for s in spans)
        needs_review = sum(1 for s in spans if s.needs_review)
        audit = {
            "detector": getattr(self.detector, "name", "?"),
            "method": method,
            "entities_removed": sum(by_type.values()),
            "by_type": dict(by_type),
            "needs_review": needs_review,
        }
        return SanitiseResult(text, sanitised, spans, repls, method, audit)
