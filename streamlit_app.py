"""NoteGuard — demo UI.

Run from the repo root:  streamlit run streamlit_app.py

Try-it (detect & sanitise) · Metrics & leakage · Governance (Five Safes) · Two-Trust sharing.
Built on the NoteGuard package (src/) — pluggable detectors + patient-consistent transforms.
"""
from __future__ import annotations

import html
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from src.data import load_notes  # noqa: E402
from src.detect import build_detector  # noqa: E402
from src.evaluate import evaluate  # noqa: E402
from src.pipeline import Pipeline  # noqa: E402
from src.transform import PSEUDONYM, REDACTION, PseudonymVault  # noqa: E402

OUT_DIR = REPO / "outputs"
RESULTS = REPO / "outputs" / "results.json"

ENTITY_COLORS = {
    "PERSON": "#ffd6e0", "UK_NHS": "#ffe9b3", "DATE_TIME": "#d4f4dd", "UK_POSTCODE": "#cfe8ff",
    "LOCATION": "#cfe8ff", "ORGANIZATION": "#cfe8ff", "RECORD_ID": "#ffd9c2",
    "PHONE_NUMBER": "#d4f4dd", "EMAIL_ADDRESS": "#d4f4dd",
    "UK_NINO": "#ffe9b3", "GMC": "#f0e0a0", "NMC": "#f0e0a0", "NHS_ODS": "#f0e0a0",
}

st.set_page_config(page_title="NoteGuard", page_icon="🛡️", layout="wide")


@st.cache_resource(show_spinner="Loading the de-identification engine + sample notes…")
def load_engine():
    detector = build_detector(use_presidio=True)
    try:
        notes = load_notes(limit=50)
    except Exception:
        notes = []
    return detector, notes


def highlight(text: str, spans) -> str:
    chosen, last_end = [], -1
    for s in sorted(spans, key=lambda s: (s.start, -(s.end - s.start))):
        if s.start >= last_end:
            chosen.append(s)
            last_end = s.end
    out, idx = [], 0
    for s in chosen:
        out.append(html.escape(text[idx:s.start]))
        color = ENTITY_COLORS.get(s.entity_type, "#e0e0e0")
        border = "2px dashed #e67e00" if s.needs_review else "none"
        out.append(
            f'<mark style="background:{color};padding:0 2px;border-radius:3px;border:{border}" '
            f'title="{s.entity_type} ({s.score:.2f}){" ⚠ review" if s.needs_review else ""}'
            f'">{html.escape(text[s.start:s.end])}</mark>'
        )
        idx = s.end
    out.append(html.escape(text[idx:]))
    return "".join(out).replace("\n", "<br>")


def scroll_box(inner_html: str, height: int = 340):
    st.markdown(
        f'<div style="height:{height}px;overflow:auto;border:1px solid #ddd;border-radius:8px;'
        f'padding:12px;font-family:ui-monospace,monospace;font-size:13px;line-height:1.5">{inner_html}</div>',
        unsafe_allow_html=True,
    )


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


st.title("🛡️ NoteGuard — NHS De-Identification Gate")
st.caption("AI detects patient and clinician PII, humans review, audit logs account.")

detector, NOTES = load_engine()

tab_try, tab_metrics, tab_gov, tab_trust = st.tabs(
    ["🔎 Try it", "📊 Metrics & Leakage", "🏛️ Governance (Five Safes)", "🤝 Two-Trust sharing"]
)

# ---------------------------------------------------------------- Try it
with tab_try:
    st.markdown(
        "Paste a clinical note and see what the gate detects, removes, and flags for human review "
        "before the text is allowed into the SDE pool."
    )
    c1, c2 = st.columns([3, 2])
    with c2:
        method = st.radio("Transform", [PSEUDONYM, REDACTION],
                          format_func=lambda m: "Pseudonymise (realistic, patient-consistent)"
                          if m == PSEUDONYM else "Redact ([TYPE] tags)")
        source = st.radio("Input", ["Sample note", "Paste your own"])
    with c1:
        if source == "Sample note" and NOTES:
            idx = st.number_input("Note index", 1, len(NOTES), 1, step=1)
            rec = NOTES[int(idx) - 1]
            text, person_id, note_id = rec.text, rec.person_id, rec.note_id
        else:
            text = st.text_area("Clinical note (messy free-text)", height=200,
                                value="Pt John Smith, NHS no 943 476 5919, DOB 02/03/1981, lives SW1A 1AA. "
                                      "Admitted Manchester Royal Infirmary Ward 9. "
                                      "Reviewed by Dr Lee, GMC 1234567.")
            person_id, note_id = "demo", "pasted"

    if text.strip():
        result = Pipeline(detector, PseudonymVault()).sanitise(text, method, person_id)

        st.markdown("##### 1) Detected PII")
        scroll_box(highlight(text, result.spans))

        st.markdown(f"##### 2) Sanitised output — `{method}`")
        scroll_box(html.escape(result.sanitised).replace("\n", "<br>"))

        st.markdown("##### 3) Audit log (counts only — no raw values leave the gate)")
        confirmed = [s for s in result.spans if not s.needs_review]
        counts = Counter(s.entity_type for s in confirmed)
        st.dataframe({"entity": list(counts), "auto-removed": list(counts.values())},
                     hide_index=True, use_container_width=True)

        if result.review_items:
            st.warning(
                f"**Human review required — {len(result.review_items)} low-confidence detection(s)**\n\n"
                "These spans were redacted for safety but the model's confidence was below the "
                "auto-confirm threshold. An IG analyst should confirm before the note enters the SDE pool.",
                icon="⚠️",
            )
            for s in result.review_items:
                context_start = max(0, s.start - 40)
                context_end = min(len(text), s.end + 40)
                ctx = text[context_start:context_end].replace("\n", " ")
                st.markdown(
                    f"- **`{s.entity_type}`** · score `{s.score:.2f}` · "
                    f'…{html.escape(ctx[:s.start - context_start])}'
                    f'**_{html.escape(s.text)}_**'
                    f'{html.escape(ctx[s.end - context_start:])}…'
                )
        else:
            st.success("All detections auto-confirmed (score ≥ threshold). No human review needed.", icon="✅")

        st.markdown("##### 4) Download this de-identified note")
        one = [{"note_id": note_id, "method": method, "sanitised_text": result.sanitised}]
        d1, d2 = st.columns(2)
        d1.download_button("⬇ Download JSON", json.dumps(one, ensure_ascii=False, indent=2),
                           file_name="noteguard_note.json", mime="application/json",
                           use_container_width=True)
        d2.download_button("⬇ Download CSV", pd.DataFrame(one).to_csv(index=False),
                           file_name="noteguard_note.csv", mime="text/csv",
                           use_container_width=True)

    st.divider()
    with st.expander("⬇ Download the full de-identified dataset"):
        st.caption("De-identify a batch of notes and export **only the sanitised text** — "
                   "the original PHI never leaves the gate.")
        ca, cb = st.columns([3, 1])
        n_all = ca.slider("Notes to de-identify", 50, 1600, 200, step=50, key="dataset_n")
        if cb.button("Prepare", use_container_width=True):
            with st.spinner(f"De-identifying {n_all} notes…"):
                pipe = Pipeline(detector, PseudonymVault())  # one vault → patient-consistent
                rows = [{"note_id": r.note_id, "method": method,
                         "sanitised_text": pipe.sanitise(r.text, method, r.person_id).sanitised}
                        for r in load_notes(limit=n_all) if r.text]
                st.session_state["dataset_rows"] = rows
        rows = st.session_state.get("dataset_rows")
        if rows:
            st.success(f"{len(rows)} notes de-identified — ready to download.")
            e1, e2 = st.columns(2)
            e1.download_button("⬇ Download JSON", json.dumps(rows, ensure_ascii=False, indent=2),
                               file_name="noteguard_dataset.json", mime="application/json",
                               use_container_width=True)
            e2.download_button("⬇ Download CSV", pd.DataFrame(rows).to_csv(index=False),
                               file_name="noteguard_dataset.csv", mime="text/csv",
                               use_container_width=True)

# ---------------------------------------------------------------- Metrics
with tab_metrics:
    st.markdown(
        "**Leakage rate** is the headline SDE gate metric: after sanitisation, what fraction of known "
        "patient identifiers still appear in the output text? Ground truth is **joined from the "
        "dataset's structured tables** — every note's identifiers are known in advance, so this is "
        "a real, measurable re-identification risk, not an estimate."
    )
    st.markdown(
        "> **Target for SDE admission:** leakage = 0. Any note with a non-zero leakage score "
        "must be held back from the shared pool until reviewed."
    )
    data = load_json(RESULTS)
    n = st.slider("Notes to evaluate (live run)", 50, 1000, 200, step=50)
    if st.button("▶ Run evaluation"):
        with st.spinner("Evaluating…"):
            recs = load_notes(limit=n)
            res = evaluate(recs, detector, PSEUDONYM).to_dict()
            data = {"presidio+rules": res}
            RESULTS.write_text(json.dumps(data, indent=2), encoding="utf-8")

    if data:
        name = "presidio+rules" if "presidio+rules" in data else next(iter(data))
        r = data[name]
        leak = r["leakage"]["leakage_rate_pct"]
        m1, m2, m3 = st.columns(3)
        m1.metric("Identifiers removed", f"{100 - leak:.1f}%", help="Known PII not present in output")
        m2.metric("Residual leakage", f"{leak:.2f}%",
                  delta=f"{leak:.2f}%" if leak > 0 else None,
                  delta_color="inverse",
                  help="Fraction of known PII surviving sanitisation — target: 0%")
        m3.metric("Notes evaluated", r["notes_evaluated"])
        st.markdown("##### Detection recall by entity type")
        pe = r["detection"]["per_entity"]
        st.dataframe(
            {"entity": list(pe),
             "recall": [f"{m['recall']:.0%}" for m in pe.values()],
             "precision": [f"{m['precision']:.0%}" for m in pe.values()],
             "support": [m["support"] for m in pe.values()]},
            hide_index=True, use_container_width=True,
        )
        st.caption(
            "Precision is a conservative lower bound. Clinician names and unlisted locations "
            "detected correctly are counted as false positives."
        )
    else:
        st.info("No metrics yet — click **Run evaluation** above.")

# ---------------------------------------------------------------- Governance
with tab_gov:
    st.markdown("### NHS Five Safes — How NoteGuard maps")
    st.markdown(
        "The Five Safes framework is the standard NHS governance model for data access. "
        "NoteGuard is designed as the **Safe Data** layer that makes the other four safes cheaper to achieve."
    )

    five_safes = [
        ("✅ Safe Data",
         "DAPB1523 / ICO standard",
         "Names · NHS number · DOB · postcode → outward code · "
         "GMC/NMC clinician IDs · ODS org codes · record UUIDs · site names. "
         "NRP (nationality/religion) always redacted, never pseudonymised (UK GDPR Art. 9)."),
        ("✅ Safe Settings",
         "Processing inside the Trust",
         "Detection and sanitisation run locally. Raw notes, vault (re-id key), and CSVs "
         "are gitignored and never leave the Trust boundary. Only de-identified text is exported."),
        ("✅ Safe Outputs",
         "Leakage-gated release",
         "Residual leakage is measured against ground-truth identifiers before any note enters "
         "the SDE pool. Target: 0 known identifiers surviving sanitisation. "
         "Low-confidence spans are held in a human review queue rather than auto-released."),
        ("⚠️ Safe People",
         "Human-in-the-loop required",
         "The re-identification vault stays Trust-local. Pseudonymised data is still personal "
         "data under UK GDPR (stated honestly — no over-claim of anonymisation). "
         "An IG analyst reviews low-confidence detections before pool admission."),
        ("⚠️ Safe Projects",
         "Project-level approval not covered here",
         "NoteGuard provides the technical de-identification layer; "
         "project-level data access approval (Data Access Request / DARS) remains a Trust process."),
    ]
    for safe, standard, detail in five_safes:
        with st.expander(f"**{safe}** — {standard}"):
            st.markdown(detail)

    st.divider()
    st.markdown("### Adoption path — NHS SDE on-ramp")
    st.markdown("""
```
NHS Trust (raw notes)
    │
    ▼  NoteGuard gate (runs inside Trust)
    │   clean → detect PII → sanitise → leakage check
    │   low-confidence spans → IG analyst review queue
    │
    ▼  de-identified notes + audit log  (no PHI crosses boundary)
    │
    ▼  NHS Secure Data Environment / Federated Data Platform pool
    │   (same model as OpenSAFELY: code comes to data, data never leaves)
    │
    ▼  Federated AI training
        each Trust trains locally; only model gradients are shared
```
    """)

# ---------------------------------------------------------------- Two-Trust
with tab_trust:
    st.markdown(
        "### Sanitise-at-source: two Trusts sharing without sharing\n\n"
        "Each Trust runs the NoteGuard gate locally — raw notes and the re-identification vault "
        "**never leave**. Only de-identified text and a content-free audit manifest go into the "
        "shared SDE pool. This is the same privacy model behind OpenSAFELY and the NHS Federated "
        "Data Platform: *code comes to the data, data never leaves*."
    )
    summary = load_json(OUT_DIR / "trust_demo_summary.json")
    if st.button("▶ Run two-Trust demo"):
        from src.trust_demo import main as run_trust
        with st.spinner("Sanitising at each Trust…"):
            run_trust()
        summary = load_json(OUT_DIR / "trust_demo_summary.json")

    if summary:
        cols = st.columns(len(summary["trusts"]) + 1)
        for col, t in zip(cols, summary["trusts"], strict=False):
            with col:
                st.markdown(f"#### 🏥 {t['trust'].split('(')[0].strip()}")
                st.metric("Notes de-identified", t["notes_deidentified"])
                st.metric("Raw records shared", t["raw_records_shared"])
                st.metric("Residual leaks", t["residual_leaks"])
                st.caption("🔒 raw notes + vault stay local")
        with cols[-1]:
            st.markdown("#### 🟢 Shared SDE pool")
            st.metric("De-identified notes", summary["shared_pool_size"])
            st.metric("Raw records shared", summary["raw_records_shared"])
            st.metric("Total residual leaks", summary["total_residual_leaks"])
            st.caption("→ ready for federated AI training")
    else:
        st.info("Click **Run two-Trust demo** above.")

# ---------------------------------------------------------------- Footer (all tabs)
st.divider()
st.caption(
    "Live demo for the **FLock Sovereign AI Challenge** at the Encode Vibe Coding Hackathon, "
    "hosted by Encode Hub."
)
