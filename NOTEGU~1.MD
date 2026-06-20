# NoteGuard — Project Brief & Handover

**NoteGuard**
*An automatic PII preprocessing tool that sanitises NHS clinical notes before any model training.*

**Hackathon:** FLock.io × UK Sovereign AI (48 hours)
**Team:** Chaeyoon + Yumi
**Last updated:** 19 June 2026

---

## TL;DR

NoteGuard is an automatic preprocessing tool that **discovers, inspects, redacts, and de-identifies PII in free-text NHS clinical notes** before the data is used to train any model. It runs **locally at each trust** ("sanitise at source"), so each institution cleans its own data before anything is shared or used in collaborative/federated training.

> One-liner: *NoteGuard — automatic PII sanitisation for NHS clinical notes. Clean data in, no identifiers out.*

**Tracks:** Trusted Data & AI Infrastructure + AI Governance, Transparency & Trust.

---

## The problem

Clinical notes are the most IG-sensitive data the NHS holds. To use them for any ML they must first be de-identified, but:

- Manual de-identification is slow, inconsistent, and doesn't scale.
- Centralised tools (e.g. Google Cloud Sensitive Data Protection / Cloud DLP) require sending data to a proprietary external cloud.
- Free-text notes hide PII *inline in the narrative*, and real notes are full of typos and abbreviations that defeat naive rules.

NoteGuard automates de-identification at the point data enters the pipeline, on-prem, with a **measurable** leakage rate.

---

## Sovereignty framing (clarified by the judges)

"Sovereignty" does **not** mean locking data to UK soil. It means **data-jurisdiction sovereignty**: any institution or region retains governance over its own data and can collaborate without surrendering it — whether that boundary is an NHS trust, a London ICB, a US state health department, or an EU region.

NoteGuard's contribution: it sanitises data **inside its own governance boundary, wherever that is**, so cross-institution collaboration (incl. federated training) becomes possible without any central party ever seeing raw PII. NoteGuard is the **privacy-preserving on-ramp** to collaborative/federated AI.

> Avoid "don't send it to a US hyperscaler" — it's about *control*, not location.

---

## Scope (narrowed — this is the whole build)

We are building **only the PII preprocessing tool**, not a federated model. Federated learning is the *context/motivation* (sanitise-at-source enables it); the *deliverable* is the sanitiser.

**Note on FLock:** the judges confirmed we do **not** have to use FLock's API. Build the tool standalone; reference FLock as the decentralised-coordination layer NoteGuard feeds into.

---

## The pipeline (the product)

### 1. Ingest
Load clinical notes (NHSE synthetic dataset).

### 2. Detect / Inspect PII (layered — no single method catches everything)
- **Rules + checksums:** NHS number (10-digit, **mod-11 checksum** — standout custom recogniser), UK postcodes, dates, phone, email.
- **Gazetteer:** match names / site names from the patient & admission tables against the note text.
- **NER model:** catch PII *inline in the narrative* (PERSON, DATE, LOCATION) that rules miss.

### 3. Transform / De-identify (offer several; explain the utility trade-off)
- **Redaction** → `[PERSON]`, `[NHS_NUMBER]`
- **Surrogate replacement** → fake-but-realistic value (keeps text readable for downstream NLP)
- **Consistent pseudonymisation** → same patient → same token across all their notes (preserves the longitudinal journey) via a mapping vault
- **Date shifting** → shift each patient's dates by a consistent random offset (preserves intervals)

### 4. Validate / Risk-score
Output a **clean, training-ready dataset** + an **audit report** of what was removed + a **k-anonymity** re-identification risk score.

---

## Recommended engine: Microsoft Presidio

Don't build detection from scratch. **Presidio** is open-source, purpose-built for PII detection + anonymisation, runs fully on-prem (sovereign), and is extensible with custom recognisers — the de-facto open-source equivalent of GCP Sensitive Data Protection.

Our 48h work = add NHS-specific recognisers (NHS-number checksum, NHS org/site lists) + wire up the transforms. **spaCy / medspaCy** underneath for the NER layer.

---

## Evaluation (our "reliable" pillar — wins on measurable results)

The synthetic dataset has **known** PII (names/NHS numbers in the structured tables), so we can build ground-truth labels and report real numbers:

- **Precision / recall / F1 of PII detection, per entity type.**
- **Residual PII leakage rate** after de-identification.
- **Robustness to noise:** the dataset's injected **typos + abbreviations** degrade detection — report F1 *with vs without* them. "PII detection under realistic messy text" is a strong, honest result.

---

## Dataset

**NHSEDataScience/synthetic_clinical_notes** (Hugging Face) — NHS England's own synthetic dataset.

- ~70 synthetic patients (50 adult, 20 paediatric), 20–50 notes each, full admission→discharge journeys.
- **Deliberately injected typos + medical abbreviations** — the messiness is the test.
- Names / NHS numbers in the patient & admission tables → ground truth for the de-id eval.
- No FDP, no real data, no IG barrier. "We deliberately used synthetic data so it's shareable and governance-safe" is a strength.

---

## NHS England framing (credibility edge)

Adopt NHSE Data Science's own ethics scaffolding rather than inventing one. Four characteristics: **fair, transparent, value-adding, reliable.**

**Lighter governance artefacts (no heavy ML-model paperwork now):**
1. **Tool Card / datasheet** for NoteGuard
2. **Data Hazards assessment** (datahazards.com — NHSE applies it to every project)
3. **Five Safes mapping** (Safe Data: de-identify at source)

**NHSE siblings to cite hard** (NoteGuard is the productised, automated version): *Tool to Assess Privacy Risk of Text Data*; *Privacy of Unstructured Data*; *Emerging Privacy Enhancing Technologies (PETs)*; *SDE Service Data Wranglers — Reusable Data Validation Process* (literally the target role).

---

## 48-hour MVP

A small web UI:
**messy clinical note → highlighted detected PII (inspect) → choose a de-id transform → sanitised note out → detection F1 + leakage + k-anonymity score.**
Behind it: Presidio + NHS custom recognisers running against the synthetic dataset. The **detect → de-identify → score** loop is the demo that lands.

---

## Division of labour (suggested)

- **Person A:** Presidio engine + NHS custom recognisers (NHS-number checksum, gazetteers) + transforms (redaction/pseudonymisation/date-shift).
- **Person B:** Web UI demo + evaluation harness (precision/recall/F1, leakage rate, k-anonymity).
- **Shared / Chaeyoon (ethicist edge):** Tool Card, Data Hazards, Five Safes mapping, the pitch + architecture diagram.

---

## Why this wins (judging criteria check)

- ✅ Clear, relevant real-world use case (automated NHS de-identification preprocessing)
- ✅ Thoughtful use of privacy-preserving AI (sanitise-at-source; on-ramp to federated/collaborative AI)
- ✅ Strong technical implementation (layered detection, multiple transforms, robustness-to-noise eval)
- ✅ Attention to trust, governance, security (Five Safes, NHSE ethics, measurable leakage rate, audit log)
- ✅ Credible path to real-world adoption (open-source, on-prem, generalises to any jurisdiction; aligns to NHSE's own tooling)
