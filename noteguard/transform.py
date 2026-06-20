"""De-identification transforms.

Presidio anonymises per-document; the value NoteGuard adds is *cross-note,
patient-consistent* de-identification — the same patient maps to the same
surrogate across their whole admission journey, and their dates are shifted by a
single consistent offset so intervals (and therefore clinical timelines) survive.
That utility-preserving longitudinal property is what makes the cleaned data
useful for downstream / federated training instead of just safe.

Surrogates are realistic en_GB fakes (folded in from the Presidio branch's Faker
vault) so the output reads like a real note — better for training than `Patient_001`
tokens. Faker is optional: with it absent we fall back to deterministic tokens, so
the pure-Python guarantee holds.
"""
from __future__ import annotations

import hashlib
import random
import re
import string
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .recognizers import Span

REDACTION = "redaction"
PSEUDONYM = "pseudonym"

_DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"]
_POSTCODE_INWARD = re.compile(r"\s*\d[A-Za-z]{2}\s*$")

try:  # realistic surrogates if Faker is available
    from faker import Faker

    _FAKER: "Faker | None" = Faker("en_GB")
except Exception:  # pragma: no cover - keeps the pure-Python path working
    _FAKER = None


def _seed(value: str) -> int:
    return int(hashlib.sha256(value.encode()).hexdigest(), 16)


def _fake(value: str, kind: str) -> str | None:
    """Deterministic realistic surrogate for `value` via Faker, or None if unavailable."""
    if _FAKER is None:
        return None
    _FAKER.seed_instance(_seed(value) % (10 ** 9))
    if kind == "PERSON":
        return _FAKER.name()
    if kind == "LOCATION":
        return _FAKER.city()
    if kind == "EMAIL_ADDRESS":
        return _FAKER.safe_email()
    if kind == "PHONE_NUMBER":
        return _FAKER.phone_number()
    return None


def _postcode_outward(value: str) -> str:
    """Reduce a postcode to its outward code (DAPB1523-style geo generalisation)."""
    outward = _POSTCODE_INWARD.sub("", value).strip()
    return outward or "[UK_POSTCODE]"


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
            self._map[key] = self._make(entity_type, value)
        return self._map[key]

    def _make(self, entity_type: str, value: str) -> str:
        if entity_type == "UK_NHS":
            return _fake_nhs_number(value)
        if entity_type == "UK_POSTCODE":
            return _postcode_outward(value)
        if entity_type == "UK_NINO":
            return _fake_nino(value)
        if entity_type == "UK_VEHICLE_REGISTRATION":
            return _fake_vehicle(value)
        realistic = _fake(value, entity_type)
        if realistic is not None:
            return realistic
        # deterministic token fallback (no Faker, or an entity with no faker kind)
        self._counts[entity_type] = self._counts.get(entity_type, 0) + 1
        if entity_type == "PERSON":
            return f"Patient_{self._counts[entity_type]:03d}"
        return f"{entity_type}_{self._counts[entity_type]:03d}"

    def export(self) -> dict[str, str]:
        """Audit/export of the vault (keep this secret in production)."""
        return {f"{etype}:{val}": tok for (etype, val), tok in self._map.items()}


def _patient_date_offset(person_id: str, max_days: int = 365) -> int:
    """Deterministic per-patient shift in [-max_days, max_days], from person_id."""
    h = int(hashlib.sha256(f"noteguard:{person_id}".encode()).hexdigest(), 16)
    return (h % (2 * max_days + 1)) - max_days


def _fake_nino(value: str) -> str:
    """Format-correct fake NINO (XX999999X) — deterministic per original."""
    rng = random.Random(_seed(value))
    prefix = "".join(rng.choices(string.ascii_uppercase, k=2))
    digits = "".join(str(rng.randint(0, 9)) for _ in range(6))
    suffix = rng.choice("ABCD")
    return f"{prefix}{digits}{suffix}"


def _fake_vehicle(value: str) -> str:
    """Format-correct fake UK registration plate (AB12 CDE) — deterministic per original."""
    rng = random.Random(_seed(value))
    area = "".join(rng.choices(string.ascii_uppercase, k=2))
    age = "".join(str(rng.randint(0, 9)) for _ in range(2))
    seq = "".join(rng.choices(string.ascii_uppercase, k=3))
    return f"{area}{age} {seq}"


def _fake_nhs_number(value: str) -> str:
    """Deterministic, checksum-VALID fake NHS number (stable per original)."""
    from .recognizers import nhs_number_is_valid

    seed = _seed(value)
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
