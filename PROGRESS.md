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

### Empty-persons rate investigation

The pre-fix partial run had 23% of processed records returning zero persons. Investigated 15-record sample drawn from the 1,574 empty records in the (Copy) partial output:

- 71% of empty records have <30 chars of cleaned text (median 15 chars vs 69 chars for nonempty).
- 28% have >30% damage in the raw inscription.

Sample breakdown:
- **10/15 correctly empty** — title-only inscriptions (`consuli pro praetore`), funeral formulas with name in lacunae (`fuit suis amabilis vixit in pace...`), `solvit`-only, military roster fragments, single Greek letter, 2-3 letter `tituli fabricationis` stamps.
- **4/15 borderline** — single name-fragment letters (`APP`, `Cat`, `ilius`, `PV`) where a `fragmentary: true` attestation would be defensible. The cleaned-input run missed these because the lacuna context was stripped.
- **1/15 unclear**.

Conclusion: the empty rate is not a model failure. Africa Proconsularis genuinely contains many fragments and formula-only inscriptions with no extractable name. With the raw `inscription` input + properly firing damage filter, the empty rate in the new run is expected to drop substantially (heavily damaged records get filtered out before the API call, borderline fragments gain `fragmentary: true` attestations).

### Outstanding before full corpus run
- Re-run eval (`05_evaluate_ner.py`) with raw inscription input to update headline F1 numbers — current 0.82 was measured on `clean_text_interpretive_word`.

### Mid-run spot check (2,560 / 27,447 records processed)

Stats are healthy: 3,083 persons extracted, 28.4% fragmentary flag rate (up from 12%), 22.6% empty rate (consistent with prior analysis), zero "null" string leaks, zero gender leaks. New raw-inscription input is doing what we wanted.

**One real systematic bug found:** the model misclassifies `Fl./Iun./Iul./F./Fab.` abbreviation patterns as praenomen ~0.5% of the time (16/3,083 persons in the partial). When the inscription has `Fl(avius) Polybio` or `Iunius Amicus`, the model correctly expands the abbreviation to the full nomen but then files it in the praenomen field due to positional anchoring — overriding the explicit prompt rule that "Iulius, Flavius, Aurelius are NOMINA, not praenomina." Notable affected person: Flavius Lucretius Florentinus Rusticus, a late-antique governor of Tripolitania, wrongly classified in all 4 of his attestations.

**Decision: post-process fix at export time, not a re-run.** The 18 canonical praenomina are a closed set, so any `praenomen` value outside that whitelist is by definition wrong. The export script can deterministically move it: `praenomen` → `nomen`, push existing `nomen` to `cognomen`. Three-line patch in `06_export_to_dataset.py`. More reliable than re-prompting (the rule didn't catch it the first time), saves the restart cost.

Edge case to consider: feminine praenomina like `Publia` (fem. of Publius). Roman women occasionally had praenomina; the model's reading of `P(ublia) Ogulnia` may actually be correct. The whitelist needs feminine forms added (Publia, Gaia, Marcia, Lucia, Tita, Quinta, etc.) or this should be a soft warning rather than a hard reclassify. Address as part of the post-process patch.

**Other findings cleared:**
- 21 "tribus in nomen" flags from the heuristic check are all legitimate female nomina (`Aemilia`, `Cornelia`, `Fabia`, `Claudia`, etc.) — false alarms, no fix needed.
- 8-record random eyeball sample looked clean: emperors correctly tagged, multi-cognomen names handled, fragmentary signal preserving lacuna markers in name fields (e.g., `Gaius Ser[3] Soricius`).

### Next session pickup
1. Confirm full Africa corpus run finished overnight.
2. Add the praenomen-whitelist post-process to `06_export_to_dataset.py` (plus feminine praenomina handling).
3. Re-export to CSV/Parquet, sanity-check counts.
4. Re-run eval with raw inscription input to update headline F1.
5. Then proceed to Britannia setup or webapp build.

---

## Next Province: Britannia

The pipeline is largely province-agnostic; only ~5 lines are Africa-specific (province constant, output filename, system-prompt opening line, one few-shot example with Punic names). Britain looks like a clean second target.

### Scope and validation

| | Africa Proconsularis | Britannia |
|---|---|---|
| EDCS records | 33,044 | 19,192 |
| After damage filter | 27,447 | 15,764 |
| LIRE records with structured `people` data | 433 | **2,250** |
| Estimated API cost | ~$6 | ~$3-4 |
| Estimated runtime | ~4h | ~2.5h |

Britain is ~60% the size of Africa and has ~5× more LIRE ground truth, so validation will be much stronger. Latin-dominant; minimal Greek to handle.

### Independent cross-reference: RIB Online

Roman Inscriptions of Britain (romaninscriptionsofbritain.org):
- **License: CC BY 4.0** — texts and the underlying TEI XML are openly licensed. Compatible with CC BY-SA redistribution, attribution required.
- **No bulk export or public API yet.** Linked-data RDF serialization is "underway" but not shipped. Currently only browsable HTML.
- Structured endpoints (`/person/0`, `/place/0`, etc.) exist internally but aren't exposed for bulk consumption.

Implication: primary validation stays LIRE-based (programmatic, no permission needed). Enhanced precision claims via 50-record manual lookup against RIB website — fine under their terms. No scraping for bulk RIB data without permission; defer joining RIB cross-references until they publish RDF.

### What to change in the codebase

1. `PROVINCE = 'Britannia'` and output filename (`britannia_ner_full.jsonl`).
2. System prompt opening: "specializing in ... Africa Proconsularis" → "Britannia".
3. Swap the African Punic-name few-shot example for a British one — military votive altars are the common pattern, e.g. `P(ublius) Viboleius Secundus aram d(onum) d(edit)`. Consider also adding a Celtic-name example and a unit-abbreviation note (`Leg(io) XX V(aleria) V(ictrix)`, `Ala I A(sturum)`, `Coh(ors)`) so unit names aren't parsed as persons.
4. Re-run `03_generate_validation_set.py` against LIRE Britain to build a new eval set (~2,250 candidates).
5. Same few-shot tweaks in `scripts/prompts/ner_v1.txt` for consistency.

### Order of operations
1. Finish Africa full run (in progress).
2. Re-measure Africa F1 with the new input format to lock in headline numbers.
3. Then Britain: half-day setup, ~2.5h runtime, ~$4. Manual RIB spot-check on the discoveries list.

### Wider relevance
Britain is well-studied (RIB is curated by classicists for decades), so the framing shifts from "discoveries" (Africa pitch) to "first openly-licensed structured CSV of British Roman name attestations with coordinates, dates, and source links." Useful as a data-analysis primitive even where the underlying material is well-known. Gives a cleaner pitch to UK-based scholars and the Roman Society community.
