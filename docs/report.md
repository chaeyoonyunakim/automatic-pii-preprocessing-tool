# Algorithmic Transparency Record — NoteGuard

> **Illustrative** record following the UK government [Algorithmic Transparency Recording Standard
> (ATRS)](https://www.gov.uk/government/collections/algorithmic-transparency-recording-standard-hub),
> modelled on the [NHS.UK Reviews Automoderation Tool record](https://www.gov.uk/algorithmic-transparency-records/nhs-england-nhs-dot-uk-reviews-automoderation-tool).
> NoteGuard is a hackathon **prototype** evaluated on synthetic data — this is not an official
> published ATRS entry, but is structured so it could become one.

## Tier 1 — Summary

- **Name:** NoteGuard — NHS clinical-note de-identification gate
- **Description:** Detects and removes patient/clinician PII from free-text NHS clinical notes
  *inside* a Trust, so only de-identified text leaves for a Secure Data Environment (SDE) or
  federated AI. Combines pure-Python rules with Microsoft Presidio (spaCy NER). No model is trained.
- **Website / repository:** https://github.com/chaeyoonyunakim/automatic-pii-preprocessing-tool
- **Contact:** via GitHub issues on the repository (maintainer **@chaeyoonyunakim**)

---

## Tier 2

### 1. Owner and responsibility
- **1.1 Organisation:** Encode Club "Trusted Data & AI Infrastructure" hackathon team (fork of `NoteGuard/`).
- **1.2 Team:** Project contributors (see repository history / `docs/CHANGELOG.md`).
- **1.3 Senior responsible owner:** None — prototype, not in service. An SRO would be required before deployment.
- **1.4 External supplier involvement:** No commercial supplier. Built on open-source components
  (Microsoft Presidio, spaCy `en_core_web_lg`, Faker).

### 2. Description and rationale
- **2.1 Detailed description:** A note is cleaned of mojibake, then scanned by a `RuleDetector`
  (checksum/context rules) unioned with a `PresidioDetector` (spaCy NER for `PERSON`/`LOCATION` +
  built-ins). Detected spans are removed by a transform — **redaction** (`[type]` tags) or
  **pseudonymisation** (realistic, patient-consistent Faker surrogates; valid fake NHS numbers;
  consistent date-of-birth shift). A content-free audit log records what was removed.
- **2.2 Scope:** Free-text English NHS clinical notes. Evaluated on the `NHSEDataScience/synthetic_clinical_notes`
  dataset only. Not evaluated on real Trust data, other languages, or scanned documents.
- **2.3 Benefit:** Enables cross-Trust / federated AI without sharing raw PHI ("sanitise at source"),
  with a **measured residual-leakage rate** rather than an unverified assurance.
- **2.4 Previous process:** Manual redaction by an analyst, or — more commonly — free-text notes simply
  not shared because the re-identification risk could not be quantified.
- **2.5 Alternatives considered:** Manual redaction (does not scale, inconsistent); Presidio alone
  (misses the dataset's 9-digit NHS numbers and UK staff/org identifiers); a clinical transformer
  (`obi/deid_roberta_i2b2`, tested — worse on UK names, US-trained). Rejected in favour of the
  rules + Presidio hybrid.

### 3. Decision-making process
- **3.1 Process integration:** Sits at the Trust egress boundary. It **supports** an IG decision and
  **automatically** removes high-confidence PII; low-confidence spans are still removed but flagged.
- **3.2 Information provided to reviewers:** entity type, confidence score, surrounding context snippet,
  and per-note audit counts (never raw values in the shareable log).
- **3.3 Frequency and scale:** Prototype, batch-oriented. Benchmarked on 1,602 notes / 1,027 known-PII
  occurrences.
- **3.4 Human decisions and review:** An IG analyst reviews the **review queue** (spans scored between
  the review and auto-confirm thresholds) and makes the **final** call before a note enters the SDE pool.
- **3.5 Required training:** Reviewers need training on the tool's limitations (esp. name-recall bias),
  the residual-leakage metric, and the escalation route.
- **3.6 Appeals / redress:** Not a citizen-facing decision system, so no external appeal. Internally,
  any missed identifier found downstream is corrected and fed back into the recogniser rules/tests.

### 4. Tool specification
- **4.1.1 System architecture:** Python package (`src/`) run **inside** the Trust; `RuleDetector` +
  `PresidioDetector` behind one `Detector` interface; Streamlit demo UI; deployable as a Docker
  Hugging Face Space. Raw notes and the re-identification vault never leave the Trust.
- **4.1.2 Phase:** Prototype (hackathon) — not deployed.
- **4.1.3 Maintenance:** CI (`ruff` + `pytest`) on every change; residual leakage acts as a regression
  gate; recognisers re-evaluated when the data or rules change.
- **4.1.4 Components:** (a) pure-Python rule recognisers; (b) Presidio analyzer with spaCy
  `en_core_web_lg` + custom UK recognisers; (c) Faker pseudonymisation vault.

**4.2 Component specifications**

| Component | Task | Method | Measured (synthetic, 1,602 notes) |
|---|---|---|---|
| Rule recognisers | NHS number, postcode, date, phone, email, GMC/NMC/ODS, NINO, vehicle, UUID | regex + Modulus-11 checksum + context anchors (name-agnostic) | NHS number F1 ≈ 0.99 |
| Presidio NER | `PERSON`, `LOCATION` | spaCy `en_core_web_lg`, score-thresholded, unioned with rules | PERSON recall ≈ 0.68 |
| Transform | redact / pseudonymise | per-entity policy; Faker(en_GB) vault; per-patient DOB shift | — |
| **End-to-end** | residual leakage after sanitisation | known-PII oracle from structured tables | **rules 74.8% → presidio+rules 8.5%** |

Precision is a conservative lower bound (correctly removing PII absent from the tables counts as a
false positive). Recall and leakage are the sound headline metrics.

**4.3 Data specification**
- **4.3.1 Source:** `NHSEDataScience/synthetic_clinical_notes` (Hugging Face).
- **4.3.2 Modality:** Text (3 linked CSVs: patients, admissions, notes).
- **4.3.3 Description:** Synthetic clinical notes joined to synthetic patient/admission records on
  `person_id` / `admission_id` — the join provides free ground truth for the leakage metric (EVAL-ONLY).
- **4.3.4 Quantities:** ~70 patients, ~1,602 notes, 1,027 known-PII occurrences.
- **4.3.5 Sensitive attributes:** Synthetic names, NHS numbers, DOBs, sites — treated as if real PHI.
- **4.3.6 Representativeness:** Synthetic; not representative of real Trust notes. Real validation required.
- **4.3.7 Source URL:** https://huggingface.co/datasets/NHSEDataScience/synthetic_clinical_notes
- **4.3.8 Collection:** Generated synthetically by NHS England Data Science; downloaded at runtime.
- **4.3.9 Cleaning:** mojibake repair (`ftfy`/`_fix_mojibake`); Modulus-11 validation; table joins.
- **4.3.10 Sharing:** Only de-identified text + content-free audit logs are shareable. Raw data and the
  vault are gitignored and never committed/shared.
- **4.3.11 Access/storage:** Local to the Trust; `data/` and `outputs/` are gitignored.

### 5. Risks, mitigations and impact assessments
- **5.1 Impact assessment:** A **DPIA is required before any real deployment** and has **not** been done
  (prototype on synthetic data). IG / Caldicott sign-off and DARS approval also required.
- **5.2 Risks and mitigations:**

| Risk | Impact | Mitigation |
|---|---|---|
| False negative (missed PII) | Re-identification of a patient | Name-agnostic checksum/context rules; human review queue; leakage measured and gated; recall stratification recommended |
| **Name-recall bias** (non-English names) | Unequal re-identification risk across demographics | Structured-identifier rules are demographic-agnostic; human review; **stratified recall evaluation required** before deployment |
| Over-redaction (false positive) | Loss of clinical utility | Pseudonymise mode preserves structure & timelines; precision reported as a conservative bound |
| Vault compromise | Re-identification via the linkage key | Vault stays Trust-local, gitignored; treated as the re-identification key |
| Pseudonymised ≠ anonymised (UK GDPR) | Mistaken belief data is non-personal | Stated honestly throughout; DPIA + IG sign-off required |
| Pretrained-component provenance | No control over Presidio/spaCy training data | Composed with auditable rules + human review; alternatives documented |

---

*NoteGuard · Encode Club "Trusted Data & AI Infrastructure" hackathon · prototype · v0.0.1*
