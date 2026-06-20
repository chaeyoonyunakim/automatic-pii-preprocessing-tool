"""NoteGuard demo UI.

The demo that lands: messy clinical note -> highlighted detected PII (inspect) ->
choose a de-identification transform -> sanitised note out -> audit + the
dataset-level residual-leakage numbers behind it.

    python app.py
"""
from __future__ import annotations

import json
import os

import gradio as gr

from noteguard.data import load_notes
from noteguard.pipeline import Pipeline
from noteguard.transform import PSEUDONYM, REDACTION, PseudonymVault

# ---- load engine + a few sample notes once ---------------------------------
print("[noteguard] loading detection engine (Presidio + spaCy) ...")
PIPELINE = Pipeline()
print("[noteguard] loading sample notes ...")
try:
    SAMPLES = load_notes(limit=40)
except Exception as e:  # pragma: no cover
    print(f"[noteguard] could not load dataset samples ({e}); paste-only mode.")
    SAMPLES = []

SAMPLE_CHOICES = [
    f"{i}: {(s.note_type or 'note')} — {s.text[:48].strip()}…"
    for i, s in enumerate(SAMPLES) if s.text
]


def _highlight(text: str, spans) -> dict:
    return {
        "text": text,
        "entities": [
            {"entity": s.entity_type, "start": s.start, "end": s.end} for s in spans
        ],
    }


def load_sample(choice: str) -> tuple[str, str]:
    if not choice:
        return "", ""
    idx = int(choice.split(":", 1)[0])
    rec = SAMPLES[idx]
    return rec.text, rec.person_id


def run(text: str, method_label: str, person_id: str):
    method = PSEUDONYM if method_label.startswith("Pseudonym") else REDACTION
    # fresh vault per run so the demo is reproducible
    PIPELINE.vault = PseudonymVault()
    result = PIPELINE.sanitise(text or "", method, person_id or "demo")

    highlighted = _highlight(text or "", result.spans)
    by_type = result.audit.get("by_type", {})
    audit_md = "\n".join(f"- **{k}**: {v}" for k, v in sorted(by_type.items())) or "_none detected_"
    audit_md = (
        f"**Detector:** `{result.audit['detector']}`  \n"
        f"**Transform:** `{method}`  \n"
        f"**Entities removed:** {result.audit['entities_removed']}\n\n"
        f"{audit_md}"
    )
    return highlighted, result.sanitised, audit_md


_PII_LABEL = {"UK_NHS": "NHS number", "PERSON": "Name", "DATE_TIME": "Date of birth"}


def metrics_panel() -> str:
    if not os.path.exists("results.json"):
        return "_Run `python run_eval.py --limit 500` to populate metrics._"
    with open("results.json") as f:
        data = json.load(f)
    # show the shipping detector (NER model + rules)
    name = "presidio+rules" if "presidio+rules" in data else next(iter(data))
    r = data[name]
    notes = r["notes_evaluated"]
    leak = r["leakage"]["leakage_rate_pct"]
    removed = round(100 - leak, 2)
    pe = r["detection"]["per_entity"]

    rows = ["| PII type | Detected (recall) | occurrences |", "|---|---|---|"]
    for et in ("UK_NHS", "PERSON", "DATE_TIME"):
        m = pe.get(et)
        if m and m["support"] > 0:
            rows.append(f"| {_PII_LABEL.get(et, et)} | {m['recall']:.0%} | {m['support']} |")
    return (
        f"### 📊 Measured on {notes} NHSE synthetic notes\n\n"
        f"## ✅ Removed **{removed}%** of known identifiers\n"
        f"_residual re-identification risk: **{leak}%** leakage_\n\n"
        + "\n".join(rows)
        + "\n\n_Ground truth is joined from the dataset's structured patient / "
          "admission tables, so the leakage rate is a real, measurable "
          "re-identification risk — not an estimate._"
    )


with gr.Blocks(title="NoteGuard") as demo:
    gr.Markdown(
        "# 🛡️ NoteGuard\n"
        "**Automatic PII sanitisation for NHS clinical notes — clean data in, no "
        "identifiers out.** Sanitise-at-source so institutions can collaborate "
        "(incl. federated training) without ever sharing raw PII."
    )
    person_state = gr.State("")
    with gr.Row():
        with gr.Column(scale=1):
            sample_dd = gr.Dropdown(SAMPLE_CHOICES, label="Load a sample NHSE note",
                                    value=SAMPLE_CHOICES[0] if SAMPLE_CHOICES else None)
            note_in = gr.Textbox(label="Clinical note (messy free-text)", lines=14,
                                 placeholder="Paste a clinical note…")
            method = gr.Radio(
                ["Redaction → [PERSON]", "Pseudonymisation (patient-consistent + date-shift)"],
                value="Redaction → [PERSON]", label="De-identification transform",
            )
            run_btn = gr.Button("Detect & sanitise", variant="primary")
        with gr.Column(scale=1):
            highlighted = gr.HighlightedText(label="1) Detected PII (inspect)")
            sanitised = gr.Textbox(label="2) Sanitised note (training-ready)", lines=10)
            audit = gr.Markdown(label="3) Audit")

    gr.Markdown("---")
    with gr.Row():
        gr.Markdown("## 📊 Dataset-level metrics")
        refresh_btn = gr.Button("🔄 Refresh from results.json", scale=0)
    metrics_md = gr.Markdown(metrics_panel())

    sample_dd.change(load_sample, sample_dd, [note_in, person_state])
    run_btn.click(run, [note_in, method, person_state], [highlighted, sanitised, audit])
    refresh_btn.click(metrics_panel, None, metrics_md)

    # re-read results.json on every page load so the panel never shows a stale snapshot
    demo.load(metrics_panel, None, metrics_md)
    if SAMPLE_CHOICES:
        demo.load(load_sample, sample_dd, [note_in, person_state])


if __name__ == "__main__":
    demo.launch()
