# 🛡️ NoteGuard

**Automatic PII sanitisation for NHS clinical notes — clean data in, no identifiers out.**

NoteGuard discovers, inspects, redacts, and de-identifies PII in free-text NHS
clinical notes **before** the data is used to train any model. It runs **locally
at each institution** ("sanitise at source"), so every trust cleans its own data
inside its own governance boundary before anything is shared or used in
collaborative / federated training.

> Federated learning lets institutions train without moving data. NoteGuard is the
> **privacy-preserving on-ramp** that makes the data safe to train on in the first place.

Hackathon: **FLock.io × UK Sovereign AI** — track *Trusted Data & AI Infrastructure*.

---

## What makes this more than "just Presidio"

[Microsoft Presidio](https://microsoft.github.io/presidio/) is the detection
**engine** — we don't reinvent it. NoteGuard is the **clinical assurance layer**
Presidio leaves to you:

1. **Measured residual leakage.** Presidio detects PII but never tells you *how
   much still leaks on your data*. Because the NHSE dataset keeps PII in structured
   tables, we join them back to each note to get ground truth for free and report a
   real **re-identification risk** number.
2. **Domain adaptation to messy clinical text.** Real notes are full of typos and
   abbreviations. We measure detection with vs without that noise, and add NHS-aware
   recognisers (checksum-validated NHS numbers **plus** context-anchored detection
   for the dataset's 9-digit synthetic numbers that Presidio's `UK_NHS` misses).
3. **Patient-consistent, longitudinal de-identification.** Presidio anonymises per
   document. NoteGuard keeps the *same patient → same surrogate* across their whole
   admission journey and shifts each patient's dates by one consistent offset, so
   intervals (clinical timelines) survive — useful data, not just safe data.
4. **Governance wrapper.** Per-note audit of what was removed, plus the dataset-level
   leakage report — aligned to NHSE's *fair / transparent / value-adding / reliable*
   ethics and the Five Safes (Safe Data: de-identify at source).

## Results (500 NHSE synthetic notes)

| Detector | NHS number F1 | PERSON recall | **Residual leakage** |
|---|---|---|---|
| rules only | 0.97 | 0.00 | **73.3 %** |
| **presidio + rules** | **0.98** | **0.69** | **4.6 %** |

**Residual leakage** = known identifiers (joined from the structured tables) still
present in the note *after* sanitisation. The rules→engine drop from 73 % → 4.6 %
is the headline: it shows, with numbers, exactly what the NER engine buys you.

> Precision is reported against *structured* PII only, so it is a conservative lower
> bound — correctly removing a clinician's name (not in the tables) counts here as a
> false positive. Recall and leakage are the sound, headline metrics.

## Architecture

```
data.py        load 3 CSVs, join on person_id/admission_id → per-note ground-truth PII
recognizers.py pure-Python rules: NHS checksum + NHS-context + postcode/date/phone/email
detect.py      Detector interface: RuleDetector · PresidioDetector · Gazetteer · Composite
transform.py   redaction · patient-consistent pseudonymisation (vault) · date-shift
evaluate.py    ground-truth matching → per-entity P/R/F1 + residual leakage rate
pipeline.py    single-note detect → de-identify → audit (used by UI + CLI)
run_eval.py    dataset-level evaluation → results.json
app.py         Gradio demo: note → highlighted PII → transform → sanitised + metrics
```

The rule layer and evaluation harness are **pure Python** — they run even if
Presidio/spaCy are unavailable, so the core "measure the leakage" capability never
depends on the heavy NER stack.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm

python run_eval.py --compare --limit 500   # reproduce the table above → results.json
python app.py                              # launch the demo UI (http://127.0.0.1:7860)
```

The NHSE synthetic dataset
([`NHSEDataScience/synthetic_clinical_notes`](https://huggingface.co/datasets/NHSEDataScience/synthetic_clinical_notes))
is pulled automatically on first run. To run fully offline, drop the three CSVs in a
folder and set `NOTEGUARD_DATA_DIR=/path/to/csvs`.

## Data note (found by inspecting the data, not assuming)

- NHS numbers in this synthetic set are **9 digits** (real ones are 10 + mod-11
  check). We catch both: checksum-validated 10-digit anywhere, **and**
  context-anchored numbers after an "NHS …" label.
- The `ward` column is the literal word `ward`, and some fields are double-encoded
  (`Â·`). Both are handled in `data.py` so they don't pollute the ground truth.

## Why synthetic data is a strength

No real patient data, no IG barrier, fully shareable — and it ships **known** PII in
structured tables, which is exactly what lets us report an honest, measurable leakage
rate instead of a vibe.
