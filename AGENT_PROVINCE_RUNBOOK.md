# Agent Runbook: Supervised Province NER Run

This document gives complete instructions for an AI agent to run the NER pipeline on a new province, gut-check the output, fix any systematic problems, and complete the full pipeline through to the webapp data files.

---

## Project Context

This pipeline extracts personal names from Latin inscriptions using **Gemini 2.5 Flash-Lite** with structured output. The source corpus is EDCS (Epigraphik-Datenbank Clauss-Slaby). The output is one row per name attestation in Parquet format, plus GeoJSON and cluster files for a web map.

> **MODEL SELECTION:** The default model is `gemini-2.5-flash-lite` (cheapest). However, provinces with complex prompt branches (many rules + examples, prompt >25K chars) may perform significantly better with `gemini-flash-lite-latest` (Gemini 3.5 Flash Lite). This model costs ~1.4x more ($0.25/$1.50 per M tokens vs $0.10/$0.40) but handles nuanced Latin morphology and multi-rule prompts much more reliably. **If error rates plateau above 15% despite prompt iteration, try switching models before adding more rules.** Pass `--model gemini-flash-lite-latest` to the NER runner. See the Apulia et Calabria entry in "Known Province-Specific Patterns" for a case study.

> **CRITICAL PERFORMANCE NOTE:** The raw EDCS JSON file (`data/EDCS_text_cleaned_*.json`) is very large (400MB+). **NEVER** use `grep` or `read_file` on this file in the CLI. It will overwhelm the context and is extremely slow. If you need to explore or verify data in this file, write a small Python script that uses `ijson` or standard `json` with a streaming approach, or simply trust the `scripts/run_pipeline.py` which handles filtering efficiently.

The pipeline has been run on Africa Proconsularis, Britannia, Numidia, Dalmatia, Pannonia Superior/Inferior, Noricum, Dacia, Moesia Superior/Inferior. The methodology is proven but the prompt may need minor tuning for province-specific naming patterns.

Data file paths are centralised in `scripts/config.py` — do not hardcode paths elsewhere.

### Fast path: the orchestrator

For a normal end-to-end run, prefer `scripts/run_pipeline.py`, which chains
`eval_set → ner → export → eval → cluster → webapp` for one province or all,
handling the EDCS-name vs slug argument split each script expects:

```bash
python3 scripts/run_pipeline.py --province "<slug>"        # one province, full chain
python3 scripts/run_pipeline.py                            # all provinces
python3 scripts/run_pipeline.py --stages export,eval,cluster,webapp   # regen only (no API cost)
python3 scripts/run_pipeline.py --exclude africa_proconsularis        # all but one
```

NER defaults to a **fresh** run (it backs up the existing `_ner_full.jsonl`,
because `06_run` resumes by ID and would otherwise no-op on old output);
`--resume` appends. The supervised step-by-step below is for first-time runs on
a new province or when debugging a systematic error pattern.

---

## Environment

All commands must be run from the repo root (`/home/mbosse/dev/name-research`) with the virtualenv active:

```bash
source venv/bin/activate
```

The `.env` file contains `GEMINI_API_KEY`. It is present and working. Do not print or expose it.

---

## Your Task

Run the NER pipeline for: **`{{PROVINCE_NAME}}`** (e.g. `Dalmatia`)

Province slug (lowercase, underscores): **`{{PROVINCE_SLUG}}`** (e.g. `dalmatia`)

---

## Step 1: Gut-Check Run — First 100 Records

First, generate the LIRE evaluation set (needed for `--with-gt` in spot-checks):

```bash
python3 scripts/03_generate_validation_set.py --province "{{PROVINCE_NAME}}"
```

Note the pool size it reports. Some provinces (e.g. Gallia Narbonensis: ~83) have small LIRE pools. This is fine for scoring but means `--with-gt` may show 0 GT hits in a small sample if IDs don't overlap — not a bug, just low density.

Then run the first 100 records:

```bash
python3 scripts/06_run_full_corpus.py --province "{{PROVINCE_NAME}}" --stop-after 100 --model gemini-2.5-flash-lite
```

Then spot-check **all 100** with ground truth:

```bash
python3 scripts/spot_check.py --province {{PROVINCE_SLUG}} --n 100 --recent --with-gt
```

Read the full output. For each record, check:

### What good output looks like

- Personal names extracted with correct component breakdown (praenomen / nomen / cognomen)
- Illyrian or other indigenous names appearing as single-word **cognomen** (no praenomen/nomen)
- Father's name in filiation (e.g. "Bato **Platoris** filius") extracted as a separate person with status "pater" or left as part of raw_name — either is acceptable; what is NOT acceptable is the father's name being put in the **nomen** field of the child
- `fragmentary: true` set when the name text contains `[---]` or `[3]`
- Where LIRE ground truth is shown: our extraction matches in substance (exact spelling may differ; root match is sufficient)

### Red flags — stop and fix before continuing

**1. Praenomen field contains a nomen**
Bad: `"praenomen": "Flavius"`, `"praenomen": "Aurelius"`, `"praenomen": "Iulius"`
These are nomina. The model is misclassifying positional anchoring. The export script (`06_export_to_dataset.py`) will auto-rotate these, but if you see >10% of records doing this, add a clearer example to the prompt.

**2. Deity or place names extracted as persons**
Bad: extracting `Mars`, `Jupiter`, `Fortuna`, `Salona`, `Narona` as persons.
Check `scripts/lookup/deities.txt` and `scripts/lookup/place_names.txt`. If the province has common local deity or place names not in those files, add them.

**3. Unit/legion names extracted as persons**
Bad: extracting `Augusta` (from `Legio II Augusta`) or `Claudia` (from `Ala Claudia`) as a female person.
This should be rare with the current prompt but check for it.

**4. Empty raw_name or single-character raw_name**
Bad: `"raw_name": ""` or `"raw_name": "C"`.
These are extraction artifacts. If systematic, tighten the prompt.

**5. Gender value in a name field**
Bad: `"nomen": "male"` or `"cognomen": "female"`.
The `model_post_init` validator in `06_run_full_corpus.py` strips these, but if you see them surviving, check the validator.

**6. Zero-person extraction rate > 80%**
Run: `python3 scripts/spot_check.py --province {{PROVINCE_SLUG}} --n 100 --recent`
If 80%+ of records extract nothing, sample some of the empty records and check whether the inscriptions actually contain personal names. Many Dalmatian inscriptions are military building texts or votive dedications without personal names — a high empty rate may be correct. But if personal-name inscriptions are being missed, the prompt needs attention.

**7. All names collapsed into nomen field, cognomen always null**
This indicates the model isn't distinguishing tria nomina components. Add a clearer example.

### Threshold for action

| FP/error rate in first 100 | Action |
|---|---|
| < 5% obvious errors | Proceed to Step 2 |
| 5–15% errors, not systematic | Note in findings, proceed |
| > 15% errors, or a clear systematic pattern | Fix first (see Step 1b), then delete partial output and rerun Step 1 |

---

## Step 1b: How to Fix Problems

### Fix the prompt (most common fix)

Edit `scripts/prompt_utils.py`. The `get_system_prompt()` function has an `elif` branch for each province. The Dalmatia/Pannonia/Noricum/Dacia branch is already there. Add or adjust few-shot examples to correct the specific error pattern you observed.

Example: if the model is treating Illyrian filiation incorrectly, add an example that shows the right behavior.

After editing, **delete the partial output** and rerun:

```bash
rm data/output/{{PROVINCE_SLUG}}_ner_full.jsonl
python3 scripts/06_run_full_corpus.py --province "{{PROVINCE_NAME}}" --stop-after 100
```

### Add to lookup files

- New deity names: `scripts/lookup/deities.txt`
- New place names (if they appear as false-positive persons): `scripts/lookup/place_names.txt`

One entry per line. Lowercase. Check existing entries for format.

### If the validator is missing a bad value

Edit the `model_post_init` method in `06_run_full_corpus.py` to add the bad value to the strip list.

---

## Step 2: Extended Check — First 500 Records

After a clean Step 1, continue to 500:

```bash
python3 scripts/06_run_full_corpus.py --province "{{PROVINCE_NAME}}" --stop-after 500 --model gemini-2.5-flash-lite
```

Spot-check 50 recent records with ground truth:

```bash
python3 scripts/spot_check.py --province {{PROVINCE_SLUG}} --n 50 --recent --with-gt --only-persons
```

Look for the same issues as Step 1. Pay particular attention to:
- Whether GT-matched records are being extracted correctly (the `--with-gt` output shows LIRE ground truth for those that have it)
- Whether extraction quality degrades on less common inscription types

If clean, proceed. If new systematic issues appear, fix and decide whether to rerun from 0 or just continue.

---

## Step 3: Full Corpus Run

```bash
python3 scripts/06_run_full_corpus.py --province "{{PROVINCE_NAME}}" --model gemini-2.5-flash-lite --workers 20
```

`--workers 20` runs 20 concurrent API calls. Flash-Lite allows 4,000 RPM / 4M TPM; at batch size 30 and ~3k tokens per batch this is well within limits. Increase to `--workers 40` for large provinces (Roma). The script resumes from the last processed record if interrupted; 429 errors trigger automatic backoff and retry.

While it runs, you can check progress:
```bash
wc -l data/output/{{PROVINCE_SLUG}}_ner_full.jsonl
```

---

## Step 4: Post-Run Pipeline

Run each step in order. Each is fast (seconds to a few minutes).

### 4a. Evaluation (measures quality against LIRE ground truth)

Score against the full corpus output (eval set was already generated in Step 1):
```bash
python3 scripts/05b_eval_from_corpus.py --province {{PROVINCE_SLUG}}
```

Record the F1 (adjusted), precision (adj), and recall (adj) numbers. Expected range based on prior provinces: F1 0.75–0.90.

If F1 < 0.70, examine the false negatives and false positives before continuing. This may indicate a prompt issue that affected the whole run.

### 4b. Export to Parquet dataset

```bash
python3 scripts/06_export_to_dataset.py --province {{PROVINCE_SLUG}} --province-name "{{PROVINCE_NAME}}"
```

Check the output stats it prints: total names, flagged deity/imperial/epithet counts. If `is_imperial` is 0 and the province had any military content, something is wrong. If `is_deity` is 0, same concern.

### 4c. Clustering

```bash
python3 scripts/08_cluster_attestations.py --province {{PROVINCE_SLUG}}
```

This deduplicates near-identical name attestations across the corpus. Note the number of unique clusters vs total attestations.

### 4d. Build LIRE enrichment lookup (run once per repo, not per province)

If `data/lire_enrichment.json` does not exist:

```bash
python3 scripts/10_build_lire_lookup.py
```

This reads `LIRE_PATH` (currently `data/LIRE_v3-0.geojson`, set in `scripts/config.py`) and writes `data/lire_enrichment.json`. Takes ~2 minutes. Only needs to be run once per LIRE version; if you upgrade LIRE, delete the old enrichment file and re-run.

### 4e. Build webapp data

```bash
python3 scripts/09_build_webapp_data.py --province {{PROVINCE_SLUG}}
```

This writes:
- `webapp/data/inscriptions_{{PROVINCE_SLUG}}.geojson`
- `webapp/data/clusters_{{PROVINCE_SLUG}}.json`
- `webapp/data/enrichment_{{PROVINCE_SLUG}}.json`

### 4f. Add English translations (recommended)

```bash
python3 scripts/11_translate_inscriptions.py --province {{PROVINCE_SLUG}} --include-raw --dry-run
python3 scripts/11_translate_inscriptions.py --province {{PROVINCE_SLUG}} --include-raw
```

The dry run shows how many records will be translated and estimated batches. The full run costs a few cents per province. The `--include-raw` flag translates non-LIRE inscriptions using EDCS raw text (epigraphic notation with parenthesised expansions), which typically brings translation coverage from ~50% to ~99%. Without this flag, only inscriptions with LIRE `text_edition` are translated. Translations are written directly into `webapp/data/enrichment_{{PROVINCE_SLUG}}.json` and displayed in popup cards. The script is interruptible — re-run without `--force` to resume.

### 4g. Add province to the webapp selector

Edit `webapp/index.html`. Find the `<select id="province-select">` block and add:

```html
<option value="{{PROVINCE_SLUG}}">{{PROVINCE_NAME}}</option>
```

Find the `PROVINCES` JavaScript config object and add:

```javascript
{{PROVINCE_SLUG}}: { label: '{{PROVINCE_NAME}}', center: [LAT, LON], zoom: 7 },
```

Use an appropriate center coordinate for the province (e.g. Dalmatia: `[44.0, 16.5]`, Noricum: `[47.5, 14.0]`, Pannonia: `[47.0, 18.0]`, Dacia: `[46.0, 23.5]`).

---

## Step 5: Final Spot Check

Run a final quality check on the full corpus output:

```bash
python3 scripts/spot_check.py --province {{PROVINCE_SLUG}} --n 100 --with-gt --only-persons --seed 99
```

Confirm:
- Person extraction looks correct across a broad sample
- No obvious systematic errors remaining
- F1 score is in acceptable range (≥ 0.72)

---

## Step 6: Report Back

Summarise:
1. F1 / precision / recall from Step 4a
2. Total name attestations extracted
3. Any prompt changes made (what problem, what fix)
4. Any new entries added to lookup files
5. Translation count and any issues with translation quality
6. Any issues still present that warrant human attention

---

## Known Province-Specific Patterns

### Dalmatia
- Large population of Illyrian single names: Bato, Epicadus, Liccavus, Plassarus, Scenobarbus, Dasas, Pinnes, Tato, Andes, Laidus, Verzus. These should appear as **cognomen only** (praenomen = null, nomen = null).
- Filiation is common: "Bato Platoris f(ilius)" — extract Bato as the main person, Plator as a separate person with status "pater", OR note Plator in raw_name filiation. Do not put Plator in Bato's nomen field.
- After 212 AD (Constitutio Antoniniana): many Illyrians took Roman nomina (Aurelius is most common), so "Aurelius Bato" is correct tria nomina (nomen: Aurelius, cognomen: Bato).
- Military inscriptions are numerous — legionary and auxiliary unit names should NOT be extracted as persons.

### Pannonia (superior / inferior)
- Similar Illyrian naming patterns to Dalmatia.
- Celtic names also present in the west.
- High density of military epitaphs from the Danubian legions.

### Noricum
- Mix of Celtic (Atta, Suadra, Catta) and Roman names.
- Celtic names: single cognomen, same as Illyrian treatment.
- Relatively few inscriptions — quality tends to be high.

### Dacia
- Dacian names: single cognomen (Decebalus, Decebal, Scorilo, Comosicus are legendary; ordinary Dacians: Diurpaneus, Buri, etc.).
- Strong Greek influence in some areas (Greek names in Latin script).
- Many veterans from auxiliary units settled here.

### Apulia et Calabria / Regio II
- **Model requirement:** This province uses `gemini-flash-lite-latest` (3.5 Flash Lite), not the default `gemini-2.5-flash-lite`. The complex 34K-char prompt (23 rules, 34 examples) caused a regression to ~24% error rate on flash-lite, but only ~8-10% on flash-lite-latest. **Always pass `--model gemini-flash-lite-latest`.**
- Title vs. cognomen ambiguity (Rule 19): words like "Sacerdos," "Augur," "Flamen" can be either titles or cognomina. When they appear in the cognomen slot of a standard name pattern (e.g. "Romanius Sacerdos"), treat as cognomen.
- Person-split errors (Rule 23): adjacent nomen + cognomen in the same oblique case without "et" are one person, not two (e.g. "Insontio Secundino" = one person Insontius Secundinus).
- Greek-influenced names common in coastal cities (Tarentum, Brundisium): Thallus, Aphrodisia, Glyconis, Zosima.
- Syncretic deity names: Pallas/Palladi, Pomona, Lyaeus/Lyaeo, Deus/Deo Aeternus — added to `deities.txt`.
- Regional prompt branch in `prompt_utils.py` matches on `'apulia et calabria'`, `'apulia_et_calabria'`, or `'apulia et calabria / regio ii'`.

---

## File Reference

| File | Purpose |
|---|---|
| `scripts/06_run_full_corpus.py` | Main NER run script |
| `scripts/spot_check.py` | Sampling and review tool |
| `scripts/prompt_utils.py` | System prompt + province few-shots |
| `scripts/03_generate_validation_set.py` | Build eval set from LIRE |
| `scripts/05b_eval_from_corpus.py` | Score against LIRE ground truth |
| `scripts/06_export_to_dataset.py` | Flatten NER output → Parquet |
| `scripts/08_cluster_attestations.py` | Deduplication clustering |
| `scripts/09_build_webapp_data.py` | Build GeoJSON + cluster + enrichment JSON |
| `scripts/10_build_lire_lookup.py` | Build LIRE enrichment lookup (run once) |
| `scripts/11_translate_inscriptions.py` | Batch-translate inscription text with Gemini |
| `scripts/lookup/deities.txt` | Deity name filter list |
| `scripts/lookup/emperor_signatures.txt` | Imperial name signatures |
| `data/output/{{PROVINCE_SLUG}}_ner_full.jsonl` | NER output (appended, resumable) |
| `webapp/index.html` | Web map — add province here |
