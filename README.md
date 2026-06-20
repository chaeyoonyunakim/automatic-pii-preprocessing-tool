---
title: NoteGuard — NHS De-Identification Gate
emoji: 🛡️
sdk: docker
app_port: 8501
pinned: false
---

# 🛡️ NoteGuard

**Automatic PII sanitisation for NHS clinical notes — clean data in, no identifiers out.**

NoteGuard discovers, inspects, redacts and de-identifies PII in free-text NHS clinical notes **before**
the data is used to train any model. It runs **locally at each institution** ("sanitise at source"), so
every Trust cleans its own data inside its own governance boundary before anything is shared or used in
collaborative / federated training.

> Federated learning lets institutions train without moving data. NoteGuard is the **privacy-preserving
> on-ramp** that makes the data safe to train on in the first place — the missing layer in front of an
> NHS Secure Data Environment / the Federated Data Platform / FLock.io.

Encode Club hackathon — *Trusted Data & AI Infrastructure*. Built on **Microsoft Presidio** + **spaCy**,
evaluated on [NHSEDataScience/synthetic_clinical_notes](https://huggingface.co/datasets/NHSEDataScience/synthetic_clinical_notes).

## What makes this more than "just Presidio"

Presidio is the detection **engine** — we don't reinvent it. NoteGuard is the **clinical assurance
layer** Presidio leaves to you:

1. **Measured residual leakage.** Because the dataset keeps PII in structured tables, we join them back
   to each note for free ground truth and report a real **re-identification risk** number — not a vibe.
2. **Domain adaptation to messy clinical text.** NHS-aware recognisers: checksum-validated NHS numbers
   **plus** context-anchored detection for the dataset's 9-digit synthetic numbers Presidio's `UK_NHS`
   misses, plus GMC/NMC clinician IDs, ODS org codes and record UUIDs.
3. **Patient-consistent de-identification.** Same patient → same surrogate across their whole
   admission journey. Only date-of-birth is treated as PII (shifted by a consistent per-patient
   offset); visit / admission dates are clinically useful and left intact. Realistic en_GB fakes
   (or `[label]` redaction).
4. **Pluggable + degrades gracefully.** One `Detector` interface (Rule / Presidio); the pure-Python
   rule layer + eval run even if spaCy/Presidio are unavailable.
5. **Governance wrapper.** Per-note audit of what was removed + the dataset-level leakage report,
   mapped to the NHS **Five Safes**.

## Results — residual leakage drops as we layer detection

*Known identifiers (joined from the structured tables) still present after sanitisation. Measured on all
**1,602 notes** (1,027 known-PII occurrences). Reproduce with `python tests/run_eval.py --compare`.*

| Detector | NHS number F1 | PERSON recall | **Residual leakage** |
|---|---|---|---|
| rules only | 0.98 | 0.00 | **74.8 %** |
| **presidio + rules** (shipping) | **0.99** | **0.68** | **8.5 %** |

The rules→engine drop is the headline: it shows, with numbers, exactly what the NER engine buys you.

> Precision is reported against *structured* PII only, so it is a conservative lower bound — correctly
> removing a clinician's name (not in the tables) counts here as a false positive. **Recall and leakage
> are the sound, headline metrics.**

## Architecture

```
                 ┌──────────────────── inside Trust A ─────────────────────┐
 raw notes ──►   │  fix mojibake ─► detect (Presidio NER + rules)           │ ──► de-identified
 (PHI)           │                  ─► transform (redact | pseudonymise)    │     text + audit log
                 │                     patient-consistent + date-shift, vault│     (no PHI leaves)
                 └─────────────────────────────────────────────────────────┘
        same gate runs inside Trust B ──►  ┌────────────────────────────┐
                                           │  shared de-identified pool  │ ──► federated AI / FLock.io
                                           └────────────────────────────┘
```

**Project layout** (Gold-RAP "analysis as a product"):

```
src/                 the package
  data.py            load CSVs + ground-truth join (EVAL-ONLY oracle)
  recognisers.py     pure-Python rules: NHS checksum/context, postcode, date, phone, email, GMC/NMC/ODS, UUID
  detect.py          RuleDetector / PresidioDetector behind one Detector interface
  transform.py       redaction | patient-consistent pseudonymisation + DOB date-shift (Faker vault)
  pipeline.py        single-note detect -> sanitise -> audit
  evaluate.py        detection P/R/F1 + residual-leakage metric
  trust_demo.py      two-Trust sanitise-at-source demo
tests/               unit tests + run_eval.py (the evaluation CLI)
docs/                tool_card.md · CHANGELOG.md
data/                input CSVs (gitignored)
outputs/             generated artifacts: results.json, manifests (gitignored)
streamlit_app.py     demo UI + Hugging Face Space entry point
Dockerfile           HF Spaces (Docker) deploy      pyproject.toml   packaging + lint/test config
```

## Trust & governance — mapped to the NHS Five Safes
- **Safe data** — PII removed to DAPB1523/ICO standard across patient + staff + org identifiers.
- **Safe settings** — runs inside the Trust; raw CSVs and the vault are gitignored, never leave.
- **Safe outputs** — only de-identified text + content-free audit logs; the measured leakage gates them.
- **Safe people / projects** — the re-identification vault stays Trust-local; pseudonymised data is
  still personal data under UK GDPR — stated honestly, no over-claim.

## Run it

```bash
# 1) create AND activate the virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/Scripts/activate     #   ... or Windows Git Bash
# source .venv/bin/activate         #   ... or macOS / Linux

# 2) install the package (editable) + the spaCy model
pip install -e ".[app,dev]"
python -m spacy download en_core_web_lg   # or en_core_web_sm for a faster, lighter run

# 3) run
python tests/run_eval.py --compare --limit 300   # reproduce the table -> outputs/results.json
python -m src.trust_demo                          # two NHS Trusts share only de-identified data -> outputs/
streamlit run streamlit_app.py                    # demo: Try-it · Metrics · Governance · Two-Trust
pytest -q                                          # unit tests
```

The dataset is pulled automatically on first run. To run fully offline, drop the three CSVs in a
folder and set `NOTEGUARD_DATA_DIR=/path/to/csvs`.

## Deploy the live demo (Hugging Face Spaces)

```bash
pip install -U huggingface_hub      # provides the `hf` CLI
hf auth login                        # paste a WRITE token from https://huggingface.co/settings/tokens
hf repos create <user>/noteguard --repo-type space --space-sdk docker
git remote add space https://huggingface.co/spaces/<user>/noteguard
git push space HEAD:main             # builds the image and serves streamlit_app.py
```

## Data notes (found by inspecting the data, not assuming)
- NHS numbers in this synthetic set are **9 digits** (real ones are 10 + mod-11 check). We catch both:
  checksum-validated 10-digit anywhere, **and** context-anchored numbers after an "NHS …" label.
- Some fields are double-encoded (`Â·`); `_fix_mojibake` repairs them so they don't pollute ground truth.

Built with Claude Code (`CLAUDE.md`, `.claude/`).
