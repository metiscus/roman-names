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
1. ✅ Confirm full Africa corpus run finished overnight. 27,446 records → 34,788 attestations.
2. ✅ Praenomen-whitelist post-process landed in `06_export_to_dataset.py`. `CANONICAL_PRAENOMINA` set (18 male + spelling variants + feminine forms); off-list values rotate left (`praenomen → nomen`, displaced `nomen`+`cognomen` concatenated into new cognomen). 121 reclassifications in this run (~1.3% of persons with praenomen, ~0.4% of all persons). Sanity-checked: zero off-list values remain; Flavius Lucretius Florentinus Rusticus and other known mid-run problem cases now correctly structured.
3. ✅ Re-exported. Final: 34,788 attestations.
4. ✅ Re-evaluated with raw inscription input (`scripts/05b_eval_from_corpus.py`). Reuses corpus-run predictions instead of re-running NER, joins back to eval GT, applies the praenomen fix, and counts damage-filter-skipped inscriptions as `fn_filtered`. Results below.
5. Then proceed to Britannia setup or webapp build.

### Updated headline numbers (raw inscription input)

| Metric | Old (clean_text, all 433 eval records) | New (raw inscription, 299 records post-damage-filter) |
|---|---|---|
| Recall (adj, excl. damage) | 0.93 | **0.85** |
| Precision (adj, excl. imperial) | 0.73 | **0.68** |
| F1 (adj) | 0.82 | **0.76** |
| Potential discoveries | 226 | 186 |
| Per-record discovery rate | 0.52 | **0.62** |

The headline F1 drops from 0.82 to 0.76 on switching to raw-inscription input. Caveats:
- **Apples-to-oranges denominators.** The old eval ran on all 433 records (the damage filter was the silent no-op). The new pipeline drops 134 inscriptions (31%) before the API call — 277 GT persons in those dropped records count as `fn_filtered` (unrecoverable from raw text). Scoring is on the 299 survivors, which skew shorter and more fragmentary.
- **Precision regression source:** emperor-epithet phrases like `Pio Felici` and `Augusta Salutaris` slip past the imperial filter as "discoveries." Per-record discovery rate is actually higher (0.62 vs 0.52) — the model is more aggressive on the survived-damage-filter subset.
- The qualitative tradeoff from the pre-run A/B test stands: with raw input the model correctly flags fragmentary names instead of fabricating restorations. The full-corpus run rate of `fragmentary: true` is 28.4% (up from 12% under clean-text), which is the desired behavior.
- 0.76 adjusted F1 with 0.85 recall is still strong for unsupervised NER on noisy epigraphic text. Headline framing for outreach: "0.85 recall and 0.68 precision on inscriptions that survive a 30%-lacuna damage filter; 186 candidate name attestations on the 299-record eval set that don't match LIRE ground truth and warrant manual review."

### Discoveries-list triage and non-person FP filters

Manual review of the top 10 "discoveries" (against SIRAR, PIR, PLRE, secondary scholarship) found that most were not discoveries at all:
- `Augusta Salutaris` (EDCS-06000308) is a deity on a dedicatory inscription — the actual person C. Vibius Marsus, proconsul, was correctly extracted and matched LIRE GT, but the deity got bucketed alongside as a "discovery."
- Three `P./L. Septimius Geta` entries — emperor's brother (Caracalla's), not in our imperial filter.
- `Pio Felici` / `Pius` — bare imperial epithets.
- `Tiberius Caesar Augustus` — actual emperor, somehow not caught.
- `[[C(aio) Fulvio Pla[ut]iano]]` — Severan praetorian prefect, damnatio memoriae brackets are a strong imperial signal.

**Boncarth Muthumbalis** (EDCS-06000296) was a *real* hit: extracted correctly with `IIIIvir macelli` status from a bilingual Latin-Punic Liber Pater dedication at Lepcis Magna; cited in Brill scholarship for the practice of municipal magistrates funding dedications `ex multis`. He is not in LIRE's structured `people` field.

This sharpens the framing: the dataset's value is **machine-readable attestations of individuals already documented in scholarship but absent from any open structured prosopographical dataset**. Not "discoveries" in the strong sense — but the bridge between EDCS's raw text, LIRE's hand-curated 433 records, and the scholarly literature.

**New module: `scripts/name_filters.py`**
- `DEITY_NAMES` — Roman/African/personification deity tokens (Iuppiter, Saturnus, Caelestis, Salus, Concordia, Augusta-when-alone, etc.).
- `EMPEROR_SIGNATURES` — known emperor/imperial-family name tuples (Septimius+Geta, Aurelius+Antoninus, Fulvius+Plautianus...).
- `IMPERIAL_EPITHETS` — bare epithets when no nomen/praenomen accompanies (Pius, Felix, Invictus, Augustus, etc.).
- `[[...]]` damnatio memoriae brackets → imperial.
- `classify_non_person_fp(person)` returns `'deity' | 'imperial' | 'epithet' | None`.

Wired into both `05b_eval_from_corpus.py` (bucket FPs out of discoveries) and `06_export_to_dataset.py` (add `is_deity` / `is_imperial` / `is_bare_epithet` boolean columns to the deliverable). After filters:

| Metric | Before filters | After filters |
|---|---|---|
| Precision (adj) | 0.68 | **0.71** |
| F1 (adj) | 0.76 | **0.77** |
| FP — Imperial | 37 | 44 (+7 Severan family, Tiberius, Plautianus) |
| FP — Deity / personification | — | 6 |
| FP — Bare imperial epithet | — | 5 |
| Candidate Discoveries | 186 | 168 |

Export deliverable now flags 856 `is_deity`, 1,358 `is_imperial`, 330 `is_bare_epithet`, 10,262 `fragmentary` (out of 34,788 — note these overlap). Downstream consumers can filter as needed.

### Framing for outreach (revised)

Earlier draft framing leaned on "discoveries." That's not honest — Boncarth Muthumbalis is real but already known; the deity FPs were never persons. The defensible framing:

> **Structured, machine-readable attestation index for Africa Proconsularis Roman inscriptions.** Bridges raw EDCS text with LIRE's hand-curated `people` layer (currently 433/33k records). Validated against LIRE ground truth: F1 0.77, recall 0.85 (adjusted, excl. damage-filtered). Useful for: aggregate analyses, cross-reference between EDCS records and published prosopographical scholarship, and a starting point for future expert curation.

LIRE remains the authority; this is a parallel resource that depends on it for validation. No suggestion of patching or merging into LIRE — that would be presumptuous toward a hand-curated academic project. Courtesy email to Heřmánková as ground-truth user, methodological feedback request only.

### Next direction (user-set priority)

1. **Triage** the 168 candidate discoveries (manual spot-check, EDCS context + scholarly cross-reference) to produce a real precision-of-discoveries number. Cheapest, biggest credibility unlock.
2. ✅ **Dedup pass** — done. See "Clustering" section below.
3. **Webapp** — Leaflet + GeoJSON + GitHub Pages per `followup/webapp_plan.md`. Outreach surface.

Britannia and Zenodo upload follow after these.

### Clustering (dedup) — landed

`scripts/08_cluster_attestations.py` implements connected-component clustering over name+location+date compatibility. Two artifacts:
- `cluster_id`, `cluster_size`, `cluster_confidence` columns appended to the parquet/CSV.
- `data/clusters_summary.csv` — one row per cluster with representative name, member IDs, findspots, date range, and flags. This is the file a classicist actually reads.

**Universe:** 33,509 attestations (excluding 1,279 flagged is_deity / is_place / is_bare_epithet). is_imperial and fragmentary records ARE included with flags propagated.

**Two pools:**
- **Main pool** (15,237 records): both nomen + cognomen present. Bucket by `(nomen_prefix[:6], cognomen_prefix[:6])`, union within bucket if praenomen-compatible + location-compatible + date-compatible.
- **Single-cognomen pool** (13,724 records): no nomen. Bucket by **exact** cognomen (not prefix — the 6-char prefix conflated Victor / Victorinus / Victorina / Victoricus which all share `victor`, blowing one cluster to size 75 in a debug pass). Stricter spatial filter: requires same findspot text, no coordinate fallback.

**Compatibility:**
- Praenomen: pass unless both present and differ (after Caius↔Gaius / Caeso↔Kaeso / Caia↔Gaia normalization).
- Location: same findspot (case-insensitive) OR coords ≤50km. Permissive if either side has no location.
- Date: range overlap. Permissive if either side has no dates.

**Confidence labels:**
- `low`: single-cognomen cluster with >1 member, OR post-212 CE cluster with majority Aurelius nomen (Constitutio Antoniniana effect).
- `high`: everything else, including imperial clusters.
- `excluded`: non-person (deity/place/epithet).

**Results:**

| Stat | Value |
|---|---|
| Total attestations | 34,788 |
| In universe | 33,509 |
| Total clusters | 28,740 |
| Singletons (size 1) | 26,298 (92%) |
| Multi-member clusters | 2,442 |
| Largest cluster | 72 (C. Clodius Successus — North African lamp maker, confirmed via JSTOR 10.2307/4238723) |
| Attestations in multi-clusters | 21.5% (target band 15–25%) |
| `high` confidence | 29,087 |
| `low` confidence | 4,422 |
| `excluded` | 1,279 |

**Sanity-check pass:**
- Flavius Lucretius Florentinus Rusticus → 1 cluster, size 4 (all 4 attestations). ✓
- Septimius Severus → 1 imperial cluster, size 29. ✓
- Caracalla (M. Aurelius Antoninus) → 1 imperial cluster, size 28. ✓
- C. Vibius Marsus → 2 singletons (same person, two cities, >50km apart). Known limitation: famous officials who travel across the province under-cluster by the 50km rule. Documented; downstream users can manually link via `clusters_summary.csv` if needed.

**Cluster-of-many bare cognomens** (Victor × 47, Fortunatus × 35, Bonifatius × 27, Agnus × 22, Saturninus × 18, etc.) are common-cognomen pools at single findspots — almost certainly different individuals sharing a name. All correctly flagged `low` confidence. Downstream consumers filter these out for one-person-per-cluster analyses; aggregate analyses can still use them.

**Known limitations to document with the deposit:**
- 50km rule under-clusters traveling officials and merchant-stamp series across cities.
- Single-cognomen clusters with low confidence may inflate or deflate person counts; treat as "set of attestations of this name at this place," not "this individual."
- Latin morphology not handled — Victor and Victori (nom vs dat) won't cluster in single-cognomen pool. Acceptable since these were already low-confidence.

### Triage round 1 (AI reviewer, pending human re-verification)

First-pass review of `data/triage_candidates.csv` came back from an AI agent (preserved in gitignored `followup/triage_review_v1.md` with the AI-source caveat). Headline claim: ~93/97 reviewed candidates marked True Person → ~96% precision on the reviewed subset. Treating as a hypothesis layer pending human spot-check — AI etymologies (`Luca bos` = "Lucanian cow" = elephant; `Augusta Emerita` etc.) sound confident in the way AI-reviewer claims do when they're hallucinating.

Three systematic issues claimed:
1. **Case preservation** — model leaves names in dative/genitive/ablative instead of nominative (e.g., `Publio Fabio Firmano` should normalise to `Publius Fabius Firmanus`). Particularly affects centurions in military rosters (genitive after `|` symbol).
2. **Place/idiom FPs** — towns (Apisa, Augusta Emerita) and Latin idioms (`Luca bos` = elephant) extracted as persons.
3. **Bracket blindness** — `Ner[vae(?)]` slipped past `is_imperial_person` because brackets broke token matching.

### Refactor + quick filter fixes (this session)

**Refactor to text-file lookups.** All hardcoded curated sets moved to `scripts/lookup/*.txt` so non-Python contributors can extend them:
- `praenomina_canonical.txt` (35 entries — 18 male + variants + feminine forms; used by 06_export)
- `praenomina_prompt.txt` (19 entries — male only; used by 06_run_full_corpus prompt)
- `tribus.txt` (35 voting tribes; used by 06_run_full_corpus)
- `deities.txt` (107 tokens; used by name_filters.is_deity)
- `emperor_signatures.txt` (47 signatures, comma-separated for multi-token; used by name_filters.is_imperial_person)
- `imperial_epithets.txt` (15 tokens; used by name_filters.is_bare_epithet)
- `african_places.txt` (2 entries to start: apisa, emerita — extended as new FPs are flagged)

**Filter improvements:**
- `_clean_tokens()` helper in `name_filters.py` strips `[]()` + digits + `?+*` before tokenization, defeating bracket-blindness on `Ner[vae(?)]`-style imperial names.
- New `is_place()` classifier: triggers only when cognomen alone matches a known town and there's no praenomen/nomen — conservative, won't false-flag a real person whose name shares a token with a place.
- `'divi '` (genitive of `divus`) added to `IMPERIAL_FORMULAE` in `05_evaluate_ner.py` — catches `divi Nervae` ("of the divine Nerva") which earlier slipped through with only dative `'divo '` / `'divae '` present.

**Results after fixes:**

| Metric | Pre-filter | After deity/imperial/epithet (last session) | After place/bracket fix (this session) |
|---|---|---|---|
| FP — Imperial | 37 | 44 | 46 (+ Nerva via divi formula) |
| FP — Deity | — | 6 | 5 |
| FP — Place | — | — | **2** (Apisa, Emerita) |
| FP — Epithet | — | 5 | 5 |
| Candidate Discoveries | 186 | 168 | **165** |
| Precision (adj) | 0.68 | 0.71 | 0.71 |
| F1 (adj) | 0.76 | 0.77 | 0.77 |

The `Lucae` (= elephant) case is not yet caught — would need a separate idiom/animal filter; bracketed for now since it's a rare edge case.

Export deliverable now carries `is_place` boolean column alongside `is_deity` / `is_imperial` / `is_bare_epithet` / `fragmentary`. Africa run: 944 deity, 1,390 imperial, 332 epithet, 7 place, 10,262 fragmentary out of 34,788 (overlapping).

Pipeline-side recommendations for the next NER run (Britannia or hypothetical Africa v2):
- **Prompt rule for nominative lemmatization** — covers the case-preservation issue across senatorial dedications and military-roster centurions.
- **Prompt rule for foreign filiation patterns** — `<Name1> <Name2>(genitive) f(ilius)` parsing for Punic/Libyan names (Boncarth, Asmun).
- **Few-shot example for centurion `|` symbol** — explicit instruction to lemmatize the genitive name following it.
- **Hold off re-running Africa** — current data ships with documented caveats; defer the $6 + 4h re-run decision until after Britannia validates the new prompt.

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
