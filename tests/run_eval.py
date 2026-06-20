"""Run the NoteGuard evaluation over the NHSE synthetic dataset.

    python tests/run_eval.py --limit 300            # quick run
    python tests/run_eval.py --method pseudonym     # leakage under pseudonymisation
    python tests/run_eval.py --compare              # rules-only vs presidio+rules

Writes outputs/results.json (consumed by the Streamlit metrics panel) and prints a summary.
This is the pipeline's evaluation entry point; it lives under tests/ alongside the unit tests.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # make the `src` package importable when run as a script

from src.data import load_notes  # noqa: E402
from src.detect import RuleDetector, build_detector  # noqa: E402
from src.evaluate import EvalResult, evaluate  # noqa: E402
from src.transform import REDACTION  # noqa: E402

OUTPUT_DIR = REPO / "outputs"
logger = logging.getLogger("noteguard.eval")


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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300, help="max notes (None=all)")
    ap.add_argument("--method", default=REDACTION, choices=["redaction", "pseudonym"])
    ap.add_argument("--no-presidio", action="store_true", help="rules only")
    ap.add_argument("--compare", action="store_true", help="rules vs presidio+rules")
    ap.add_argument("--out", default=None, help="output JSON path (default: outputs/results.json)")
    args = ap.parse_args()

    logger.info("loading notes (limit=%s) ...", args.limit)
    records = load_notes(limit=args.limit)
    logger.info("%d notes; %d known PII values joined.",
                len(records), sum(len(r.ground_truth) for r in records))

    runs: dict[str, EvalResult] = {}
    if args.compare:
        print("\n=== rules-only ===")
        runs["rules"] = evaluate(records, RuleDetector(), args.method)
        _print_summary(runs["rules"])
        print("\n=== presidio+rules (shipping headline detector) ===")
        runs["presidio+rules"] = evaluate(records, build_detector(True), args.method)
        _print_summary(runs["presidio+rules"])
    else:
        det = RuleDetector() if args.no_presidio else build_detector(True)
        res = evaluate(records, det, args.method)
        _print_summary(res)
        runs[res.detector_name] = res

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else OUTPUT_DIR / "results.json"
    out_path.write_text(json.dumps({n: r.to_dict() for n, r in runs.items()}, indent=2), encoding="utf-8")
    logger.info("wrote %s", out_path)


if __name__ == "__main__":
    main()
