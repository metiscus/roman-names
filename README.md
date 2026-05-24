# Roman NER: Personal Name Extraction from Latin Inscriptions

Automated extraction and classification of personal names from the corpus of Latin inscriptions (*Epigraphik-Datenbank Clauss / Slaby*) using LLM-based Named Entity Recognition.

## Project Goal
Produce a structured, openly published index of personal names from Roman inscriptions, starting with provinces currently lacking dense prosopographical coverage. The pilot province is **Africa Proconsularis**.

The pipeline uses **Gemini 2.5 Flash** (thinking disabled) with structured JSON output to:
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
- [x] Data acquisition complete (EDCS 465MB, LIRE 576MB).
- [x] Evaluation set generated: 433 Africa Proconsularis records with LIRE ground truth.
- [x] NER pipeline validated — see results below.
- [x] Scale to full Africa Proconsularis corpus (~33k records).
- [x] Scale to Britannia corpus (~16k records).
- [x] Scale to Pannonia inferior, Dacia, Noricum, Dalmatia, Pannonia superior, Moesia superior.
- [x] Prosopographical clustering across all provinces.
- [x] Interactive webapp with enriched popups, permalinks, and external database links.
- [ ] English translations of inscription text.
- [ ] Manual review of candidate discoveries list.

## Evaluation Results

| Province | Recall (adj) | Precision (adj) | F1 (adj) | Discoveries |
|----------|--------------|-----------------|----------|-------------|
| Africa Proconsularis | 0.85 | 0.71 | 0.77 | 165 |
| Britannia | 0.86 | 0.86 | 0.86 | 72 |
| Pannonia inferior | 0.92 | 0.87 | 0.90 | 107 |
| Dacia | 0.88 | 0.83 | 0.85 | 112 |

**Key finding:** 65% of false negatives are inscriptions where the ground-truth name is partially or fully in lacunae (`[---]`). The model cannot recover these from the raw text — this is an inherent limit of the text-based approach, not a model failure.

## Evaluation Methodology Notes

Several non-obvious choices in `scripts/05_evaluate_ner.py`:

- **Praenomen expansion**: LIRE stores praenomens in abbreviated form (`Q.`, `T.`); the model expands them (`Quintus`, `Titus`). A lookup table maps abbreviations before signature comparison.
- **Word-overlap matching** (≥75% threshold with 6-char prefix): replaces simple substring matching to handle (a) predictions with extra cognomina and (b) Latin case ending variants (`Uttedius` vs `Uttedio`).
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

- **English translations**: Batch-translate inscription text using a low-cost LLM or pull scholarly translations from EDH where available.
- **Lacuna restoration**: For damaged records, an Ithaca-style model (cf. Assael et al., *Nature* 2022) could recover names in lacunae — an inherent limit of the text-based approach.
- **Additional provinces**: The pipeline is transferable; each province needs province-specific few-shot examples.
- **Manual review**: Spot-check the candidate discoveries list against RIB, PIR, and secondary scholarship to produce a precision-of-discoveries number.

## Methodology
Full research plan: [roman_ner_research_plan.md](roman_ner_research_plan.md).

## License
Code: MIT License. Data: CC BY-SA 4.0 (EDCS, LIRE source databases).
