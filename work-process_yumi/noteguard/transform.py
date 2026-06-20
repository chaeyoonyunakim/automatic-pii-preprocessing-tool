"""De-identification transforms.

Presidio anonymises per-document; the value NoteGuard adds is *cross-note,
patient-consistent* de-identification — the same patient maps to the same
surrogate across their whole admission journey, and their dates are shifted by a
single consistent offset so intervals (and therefore clinical timelines) survive.
That utility-preserving longitudinal property is what makes the cleaned data
useful for downstream / federated training instead of just safe.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .recognizers import Span

REDACTION = "redaction"
PSEUDONYM = "pseudonym"

_DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"]


@dataclass
class Replacement:
    original: str
    replacement: str
    entity_type: str


@dataclass
class PseudonymVault:
    """Stable original-value -> surrogate mapping (the 'mapping vault')."""
    _map: dict[tuple[str, str], str] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)

    def token_for(self, entity_type: str, value: str) -> str:
        key = (entity_type, value.strip().lower())
        if key not in self._map:
            self._counts[entity_type] = self._counts.get(entity_type, 0) + 1
            n = self._counts[entity_type]
            if entity_type == "PERSON":
                surrogate = f"Patient_{n:03d}"
            elif entity_type == "UK_NHS":
                surrogate = _fake_nhs_number(value)
            else:
                surrogate = f"{entity_type}_{n:03d}"
            self._map[key] = surrogate
        return self._map[key]

    def export(self) -> dict[str, str]:
        """Audit/export of the vault (keep this secret in production)."""
        return {f"{etype}:{val}": tok for (etype, val), tok in self._map.items()}


def _patient_date_offset(person_id: str, max_days: int = 365) -> int:
    """Deterministic per-patient shift in [-max_days, max_days], from person_id."""
    h = int(hashlib.sha256(f"noteguard:{person_id}".encode()).hexdigest(), 16)
    return (h % (2 * max_days + 1)) - max_days


def _fake_nhs_number(value: str) -> str:
    """Deterministic, checksum-VALID fake NHS number (stable per original)."""
    from .recognizers import nhs_number_is_valid

    seed = int(hashlib.sha256(value.encode()).hexdigest(), 16)
    for _ in range(1000):
        nine = f"{seed % 1_000_000_000:09d}"
        total = sum(int(nine[i]) * (10 - i) for i in range(9))
        check = 11 - (total % 11)
        check = 0 if check == 11 else check
        if check != 10:
            candidate = nine + str(check)
            if nhs_number_is_valid(candidate):
                return candidate
        seed = (seed * 1103515245 + 12345) & ((1 << 64) - 1)
    return "0000000000"


def _shift_date(value: str, offset_days: int) -> str | None:
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return (dt + timedelta(days=offset_days)).strftime(fmt)
        except ValueError:
            continue
    return None


def apply_transform(
    text: str,
    spans: list[Span],
    method: str = REDACTION,
    vault: PseudonymVault | None = None,
    person_id: str = "",
) -> tuple[str, list[Replacement]]:
    """Return (sanitised_text, replacements). Spans applied right-to-left."""
    vault = vault or PseudonymVault()
    offset = _patient_date_offset(person_id) if person_id else 0
    out = text
    used: list[Replacement] = []
    for s in sorted(spans, key=lambda x: x.start, reverse=True):
        original = text[s.start:s.end]
        if method == REDACTION:
            repl = f"[{s.entity_type}]"
        else:  # PSEUDONYM
            if s.entity_type == "DATE_TIME":
                shifted = _shift_date(original, offset)
                repl = shifted if shifted else "[DATE_TIME]"
            else:
                repl = vault.token_for(s.entity_type, original)
        out = out[:s.start] + repl + out[s.end:]
        used.append(Replacement(original, repl, s.entity_type))
    used.reverse()
    return out, used


if __name__ == "__main__":
    from .recognizers import find_rule_spans

    txt = "Pt John seen 12/03/1981, NHS 943 476 5919. Reviewed again 20/03/1981."
    spans = find_rule_spans(txt)
    for method in (REDACTION, PSEUDONYM):
        v = PseudonymVault()
        new, repls = apply_transform(txt, spans, method, v, person_id="p7")
        print(f"\n[{method}] {new}")
        for r in repls:
            print("   ", r.original, "->", r.replacement, f"({r.entity_type})")
