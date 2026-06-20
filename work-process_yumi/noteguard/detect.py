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

    # Presidio entity types we keep (already aligned to our vocabulary)
    KEEP = {
        "PERSON", "DATE_TIME", "EMAIL_ADDRESS", "PHONE_NUMBER",
        "LOCATION", "UK_NHS", "UK_NINO", "IP_ADDRESS", "URL",
    }

    def __init__(self, spacy_model: str = "en_core_web_sm", score_threshold: float = 0.4):
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": spacy_model}],
        })
        self.engine = AnalyzerEngine(nlp_engine=provider.create_engine())
        self.score_threshold = score_threshold

    def detect(self, text: str) -> list[Span]:
        results = self.engine.analyze(text=text, language="en")
        spans = [
            Span(r.start, r.end, r.entity_type, text[r.start:r.end], r.score)
            for r in results
            if r.entity_type in self.KEEP and r.score >= self.score_threshold
        ]
        spans += find_rule_spans(text)
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


def build_detector(use_presidio: bool = True) -> Detector:
    """Best available detector; falls back to rules if Presidio import fails."""
    if use_presidio:
        try:
            return PresidioDetector()
        except Exception as e:  # pragma: no cover - environment dependent
            print(f"[noteguard] Presidio unavailable ({e}); falling back to rules.")
    return RuleDetector()
