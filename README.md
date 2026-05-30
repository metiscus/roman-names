# Roman NER: Personal Name Extraction from Latin Inscriptions

Automated extraction and classification of personal names from the corpus of Latin inscriptions (*Epigraphik-Datenbank Clauss / Slaby*) using LLM-based Named Entity Recognition.

## Project Goal
Produce a structured, openly published index of personal names from Roman inscriptions across 27 provinces of the Roman Empire.

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
- [x] Scale to full corpus: 27 provinces, including Africa Proconsularis, Britannia, Numidia, Dalmatia, Pannonia Superior/Inferior, Noricum, Dacia, Moesia Superior/Inferior, Lusitania, Hispania Citerior, Baetica, Gallia Narbonensis, Aquitanica, Mauretania (both), and Italian regions.
- [x] Full rerun with hardened prompt (nominative normalization, abbreviation expansion, generic few-shots).
- [x] Prosopographical clustering across all provinces.
- [x] Interactive webapp with enriched popups, permalinks, and external database links.
- [x] English translations of inscription text across all provinces.
- [ ] Manual review of unmatched extraction candidates.

## Evaluation Results

Numbers are reported under the **corrected evaluation** (one-to-one matching + honest damage accounting; see methodology notes) against **LIRE v3.0** ground truth. Earlier figures (F1 up to 0.90) were inflated by one-to-many matching and over-generous damage exclusion.

| Province | Recall (adj) | Precision (adj) | F1 (adj) | Unmatched in LIRE |
|----------|--------------|-----------------|----------|-------------------|
| Africa Proconsularis | 0.73 | 0.75 | **0.74** | 133 |
| Apulia et Calabria | 0.85 | 0.89 | **0.87** | — |
| Britannia | 0.70 | 0.83 | **0.76** | 72 |
| Dacia | 0.75 | 0.79 | **0.77** | 125 |
| Dalmatia | 0.75 | 0.74 | **0.75** | 184 |
| Gallia Narbonensis | 0.69 | 0.70 | **0.70** | — |
| Hispania citerior | 0.74 | 0.78 | **0.76** | 140 |
| Lusitania | 0.63 | 0.65 | **0.64** | 90 |
| Mauretania Caesariensis | 0.82 | 0.89 | **0.85** | 22 |
| Moesia superior | 0.75 | 0.82 | **0.79** | 155 |
| Noricum | 0.75 | 0.82 | **0.78** | 204 |
| Numidia | 0.82 | 0.85 | **0.84** | 81 |
| Pannonia inferior | 0.73 | 0.79 | **0.76** | 133 |
| Pannonia superior | 0.73 | 0.78 | **0.75** | 161 |

> Precision is a **lower bound** — extractions absent from the LIRE ground truth are counted as false positives. These "unmatched" cases may reflect genuine attestations not yet in LIRE, model errors, or gaps in ground-truth coverage; they have not been manually reviewed. Gallia Narbonensis F1 is measured against EDH ground truth (2× validation density vs LIRE for that region). Remaining provinces in the webapp have not yet been formally evaluated.

**Key finding:** the majority of false negatives are inscriptions where the ground-truth name is partially or fully in lacunae (`[---]`). The model cannot recover these from the raw text — an inherent limit of the text-based approach, not a model failure.

## Evaluation Methodology Notes

Several non-obvious choices in `scripts/05_evaluate_ner.py`:

- **Praenomen expansion**: LIRE stores praenomens in abbreviated form (`Q.`, `T.`); the model expands them (`Quintus`, `Titus`). A lookup table maps abbreviations before signature comparison.
- **One-to-one (greedy bipartite) matching**: each prediction is matched to at most one ground-truth person and vice versa, so a single shared-nomen prediction cannot score a true positive against every GT person in a dense record. Token comparison uses a 6-char prefix with a length guard (so `Victor` does not match `Victorinus`) to absorb Latin case-ending variants (`Uttedius` vs `Uttedio`).
- **Damage accounting**: a GT name is only excluded from adjusted recall as "unrecoverable" when it is genuinely lacuna-dominated (`[---]` or >50% bracket characters), not on the presence of any single bracket.
- **Imperial filtering**: Two-stage filter removes emperors and their family from the unmatched candidates — (1) `status` field keywords (`emperor`, `divus`, `caesar`, `augustus`, `imperator`); (2) inscription-level formula detection (`Imperatori Caesari...`, `Imperator Caesar...`).
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

- **Lacuna restoration**: For damaged records, an Ithaca-style model (cf. Assael et al., *Nature* 2022) could recover names in lacunae — an inherent limit of the text-based approach.
- **Manual review**: Spot-check unmatched extraction candidates against RIB, PIR, and secondary scholarship to estimate the true positive rate among extractions absent from LIRE.
- **Additional provinces**: The pipeline is transferable to remaining EDCS provinces not yet processed.

## Methodology
Full research plan: [roman_ner_research_plan.md](roman_ner_research_plan.md).

## License and Attribution

Code is licensed under the MIT License. See [`LICENSE`](LICENSE).

Derived data artifacts are released under CC BY 4.0, matching the Zenodo
license metadata for the EDCS 2022 and LIRE v3.0 source datasets used here.
See [`DATA_LICENSE.md`](DATA_LICENSE.md) and [`ATTRIBUTION.md`](ATTRIBUTION.md)
for source citations, reuse terms, and attribution guidance.
