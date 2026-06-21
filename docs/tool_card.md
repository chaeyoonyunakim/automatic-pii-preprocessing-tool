# NoteGuard — Tool Card

**Version:** 0.0.1  
**Track:** Public Sector & Citizen Services — NHS Secure Data Environment on-ramp  
**Status:** Hackathon prototype; not validated for production use without further evaluation.

---

## Specification

| Field | Value |
|---|---|
| Description | De-identification gate that detects + removes PII from free-text NHS clinical notes |
| Type | Hybrid pipeline — pure-Python rules + Microsoft Presidio (spaCy `en_core_web_lg` NER). **No model is trained**; pre-trained components are composed. |
| Developer | Encode Club hackathon team (fork of `NoteGuard/`) |
| Status / version | Prototype · v0.0.1 |
| Repository | github.com/chaeyoonyunakim/automatic-pii-preprocessing-tool |

> Documented as a **tool card**, not a model card. NoteGuard trains no model, so the NHS England
> *model card* template's training / hyperparameter / data-split sections do not apply. A gov.uk
> Algorithmic Transparency Recording Standard (ATRS) record is provided in [`report.md`](report.md).

---

## What it does

NoteGuard is a **de-identification gate** for free-text NHS clinical notes. It detects and removes patient and clinician PII *inside* a Trust before any text reaches a Secure Data Environment (SDE), federated training round, or cross-Trust sharing layer.

> "AI detects, humans review, audit logs account."

---

## Who uses it

| Role | When | Why |
|---|---|---|
| Data Wrangler / IG Analyst | Before releasing notes to research or AI teams | Cannot share raw free-text; must prove zero identifier leakage |
| SDE Operator | At the Trust boundary ingestion point | Gate between Trust raw data and the shared pool |
| Federated AI Platform (e.g. FLock.io) | Before each training round | Needs de-identified text; cannot inspect raw Trust data |

---

## Use cases out of scope

- **Not** a substitute for Information Governance sign-off, a DPIA, or DARS approval — it is a
  technical control, not a legal basis for processing.
- **Not** validated on real Trust data, non-English notes, or scanned / handwritten documents.
- **Not** a guarantee of zero re-identification: pseudonymised output is still personal data, and
  residual leakage is *measured*, not assumed to be zero on unseen data.
- **Not** for clinical decision-making, or any use of note *content* beyond de-identification.

---

## Detection coverage

| Entity type | Method | Notes |
|---|---|---|
| Patient name (`PERSON`) | spaCy `en_core_web_lg` NER | 100% recall in benchmarks |
| NHS number (`UK_NHS`) | Regex + Modulus-11 checksum + 9-digit context anchor | Catches both standard and synthetic dataset forms |
| Date of birth (`DATE_TIME`) | Presidio + date regex | 100% recall |
| Site / hospital name (`LOCATION`) | spaCy NER + rule-based suffix anchor | "X Hospital / Infirmary / NHS Trust" patterns (ORGANIZATION is excluded — it over-tags labels) |
| UK postcode (`UK_POSTCODE`) | Regex | Outward-code only after pseudonymisation |
| Clinician GMC / NMC (`GMC`, `NMC`) | Context-anchored regex | "GMC 1234567", "NMC PIN 12A3456B" |
| ODS org code (`NHS_ODS`) | Context-anchored regex | "ODS A12345", "Practice Code A12345" |
| Record / document UUID (`RECORD_ID`) | UUID regex | Quasi-identifier |
| Email / phone / NINO | Presidio built-ins | Standard patterns |
| Nationality / religion / political (`NRP`) | Presidio | Always redacted; never pseudonymised (UK GDPR Art. 9) |

---

## Anonymisation policy

| Mode | Behaviour |
|---|---|
| **Pseudonymise** (default) | Faker(en_GB) realistic surrogates; stable per patient via Trust-local vault; date intervals preserved by consistent random shift |
| **Redact** | `[ENTITY_TYPE]` placeholder tags |
| `NRP` | Always redacted regardless of mode |

---

## Performance (`en_core_web_lg`)

| Entity | Recall |
|---|---|
| Names | 100% |
| NHS number | ~100% |
| Date of birth | 100% |
| Places / sites | improving (was low due to ORG/LOCATION mismatch — now fixed) |

**Residual leakage target:** 0 known identifiers surviving sanitisation (gates SDE pool admission).

---

## Bias and fairness

The `PERSON` NER (spaCy `en_core_web_lg`) is trained largely on Western / English text, so **name
recall can be lower for names of non-English origin**. This is an equity risk: under-detection means
those patients carry a *higher residual re-identification risk*. Honest position and mitigations:

- The checksum / context rules (NHS number, DOB, postcode, GMC/NMC/ODS, NINO) are **name-agnostic**,
  so structured identifiers are detected uniformly regardless of patient demographics.
- The **human review queue** surfaces low-confidence name spans for IG analyst confirmation.
- **Required before deployment:** evaluate name recall *stratified by name origin / ethnicity coding*
  on representative Trust data and report the disparity. Not yet done — evaluation is on synthetic data.

---

## Human-in-the-loop

Low-confidence detections (model score below auto-confirm threshold) are:
1. Still **redacted** for safety.
2. Flagged in the **review queue** with context snippet and confidence score.
3. Surfaced to an IG analyst for confirmation before the note enters the SDE pool.

This matches the real NHS Information Governance workflow and makes the tool's accountability explicit.

---

## NHS Five Safes mapping

| Safe | Status | How |
|---|---|---|
| **Safe data** | ✅ | De-identified to DAPB1523/ICO standard; leakage-gated |
| **Safe settings** | ✅ | Processing inside Trust; raw data and vault gitignored |
| **Safe outputs** | ✅ | Only de-identified text + content-free audit logs leave |
| **Safe people** | ⚠️ | IG analyst review queue; vault stays Trust-local; honest UK GDPR framing |
| **Safe projects** | ⚠️ | Technical layer only; DPIA + project approval (DARS) remain Trust processes |

---

## Limitations and caveats

- **Pseudonymised data is still personal data** under UK GDPR — the vault is the re-identification key and must stay Trust-local.
- **Precision is a conservative lower bound**: clinician names and unlisted locations correctly detected count as false positives in the evaluation (ground truth is patient-table-only).
- **Not clinically validated**: evaluated on the `NHSEDataScience/synthetic_clinical_notes` dataset. Real deployment requires validation on representative Trust data.
- **Clinical transformer models** (e.g. `obi/deid_roberta_i2b2`) were tested and performed worse on UK names than `en_core_web_lg` (i2b2 training data is US-centric).
- **Governance prerequisites for deployment:** a Data Protection Impact Assessment (DPIA), IG /
  Caldicott sign-off, and DARS project approval are required before any real use. NoteGuard is the
  technical control, not the approval.

---

## Adoption path

```
NHS Trust (raw notes)
    │
    ▼  NoteGuard gate (runs inside Trust)
    │
    ▼  de-identified notes + audit log
    │
    ▼  NHS SDE / FDP shared pool
    │
    ▼  Federated AI  (e.g. FLock.io)
```

Same privacy model as OpenSAFELY: *code comes to the data, data never leaves*.

---

*NoteGuard · Encode Club "Trusted Data & AI Infrastructure" hackathon · internal use only*
