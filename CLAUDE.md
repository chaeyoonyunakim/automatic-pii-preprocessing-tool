# NoteGuard — NHS Clinical-Note PII Sanitisation

Sanitise-at-source: detect + de-identify PII in free-text NHS clinical notes so only de-identified
data leaves a Trust. Encode Vibe Coding Hackathon — FLock Sovereign AI Challenge, Public Sector & Citizen Services task (Encode Hub); fork of `NoteGuard/`.

## Commands
```bash
# Setup (Windows PowerShell)
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[app,dev]"; python -m spacy download en_core_web_lg

python tests/run_eval.py --compare --limit 300   # VERIFIABLE SIGNAL: rules vs presidio+rules -> outputs/results.json
python -m src.trust_demo                          # two NHS Trusts share only de-identified data -> outputs/
streamlit run streamlit_app.py                    # demo (Try-it / Metrics / Governance / Two-Trust)
python -m pytest tests/ -v

# Offline data: set NOTEGUARD_DATA_DIR to a folder holding the 3 CSVs (else auto-downloaded from HF).
```

## Architecture
- `src/` — `data` (load + ground-truth join, EVAL-ONLY oracle) · `recognisers` (pure-Python
  rules) · `detect` (Rule / Presidio, graceful fallback) · `transform`
  (redact | patient-consistent pseudonymise + date-shift, Faker) · `evaluate` (P/R/F1 + residual
  leakage) · `pipeline` · `trust_demo`.
- `tests/run_eval.py` CLI · `streamlit_app.py` demo · `tests/` mirror `src/`. Packaged via `pyproject.toml`.

## Code style
- Python 3.10+, type hints on function signatures. The pure-Python rule layer must stay importable
  WITHOUT spaCy/Presidio (the fallback path). snake_case / PascalCase.

## Data rules (treat the synthetic notes as if real NHS PHI)
- `data/raw/`, `outputs/`, and any vault export are gitignored — never commit. Never paste note text
  into prompts; point at file paths.
- The note→patient join (`src/data.py` ground truth) is the EVAL-ONLY oracle. It must NEVER feed
  detection/transform — that is data leakage and invalidates the metric.
- Never silently fall back to an older/cached dataset — fail loudly.

## Decisions locked in (version 1 branch)
- **Default model: `en_core_web_lg`** — 100% name recall vs 91% for sm; clinical transformer
  (`obi/deid_roberta_i2b2`) was tested and performed worse on UK names (US i2b2 training data).
- **ORGANIZATION excluded from PresidioDetector.KEEP** — spaCy lg over-tags labels/abbreviations
  ("NHS", "DOB …", "GMC") as ORG, causing false positives and swallowing precise rule spans. NHS
  site names are caught by the `_SITE_RE` LOCATION rule (incl. "… Trust") instead.
- **`_merge` is overlap-safe + priority-ranked** — output spans are disjoint (no transform
  corruption); on overlap, precise rule entities (date/NHS/GMC/…) beat broad NER spans.
- **Human-in-the-loop review queue** — spans with score in `[review_threshold, score_threshold)`
  are redacted but flagged `needs_review=True` for IG analyst review before SDE pool admission.
- **Places recall** — low recall (0–0.7) was mostly generic "ward"/"bay" in GT (now filtered by
  `_GENERIC`); NHS site names are caught by the `_SITE_RE` LOCATION rule in recognisers.

## Gotchas
- Note text has mojibake (`Â·`) — `_fix_mojibake` runs before detection.
- Synthetic NHS numbers are 9 digits (no valid mod-11) — caught via the "NHS …" context anchor.
- Default spaCy model is now `en_core_web_lg`; the `PII_SPACY_MODEL` env var still overrides.

## Working with Claude
- After editing `src/recognisers.py` / `detect.py` / `transform.py`, run
  `python tests/run_eval.py --compare` and check residual leakage didn't regress.
