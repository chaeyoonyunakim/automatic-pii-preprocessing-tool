# Changelog

Big changes since the fork of [`NoteGuard/Automatic-PII-preprocessing-tool`](https://github.com/NoteGuard/Automatic-PII-preprocessing-tool),
grouped by pull request / milestone (newest first). Encode Vibe Coding Hackathon — FLock Sovereign AI Challenge (hosted by Encode Hub).

## Live-demo polish — 2026-06-21
Direct UI / docs changes on `main` for the public demo.
- **Download de-identified output** from the Try-it tab: a single sanitised note *or* the full
  sanitised dataset, as JSON or CSV — only the de-identified text is exported (raw PHI never leaves).
- Removed FLock.io as a technical reference throughout (UI + docs); kept only the hackathon credit.
- Added a hackathon footer to every tab.
- Simplified the UI copy: dropped model / algorithm names and file / command references; renamed the
  "Metrics & Leakage" tab; 1-based note index; 50 sample notes in the browser.
- Fixed the Streamlit `outputs/` path after the app moved to the repo root (the Metrics and Two-Trust
  "Run" buttons read / wrote the wrong location).

## [0.0.1] — 2026-06-20 — first release (Gold-RAP restructure & Hugging Face deploy)
Branches `dev/refactor-cleancode` + `feat/hf-spaces-demo`, merged to `main`.
- Reorganised to a Gold-RAP "analysis as a product" layout: `src/` package, `tests/`, `docs/`,
  `data/` (inputs), `outputs/` (generated artifacts).
- Renamed package `noteguard/` → `src/`; British spelling throughout (`recognisers`).
- Packaged via `pyproject.toml` as the single dependency source (removed `requirements.txt`).
- CI (`.github/workflows/ci.yml`) runs `ruff` + `pytest` on every push/PR; added logging.
- Streamlit demo moved to repo root (`streamlit_app.py`); `run_eval.py` moved under `tests/`.
- Hugging Face Spaces (Docker SDK) deploy: `Dockerfile`, README front-matter, `docs/DEPLOY_HF_SPACES.md`.
- Decluttered Claude tooling (eval skill, post-edit hook, local settings) and the root changelog.

## Post-PR #3 hardening — 2026-06-20
Direct fixes on `main` after the team-briefing work.
- Only **date-of-birth** is masked; visit / admission dates are kept (clinically useful). Human-readable
  redaction labels (e.g. `[NHS number]`).
- Fixed pseudonym mis-mapping caused by spaCy ORGANIZATION over-tagging.
- Removed the roster / gazetteer feature (kept the metric honest — no circularity).
- Consolidated the frontend on Streamlit; removed the Gradio demo.

## PR #3 — Action items 1–4 from the team briefing — 2026-06-20
- Default spaCy model `en_core_web_lg` (best UK-name recall; clinical transformer tested and rejected).
- **Human-in-the-loop review queue**: low-confidence spans are still redacted *and* flagged for IG
  analyst confirmation before SDE-pool admission.
- ORGANIZATION excluded from Presidio's kept entities (it over-tagged labels like "NHS"/"GMC"); NHS
  site names caught by a LOCATION rule instead.
- Overlap-safe, priority-ranked span merge (precise rule entities beat broad NER spans).

## PR #2 — UK entity backport — 2026-06-20
- Added `UK_NINO`, `UK_PASSPORT`, `UK_VEHICLE_REGISTRATION` recognisers and comma-separated
  NHS-number detection, with format-correct fake surrogates for each.

## PR #1 — NoteGuard de-identification gate — 2026-06-20
Consolidated two parallel implementations into one package.
- One pluggable `Detector` interface: `RuleDetector` / `PresidioDetector`, degrading gracefully to
  pure-Python rules when spaCy/Presidio are unavailable.
- Patient-consistent pseudonymisation via a Faker(en_GB) vault + per-patient date-shift; redaction mode.
- Evaluation harness: per-entity precision / recall / F1 **and** a measured residual-leakage rate,
  using the dataset's structured patient/admission tables as free ground truth.
- Two-Trust "sanitise-at-source" demo; Streamlit demo UI.

## Initial NoteGuard implementation
- Pure-Python `noteguard` package: rule recognisers (NHS Modulus-11 + context anchor, postcode, date,
  phone, email), detection layer, redaction/pseudonymisation transforms, evaluation, pipeline.
- Loads the NHSE synthetic clinical notes (3 CSVs joined on `person_id`/`admission_id`).

## Initial commit
- Fork of `NoteGuard/Automatic-PII-preprocessing-tool`.
