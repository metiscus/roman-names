# Project Progress Log

## Week 1: Data Acquisition and Verification (May 2026)

### Status: Complete

**Goal:** Acquire datasets and verify ground-truth APIs for validation.

### Accomplishments
- **Environment Setup:** Python virtual environment initialized with `pandas`, `geopandas`, `requests`, `anthropic`, `google-genai`, and `tqdm`.
- **Data Acquisition:** Automated download of EDCS 2022 (465MB JSON) and LIRE (576MB GeoJSON) from Zenodo.
- **Ground Truth Discovery:** LIRE contains structured `people` data for 136,190 inscriptions, including 483 in Africa Proconsularis with at least one named individual. Pivoted validation strategy from Trismegistos APIs to LIRE people data.
- **Exploratory Data Analysis:** Africa Proconsularis has 33,713 EDCS records total; ~31,000 lack structured name data and are targets for extraction.

---

## Week 2: NER Pipeline and Evaluation (May 2026)

### Status: Complete

**Goal:** Build and validate the NER extraction pipeline against LIRE ground truth.

### Accomplishments

**Pipeline:**
- Built batched NER runner (`04c_run_ner_batched.py`) using Gemini 2.5 Flash with structured Pydantic output. Batches 10 inscriptions per API call.
- Disabled thinking tokens (`thinking_budget: 0`) — same output quality, ~5 min for 433 records, significantly lower cost.
- Added damage pre-filter: inscriptions where >30% of characters are inside lacunae brackets (`[---]`) are skipped before sending to the API.

**Evaluation harness (`05_evaluate_ner.py`):**
- Praenomen expansion table (19 standard Latin abbreviations) — LIRE stores `Q.`, model expands to `Quintus`; without this, 32% of GT people would never match.
- Word-overlap matching with 6-char prefix comparison replaces substring matching — handles extra cognomina in predictions and Latin case ending variants.
- Imperial name filter (two-stage): status keyword matching + inscription-level formula detection removes emperors/imperial family from the discoveries list.
- Damaged name tracking: separates unanswerable FNs (lacunae) from genuine model misses in the summary.

**Results (433-record Africa Proconsularis eval set, 854 GT people):**

| Metric | Value |
|--------|-------|
| Recall (raw) | 0.71 |
| Recall (adjusted, excl. damaged) | 0.93 |
| Precision (adjusted) | 0.73 |
| F1 (adjusted) | 0.82 |
| Potential discoveries (non-imperial) | 226 |

**Key finding:** 199/304 false negatives (65%) are inscriptions where the GT name is in lacunae — unrecoverable from raw text. Adjusted recall of 0.93 is the honest performance measure.

### Next Steps
- Manual review of top discoveries: sample ~50 from the 226 to estimate true precision of the discoveries list.
- Scale to full undamaged Africa Proconsularis corpus (~31k records without LIRE GT coverage).
- Outreach to Petra Heřmánková (SDAM/LIRE) and Mark Depauw (TM) with pilot results once discoveries are spot-checked.
- Long-term: Ithaca-style lacuna restoration (cf. Assael et al., *Nature* 2022) to recover damaged records — separate research direction.
