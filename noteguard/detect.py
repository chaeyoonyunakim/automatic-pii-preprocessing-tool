"""Detection layer.

NoteGuard does not reinvent detection — Presidio is the engine. Our job is to
(1) compose Presidio's NER with our transparent rule layer, (2) keep everything
behind one `Detector` interface so the pipeline and eval are engine-agnostic, and
(3) make detection degrade gracefully to pure-Python rules when spaCy/Presidio
are unavailable.
"""
from __future__ import annotations

import re
from typing import Iterable, Protocol

from .recognizers import Span, find_rule_spans


class Detector(Protocol):
    def detect(self, text: str) -> list[Span]: ...


class RuleDetector:
    """Pure-Python baseline. No external dependencies."""

    name = "rules"

    def detect(self, text: str) -> list[Span]:
        return find_rule_spans(text)


class PresidioDetector:
    """Presidio AnalyzerEngine (spaCy NER + recognisers), unioned with our rules.

    The rule layer is kept in the union because our NHS-number recogniser is
    checksum-validated and our outputs stay auditable.
    """

    name = "presidio+rules"

    # Presidio entity types we keep. ORGANIZATION is included because NHS site names
    # (e.g. "Manchester Royal Infirmary") are often tagged as ORG rather than LOCATION;
    # excluding them was the main cause of low places recall.
    KEEP = {
        "PERSON", "DATE_TIME", "EMAIL_ADDRESS", "PHONE_NUMBER",
        "LOCATION", "ORGANIZATION", "UK_NHS", "UK_NINO", "UK_PASSPORT",
        "UK_VEHICLE_REGISTRATION", "IP_ADDRESS", "URL",
    }

    def __init__(
        self,
        spacy_model: str = "en_core_web_lg",
        score_threshold: float = 0.6,
        review_threshold: float = 0.35,
    ):
        """
        spacy_model      — en_core_web_lg (default, 100% name recall) or en_core_web_sm (faster).
        score_threshold  — spans above this are auto-confirmed and always redacted.
        review_threshold — spans in [review_threshold, score_threshold) are flagged
                           needs_review=True: still redacted for safety, but surfaced for
                           human confirmation in the audit/UI (human-in-the-loop queue).
        """
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": spacy_model}],
        })
        self.engine = AnalyzerEngine(nlp_engine=provider.create_engine())
        self.score_threshold = score_threshold
        self.review_threshold = review_threshold
        self._register_uk_recognizers()

    def _register_uk_recognizers(self) -> None:
        """Register UK entity recognizers that Presidio documents but does not ship."""
        from presidio_analyzer import Pattern, PatternRecognizer

        custom = [
            PatternRecognizer(
                supported_entity="UK_NINO",
                patterns=[Pattern("UK NINO", r"\b[A-Za-z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-Da-d]\b", 0.5)],
                context=["national insurance", "ni number", "nino"],
                name="UkNinoRecognizer",
            ),
            PatternRecognizer(
                supported_entity="UK_PASSPORT",
                # bare 9-digit is very low confidence — only scores up when a passport context word is nearby
                patterns=[Pattern("UK passport", r"\b\d{9}\b", 0.05)],
                context=["passport"],
                name="UkPassportRecognizer",
            ),
            PatternRecognizer(
                supported_entity="UK_VEHICLE_REGISTRATION",
                patterns=[Pattern("UK vehicle registration", r"\b[A-Za-z]{2}\d{2}\s?[A-Za-z]{3}\b", 0.4)],
                context=["registration", "vehicle", "number plate", "car"],
                name="UkVehicleRecognizer",
            ),
        ]
        for rec in custom:
            self.engine.registry.add_recognizer(rec)

    def detect(self, text: str) -> list[Span]:
        results = self.engine.analyze(text=text, language="en")
        spans: list[Span] = []
        for r in results:
            if r.entity_type not in self.KEEP:
                continue
            if r.score >= self.score_threshold:
                spans.append(Span(r.start, r.end, r.entity_type, text[r.start:r.end], r.score))
            elif r.score >= self.review_threshold:
                spans.append(
                    Span(r.start, r.end, r.entity_type, text[r.start:r.end], r.score,
                         needs_review=True)
                )
        spans += find_rule_spans(text)  # rule-based detections are always confident
        return _merge(spans)


class GazetteerDetector:
    """Match a known list of names/sites (the roster a trust actually holds).

    Catches identifiers the NER model misses (rare names, typo'd surnames) using
    whole-word, case-insensitive matching. Used as an optional layer to show the
    recall lift — not part of the headline eval, to avoid circularity.
    """

    name = "gazetteer"

    def __init__(self, terms: Iterable[tuple[str, str]], min_len: int = 3):
        self._patterns: list[tuple[re.Pattern, str]] = []
        seen: set[str] = set()
        for term, etype in terms:
            term = (term or "").strip()
            if len(term) < min_len or term.lower() in seen:
                continue
            seen.add(term.lower())
            self._patterns.append(
                (re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE), etype)
            )

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for pat, etype in self._patterns:
            for m in pat.finditer(text):
                spans.append(Span(m.start(), m.end(), etype, m.group(), 0.9))
        return spans


class CompositeDetector:
    def __init__(self, *detectors: Detector):
        self.detectors = detectors
        self.name = "+".join(getattr(d, "name", "?") for d in detectors)

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for d in self.detectors:
            spans += d.detect(text)
        return _merge(spans)


def _merge(spans: list[Span]) -> list[Span]:
    """Sort, then drop spans fully contained in a longer span (keep highest score)."""
    spans = sorted(spans, key=lambda s: (s.start, -(s.end - s.start), -s.score))
    kept: list[Span] = []
    for s in spans:
        if any(k.start <= s.start and s.end <= k.end for k in kept):
            continue
        kept.append(s)
    return kept


def build_detector(use_presidio: bool = True, spacy_model: str = "en_core_web_lg") -> Detector:
    """Best available detector; falls back to rules if Presidio import fails.

    spacy_model defaults to en_core_web_lg (100% name recall in benchmarks).
    Pass en_core_web_sm for faster startup when recall trade-off is acceptable.
    """
    if use_presidio:
        try:
            return PresidioDetector(spacy_model=spacy_model)
        except Exception as e:  # pragma: no cover - environment dependent
            print(f"[noteguard] Presidio unavailable ({e}); falling back to rules.")
    return RuleDetector()
