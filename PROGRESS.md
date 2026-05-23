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

---

## Week 3: Pre-Run Quality Pass (May 2026)

### Status: Complete

**Goal:** Catch and fix systemic errors before launching the full ~33k corpus run.

### Issues found and fixed

**1. Prompt rules (caught via domain-expert spot review):**
- Restricted praenomen field to the 18 canonical Latin praenomina; nomina like Iulius, Flavius, Aurelius were being misclassified as praenomina.
- Added list of 35 Roman voting tribes (Quirina, Arnensis, Papiria, etc.); these were being misfiled as nomina.
- Added rule: single-name individuals default to cognomen, not nomen.
- Added Pydantic `model_post_init` guard to strip gender values (`male`, `female`) that occasionally leaked into name fields.
- Added `fragmentary: bool` flag for visibly incomplete names.

**2. Literal "null" strings:**
- The model occasionally emits the string `"null"` instead of JSON null for empty fields (~2% of persons). Coerced to `None` in `model_post_init`.

**3. Multi-cognomen splitting:**
- Roman women's names with agnomen (`Aemilia Victoria Fipiorina`) were being split into two persons. Added NAME COHERENCE rule + few-shot example to prompt: consecutive name elements without a separator (`et`, `cum`, filiation, verbs) belong to one person.

**4. Damage filter was a silent no-op:**
- `damage_ratio()` counts `[...]` lacuna brackets — but the input field `clean_text_interpretive_word` has all brackets stripped. The 30% damage threshold was filtering zero records out of 33k. Would have filtered ~5,600 if computed on the raw `inscription` field.

**5. Hallucinated names from interpretive fill-ins:**
- A 30-record A/B test (`scripts/test_inscription_vs_clean.py`) compared feeding the model `clean_text_interpretive_word` (lacunae filled in) vs raw `inscription` (with brackets). Raw inscription input won decisively:

| Metric | clean_text | inscription | Δ |
|---|---|---|---|
| Precision | 0.711 | 0.844 | +0.13 |
| Recall | 0.726 | 0.800 | +0.07 |
| F1 | 0.719 | 0.822 | +0.10 |
| Fragmentary flagged | 4 | 68 | 17× |

With cleaned input, the model fabricates names from the editor's interpretive fillings (28 FPs out of 97 extractions on the test sample). With raw input, the bracket markers preserve uncertainty: the model leaves damaged names alone and correctly flags them fragmentary instead of confidently inventing.

`06_run_full_corpus.py` now feeds raw `inscription` to the model; the prompt explains the epigraphic conventions (`[abc]` restored, `[3]` lacuna of N chars, `<a=b>` letter substitution, `/` line break). The damage filter now correctly fires.

**6. Export script (`06_export_to_dataset.py`):**
- Input path was hardcoded to a stale "(Copy)" file.
- LIRE metadata join only covers ~20% of records. Added EDCS fallback for `findspot` and `raw_text` → 100% coverage.
- Defensive `"null"` string scrub for existing partial-run data.

### Outstanding before full corpus run
- Re-run eval (`05_evaluate_ner.py`) with raw inscription input to update headline F1 numbers — current 0.82 was measured on `clean_text_interpretive_word`.
- Verify ~23% empty-persons rate on a small sample (could be legitimate formula-only inscriptions or model giving up).
