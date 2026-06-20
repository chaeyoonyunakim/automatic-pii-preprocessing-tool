"""Run the NoteGuard evaluation over the NHSE synthetic dataset.

    python run_eval.py --limit 300            # quick run
    python run_eval.py --method pseudonym     # leakage under pseudonymisation
    python run_eval.py --compare              # rules-only vs presidio+rules

Writes results.json (consumed by the demo's metrics panel) and prints a summary.
"""
from __future__ import annotations

import argparse
import json

from noteguard.data import load_notes
from noteguard.detect import RuleDetector, build_detector
from noteguard.evaluate import EvalResult, evaluate
from noteguard.transform import REDACTION


def _print_summary(res: EvalResult) -> None:
    d = res.to_dict()
    print(f"\n  detector : {d['detector']}")
    print(f"  transform: {d['transform']}   notes: {d['notes_evaluated']}")
    ov = d["detection"]["overall"]
    print(f"  detection  P={ov['precision']:.3f}  R={ov['recall']:.3f}  F1={ov['f1']:.3f}")
    print("  per-entity:")
    for et, m in d["detection"]["per_entity"].items():
        print(f"     {et:<14} P={m['precision']:.3f} R={m['recall']:.3f} "
              f"F1={m['f1']:.3f}  (support={m['support']})")
    lk = d["leakage"]
    print(f"  >> RESIDUAL LEAKAGE: {lk['residual_leaks_after_sanitisation']}"
          f"/{lk['total_known_pii_occurrences']} = {lk['leakage_rate_pct']:.2f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300, help="max notes (None=all)")
    ap.add_argument("--method", default=REDACTION, choices=["redaction", "pseudonym"])
    ap.add_argument("--no-presidio", action="store_true", help="rules only")
    ap.add_argument("--compare", action="store_true", help="rules vs presidio+rules")
    ap.add_argument("--out", default="results.json")
    args = ap.parse_args()

    print(f"[noteguard] loading notes (limit={args.limit}) ...")
    records = load_notes(limit=args.limit)
    print(f"[noteguard] {len(records)} notes; "
          f"{sum(len(r.ground_truth) for r in records)} known PII values joined.")

    runs: dict[str, EvalResult] = {}
    if args.compare:
        print("\n=== rules-only ===")
        runs["rules"] = evaluate(records, RuleDetector(), args.method)
        _print_summary(runs["rules"])
        print("\n=== presidio+rules ===")
        runs["presidio+rules"] = evaluate(records, build_detector(True), args.method)
        _print_summary(runs["presidio+rules"])
    else:
        det = RuleDetector() if args.no_presidio else build_detector(True)
        res = evaluate(records, det, args.method)
        _print_summary(res)
        runs[res.detector_name] = res

    payload = {name: r.to_dict() for name, r in runs.items()}
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n[noteguard] wrote {args.out}")


if __name__ == "__main__":
    main()
