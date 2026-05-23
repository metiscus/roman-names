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
- `data/` — Raw datasets (EDCS, LIRE) and evaluation sets.
- `scripts/` — Python pipeline: data acquisition, NER extraction, evaluation.
- `scripts/prompts/` — Versioned NER prompts.
- `docs/` — Implementation plans and research context.

## Current Status
- [x] Data acquisition complete (EDCS 465MB, LIRE 576MB).
- [x] Evaluation set generated: 433 Africa Proconsularis records with LIRE ground truth.
- [x] NER pipeline validated — see results below.
- [ ] Scale to full Africa Proconsularis corpus (~33k records).
- [ ] Manual review of discoveries list.

## Evaluation Results (Africa Proconsularis pilot, 433 records)

| Metric | Value | Notes |
|--------|-------|-------|
| Recall (raw) | 0.71 | Includes damaged inscriptions in denominator |
| **Recall (adjusted)** | **0.93** | Excluding lacunae where GT is unrecoverable from text |
| Precision (adjusted) | 0.73 | After filtering known imperial titulature |
| **F1 (adjusted)** | **0.82** | Primary headline metric |
| Potential discoveries | 226 | Names found by model, absent from LIRE |

**Key finding:** 65% of false negatives are inscriptions where the ground-truth name is partially or fully in lacunae (`[---]`). The model cannot recover these from the raw text — this is an inherent limit of the text-based approach, not a model failure.

## Evaluation Methodology Notes

Several non-obvious choices in `scripts/05_evaluate_ner.py`:

- **Praenomen expansion**: LIRE stores praenomens in abbreviated form (`Q.`, `T.`); the model expands them (`Quintus`, `Titus`). A lookup table maps abbreviations before signature comparison.
- **Word-overlap matching** (≥75% threshold with 6-char prefix): replaces simple substring matching to handle (a) predictions with extra cognomina and (b) Latin case ending variants (`Uttedius` vs `Uttedio`).
- **Imperial filtering**: Two-stage filter removes emperors and their family from the discoveries list — (1) `status` field keywords (`emperor`, `divus`, `caesar`, `augustus`, `imperator`); (2) inscription-level formula detection (`Imperatori Caesari...`, `Imperator Caesar...`).
- **Damage pre-filtering** (in `04c`): Inscriptions where >30% of characters are inside lacunae brackets are skipped before sending to the API, reducing cost on records unlikely to yield clean extractions.

## Future Directions

- **Scale**: Run the pipeline on all undamaged Africa Proconsularis records in EDCS (~33k).
- **Lacuna restoration**: For damaged records, an Ithaca-style model (cf. Assael et al., *Nature* 2022 — trained to restore damaged ancient Greek inscriptions) could eventually fill gaps that text-based NER cannot. This is a separate research direction.
- **Other provinces**: The validated pipeline is transferable; each province needs province-specific few-shot examples for local naming conventions.

## Methodology
Full research plan: [roman_ner_research_plan.md](roman_ner_research_plan.md).

## License
Code: MIT License. Data: CC BY-SA 4.0 (EDCS, LIRE source databases).
