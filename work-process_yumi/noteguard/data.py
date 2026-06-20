"""Load the NHSE synthetic clinical notes dataset and build per-note ground truth.

The dataset ships three CSVs that share keys:
  patients.csv    person_id, full_name, nhs_number, date_of_birth, ...
  admissions.csv  admission_id, patient_name/first_name/surname, site_name, ward, ...
  notes.csv       clinical_note_id, clean_note_text, person_id, admission_id, ...

Because the PII lives in the *structured* tables, we get ground-truth labels for
free: for each note we join back to the patient/admission rows and collect the
known PII strings that *should* be removed. That join is what makes a real,
measurable leakage rate possible — the thing Presidio alone never gives you.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd

REPO_ID = "NHSEDataScience/synthetic_clinical_notes"


# --- entity types we align to Presidio's vocabulary -------------------------
PERSON = "PERSON"
UK_NHS = "UK_NHS"
DATE = "DATE_TIME"
LOCATION = "LOCATION"


@dataclass(frozen=True)
class GroundTruthPII:
    """One known PII value that should not survive sanitisation."""
    text: str
    entity_type: str


@dataclass
class NoteRecord:
    note_id: str
    person_id: str
    admission_id: str
    text: str
    note_type: str = ""
    note_subject: str = ""
    # known PII strings for THIS note, derived from the structured tables
    ground_truth: list[GroundTruthPII] = field(default_factory=list)


def _fix_mojibake(s: str) -> str:
    """Repair the known UTF-8-as-latin-1 decoding defect (e.g. 'Â·' -> '·')."""
    if not s or ("Â" not in s and "Ã" not in s):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def _first_col(df: pd.DataFrame, *candidates: str) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _download_csvs(local_dir: str | None = None) -> dict[str, str]:
    """Discover and fetch the three CSVs from the HF dataset repo.

    Returns a dict {"patients"|"admissions"|"notes": local_path}.
    """
    from huggingface_hub import hf_hub_download, list_repo_files

    files = [f for f in list_repo_files(REPO_ID, repo_type="dataset") if f.endswith(".csv")]
    picked: dict[str, str] = {}
    for f in files:
        name = f.lower()
        if "patient" in name and "patients" not in picked:
            picked["patients"] = f
        elif "admission" in name:
            picked["admissions"] = f
        elif "note" in name:
            picked["notes"] = f
    missing = {"patients", "admissions", "notes"} - picked.keys()
    if missing:
        raise RuntimeError(
            f"Could not locate {missing} CSVs in {REPO_ID}. Found: {files}"
        )
    out: dict[str, str] = {}
    for key, repo_path in picked.items():
        out[key] = hf_hub_download(
            REPO_ID, repo_path, repo_type="dataset", local_dir=local_dir
        )
    return out


@lru_cache(maxsize=1)
def load_tables(local_dir: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (patients, admissions, notes) DataFrames.

    Honours NOTEGUARD_DATA_DIR (a folder holding the three CSVs) so the demo can
    run fully offline once the data is cached.
    """
    data_dir = local_dir or os.environ.get("NOTEGUARD_DATA_DIR")
    if data_dir and os.path.isdir(data_dir):
        def _read(*names):
            for n in names:
                p = os.path.join(data_dir, n)
                if os.path.exists(p):
                    return pd.read_csv(p, dtype=str, keep_default_na=False)
            raise FileNotFoundError(f"None of {names} in {data_dir}")
        patients = _read("patients.csv")
        admissions = _read("admissions.csv")
        notes = _read("synthetic_clinical_notes.csv", "notes.csv")
    else:
        paths = _download_csvs(local_dir=local_dir)
        patients = pd.read_csv(paths["patients"], dtype=str, keep_default_na=False)
        admissions = pd.read_csv(paths["admissions"], dtype=str, keep_default_na=False)
        notes = pd.read_csv(paths["notes"], dtype=str, keep_default_na=False)
    return patients, admissions, notes


# generic values that are not identifying on their own — never treat as PII GT
_GENERIC = {
    "ward", "bay", "bed", "unit", "unknown", "none", "n/a", "na",
    "male", "female", "trust", "hospital", "patient", "nil",
}


def _gt_from_row(row: pd.Series, df: pd.DataFrame, mapping: dict[str, str]) -> list[GroundTruthPII]:
    out: list[GroundTruthPII] = []
    for col, etype in mapping.items():
        actual = _first_col(df, col)
        if actual is None:
            continue
        val = _fix_mojibake(str(row.get(actual, "")).strip())
        if not val or val.lower() in _GENERIC or len(val) < 2:
            continue
        out.append(GroundTruthPII(val, etype))
    return out


# which structured columns map to which entity type
PATIENT_PII = {
    "full_name": PERSON,
    "nhs_number": UK_NHS,
    "date_of_birth": DATE,
}
ADMISSION_PII = {
    "patient_name": PERSON,
    "first_name": PERSON,
    "surname": PERSON,
    "full_name": PERSON,
    "nhs_number": UK_NHS,
    "date_of_birth": DATE,
    "site_name": LOCATION,
    "ward": LOCATION,
    "bed_location": LOCATION,
}


def load_notes(limit: int | None = None, local_dir: str | None = None) -> list[NoteRecord]:
    """Build NoteRecords with ground-truth PII joined from patient/admission tables."""
    patients, admissions, notes = load_tables(local_dir=local_dir)

    pid_col = _first_col(patients, "person_id")
    patients_idx = patients.set_index(pid_col) if pid_col else None

    aid_col = _first_col(admissions, "admission_id")
    admissions_idx = admissions.set_index(aid_col) if aid_col else None

    text_col = _first_col(notes, "clean_note_text", "note_text", "text")
    n_pid = _first_col(notes, "person_id", "patient_id")
    n_aid = _first_col(notes, "admission_id")
    nid_col = _first_col(notes, "clinical_note_id", "note_id")
    ntype = _first_col(notes, "note_type")
    nsubj = _first_col(notes, "note_subject")

    records: list[NoteRecord] = []
    rows = notes if limit is None else notes.head(limit)
    for _, r in rows.iterrows():
        pid = str(r.get(n_pid, "")) if n_pid else ""
        aid = str(r.get(n_aid, "")) if n_aid else ""
        gt: list[GroundTruthPII] = []
        if patients_idx is not None and pid in patients_idx.index:
            prow = patients_idx.loc[pid]
            if isinstance(prow, pd.DataFrame):
                prow = prow.iloc[0]
            gt += _gt_from_row(prow, patients, PATIENT_PII)
        if admissions_idx is not None and aid in admissions_idx.index:
            arow = admissions_idx.loc[aid]
            if isinstance(arow, pd.DataFrame):
                arow = arow.iloc[0]
            gt += _gt_from_row(arow, admissions, ADMISSION_PII)

        # dedupe on (text, type)
        gt = list({(g.text, g.entity_type): g for g in gt}.values())

        records.append(
            NoteRecord(
                note_id=str(r.get(nid_col, "")) if nid_col else "",
                person_id=pid,
                admission_id=aid,
                text=_fix_mojibake(str(r.get(text_col, ""))) if text_col else "",
                note_type=str(r.get(ntype, "")) if ntype else "",
                note_subject=str(r.get(nsubj, "")) if nsubj else "",
                ground_truth=gt,
            )
        )
    return records


if __name__ == "__main__":
    recs = load_notes(limit=5)
    for rec in recs:
        print(f"\n=== note {rec.note_id} (person {rec.person_id}) ===")
        print(rec.text[:200].replace("\n", " "), "...")
        print("  ground-truth PII:", [(g.text, g.entity_type) for g in rec.ground_truth])
