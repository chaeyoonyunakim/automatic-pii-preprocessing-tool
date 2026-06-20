"""Simulate two NHS Trusts collaborating without sharing sensitive data.

Each Trust holds its own patients and its own re-identification vault. It
sanitises its notes LOCALLY and contributes only the
de-identified text + a content-free audit manifest to a shared pool. Raw notes and
vaults never leave the Trust. This is the sanitise-at-source gate that sits in
front of a federated SDE / FLock.io training round.

    python -m src.trust_demo                 # pseudonymise, 300 notes
    python -m src.trust_demo redaction 600
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from .data import NoteRecord, load_notes
from .detect import build_detector
from .evaluate import _find_all, ground_truth_spans, value_variants
from .pipeline import Pipeline
from .transform import PSEUDONYM, PseudonymVault

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
TRUST_NAMES = {0: "Trust A (Northgate NHS Foundation Trust)", 1: "Trust B (Riverside NHS Trust)"}


def _assign_trust(person_id: str) -> int:
    return (hash(person_id) & 1) if person_id else 0


def _residual_leaks(rec: NoteRecord, sanitised: str) -> tuple[int, int]:
    """(present, leaked) for this note's known identifiers against the sanitised text."""
    gt = ground_truth_spans(rec)
    present = len(gt)
    leaked = 0
    for g in gt:
        if any(len(v) >= 2 and _find_all(sanitised, v) for v in value_variants(g.text, g.entity_type)):
            leaked += 1
    return present, leaked


def _run_trust(trust_id: int, records: list[NoteRecord], method: str, base_detector) -> dict:
    """Sanitise one Trust's notes locally; return a shareable manifest + de-identified records."""
    pipeline = Pipeline(detector=base_detector, vault=PseudonymVault())  # vault stays local

    entity_counts: Counter = Counter()
    deidentified: list[dict] = []
    present = leaked = 0
    for rec in records:
        if not rec.text:
            continue
        result = pipeline.sanitise(rec.text, method, rec.person_id)
        entity_counts.update(s.entity_type for s in result.spans)
        deidentified.append({"note_id": rec.note_id, "sanitised_text": result.sanitised})
        p, lk = _residual_leaks(rec, result.sanitised)
        present += p
        leaked += lk

    manifest = {
        "trust": TRUST_NAMES[trust_id],
        "patients": len({r.person_id for r in records}),
        "notes_deidentified": len(deidentified),
        "raw_records_shared": 0,
        "entity_counts": dict(entity_counts),
        "known_pii_occurrences": present,
        "residual_leaks": leaked,
        "method": method,
    }
    return {"manifest": manifest, "deidentified": deidentified}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # allow ✅/❌ when piped on Windows
    except Exception:
        pass
    method = sys.argv[1] if len(sys.argv) > 1 else PSEUDONYM
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 300

    records = load_notes(limit=limit)
    split: dict[int, list[NoteRecord]] = {0: [], 1: []}
    for rec in records:
        split[_assign_trust(rec.person_id)].append(rec)

    print("[noteguard] loading detection engine (Presidio + rules) ...")
    base_detector = build_detector(use_presidio=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shared_pool: list[dict] = []
    manifests = []
    for trust_id, recs in split.items():
        result = _run_trust(trust_id, recs, method, base_detector)
        manifests.append(result["manifest"])
        trust_dir = OUT_DIR / f"trust_{trust_id}"
        trust_dir.mkdir(exist_ok=True)
        (trust_dir / "manifest.json").write_text(json.dumps(result["manifest"], indent=2), encoding="utf-8")
        with (trust_dir / "deidentified.jsonl").open("w", encoding="utf-8") as fh:
            for record in result["deidentified"]:
                fh.write(json.dumps(record) + "\n")
        shared_pool.extend(result["deidentified"])

    with (OUT_DIR / "shared_pool.jsonl").open("w", encoding="utf-8") as fh:
        for record in shared_pool:
            fh.write(json.dumps(record) + "\n")

    total_leaks = sum(m["residual_leaks"] for m in manifests)
    summary = {
        "trusts": manifests,
        "shared_pool_size": len(shared_pool),
        "raw_records_shared": 0,
        "total_residual_leaks": total_leaks,
    }
    (OUT_DIR / "trust_demo_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    for m in manifests:
        print(f"  {m['trust']}: {m['notes_deidentified']} notes de-identified, "
              f"{m['raw_records_shared']} raw shared, {m['residual_leaks']} residual leaks")
    print(f"\nShared pool: {len(shared_pool)} de-identified notes | raw shared: 0 | "
          f"total residual leaks: {total_leaks} {'✅' if total_leaks == 0 else '⚠️'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
