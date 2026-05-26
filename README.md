# Roman NER: Personal Name Extraction from Latin Inscriptions

Automated extraction and classification of personal names from the corpus of Latin inscriptions (*Epigraphik-Datenbank Clauss / Slaby*) using LLM-based Named Entity Recognition.

## Project Goal
Produce a structured, openly published index of personal names from Roman inscriptions, starting with provinces currently lacking dense prosopographical coverage. The pilot province is **Africa Proconsularis**.

The pipeline uses **Gemini 2.5 Flash-Lite** (thinking disabled, batch size 15, up to 20 concurrent workers) with structured JSON output to:
1. Identify individuals in raw Latin inscription text.
2. Expand standard epigraphic abbreviations (e.g. `M.` → Marcus, `L.` → Lucius).
3. Classify name components (praenomen, nomen, cognomen).
4. Identify social status and gender.

## Repository Structure
- `data/` — Raw datasets (EDCS, LIRE) and intermediate build artifacts.
- `scripts/` — Python pipeline: data acquisition, NER extraction, clustering, evaluation, webapp build.
- `scripts/prompts/` — Versioned NER prompts.
- `scripts/lookup/` — Curated text-file lookup tables (praenomina, deities, emperor signatures, etc.).
- `webapp/` — Static Leaflet map visualization. See [`webapp/README.md`](webapp/README.md).

## Current Status
- [x] Data acquisition: EDCS 465MB, LIRE v3.0 474MB (upgraded from v1.2; 182k → ground-truth records).
- [x] Evaluation set generated from LIRE ground truth per province.
- [x] NER pipeline validated — see results below.
- [x] Scale to full corpus: Africa Proconsularis, Britannia, Numidia, Dalmatia, Pannonia Superior/Inferior, Noricum, Dacia, Moesia Superior/Inferior.
- [x] Prosopographical clustering across all provinces.
- [x] Interactive webapp with enriched popups, permalinks, and external database links.
- [x] English translations of inscription text (optional pipeline; run `scripts/11_translate_inscriptions.py`).
- [~] Full rerun with hardened prompt (nominative normalization, abbreviation expansion, generic few-shots) — **in progress**.
- [ ] Manual review of candidate discoveries list.

## Evaluation Results

Numbers are reported under the **corrected evaluation** (one-to-one matching + honest damage accounting; see methodology notes) against **LIRE v3.0** ground truth. Earlier figures (F1 up to 0.90) were inflated by one-to-many matching and over-generous damage exclusion.

| Province | Recall (adj) | Precision (adj) | F1 (adj) | Discoveries |
|----------|--------------|-----------------|----------|-------------|
| Africa Proconsularis | 0.73 | 0.75 | **0.74** | 133 |
| Britannia | 0.70 | 0.83 | **0.76** | 72 |
| Dacia | 0.75 | 0.79 | **0.77** | 125 |
| Dalmatia | 0.75 | 0.74 | **0.75** | 184 |
| Noricum | 0.75 | 0.82 | **0.78** | 204 |
| Numidia | 0.82 | 0.85 | **0.84** | 81 |
| Pannonia inferior | 0.73 | 0.79 | **0.76** | 133 |
| Pannonia superior | 0.73 | 0.78 | **0.75** | 161 |
| Moesia superior | 0.75 | 0.82 | **0.79** | 155 |

> Precision is a **lower bound** — genuine attestations absent from LIRE ground truth are counted as false positives ("discoveries"). Baetica and Moesia inferior are pending their full corpus run.

**Key finding:** the majority of false negatives are inscriptions where the ground-truth name is partially or fully in lacunae (`[---]`). The model cannot recover these from the raw text — an inherent limit of the text-based approach, not a model failure.

## Evaluation Methodology Notes

Several non-obvious choices in `scripts/05_evaluate_ner.py`:

- **Praenomen expansion**: LIRE stores praenomens in abbreviated form (`Q.`, `T.`); the model expands them (`Quintus`, `Titus`). A lookup table maps abbreviations before signature comparison.
- **One-to-one (greedy bipartite) matching**: each prediction is matched to at most one ground-truth person and vice versa, so a single shared-nomen prediction cannot score a true positive against every GT person in a dense record. Token comparison uses a 6-char prefix with a length guard (so `Victor` does not match `Victorinus`) to absorb Latin case-ending variants (`Uttedius` vs `Uttedio`).
- **Damage accounting**: a GT name is only excluded from adjusted recall as "unrecoverable" when it is genuinely lacuna-dominated (`[---]` or >50% bracket characters), not on the presence of any single bracket.
- **Imperial filtering**: Two-stage filter removes emperors and their family from the discoveries list — (1) `status` field keywords (`emperor`, `divus`, `caesar`, `augustus`, `imperator`); (2) inscription-level formula detection (`Imperatori Caesari...`, `Imperator Caesar...`).
- **Damage pre-filtering** (in `06_run_full_corpus.py`): Inscriptions where >30% of characters are inside lacunae brackets (`[...]`) are skipped before sending to the API, reducing cost on records unlikely to yield clean extractions.

## Input Format: Raw `inscription` vs Interpretive Cleaned Text

The pipeline feeds the model EDCS's raw `inscription` field — the editor's transcription containing
lacuna markers (`[3]` = 3 missing chars), restored readings (`[Mar]cus`), and other epigraphic
conventions — rather than `clean_text_interpretive_word` (the interpretive fill-in with brackets
stripped).

This was non-obvious at first but matters a lot. A 30-record A/B test on bracketed eval records
(see `scripts/test_inscription_vs_clean.py`) showed:

| Metric | `clean_text` input | Raw `inscription` input | Delta |
|--------|---|---|---|
| Precision | 0.711 | **0.844** | +13.3 |
| Recall | 0.726 | **0.800** | +7.4 |
| F1 | 0.719 | **0.822** | +10.3 |
| Fragmentary flagged | 4 | 68 | 17× |

**Why:** with the interpretive text the model cannot see where the original was damaged, so
(a) it hallucinates names from the editor's filled-in gaps, inflating false positives, and
(b) it almost never sets `fragmentary=true`, since the lacunae are invisible. Feeding the
raw `inscription` text lets the model preserve uncertainty and treat damaged names as
fragmentary rather than confident attestations.

The prompt explains the bracket conventions to the model so it can parse them correctly.

## Webapp

An interactive map of all extracted attestations is available at [`webapp/`](webapp/). Features include province switching, name search, prosopographical cluster linking, enriched popups with interpretive text and external database links (CIL, EDH, Trismegistos, Ubi Erat Lupa), and shareable permalinks.

See [`webapp/README.md`](webapp/README.md) for data details and instructions to regenerate.

## Future Directions

- **English translations**: `scripts/11_translate_inscriptions.py` batch-translates inscription text with Gemini 2.5 Flash. Run with `--province all --limit N` to control cost. Translations are stored in `webapp/data/enrichment_{province}.json` and displayed in popups when available. A 25-inscription sample (across all provinces and types) showed high quality results.
- **Lacuna restoration**: For damaged records, an Ithaca-style model (cf. Assael et al., *Nature* 2022) could recover names in lacunae — an inherent limit of the text-based approach.
- **Additional provinces**: The pipeline is transferable; each province needs province-specific few-shot examples.
- **Manual review**: Spot-check the candidate discoveries list against RIB, PIR, and secondary scholarship to produce a precision-of-discoveries number.

## Methodology
Full research plan: [roman_ner_research_plan.md](roman_ner_research_plan.md).

## License
Code: MIT License. Data: CC BY-SA 4.0 (EDCS, LIRE source databases).
