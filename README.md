# Roman NER: Personal Name Extraction from Latin Inscriptions

Automated extraction and classification of personal names from the corpus of Latin inscriptions (*Epigraphik-Datenbank Clauss / Slaby*) using LLM-based Named Entity Recognition.

## Project Goal
This project aims to produce a structured, openly published index of personal names mentioned in Roman inscriptions, starting with provinces currently lacking dense prosopographical coverage (e.g., Africa Proconsularis).

The pipeline uses the **Gemini 2.5 Flash** model with Structured Output to:
1. Identify individuals in raw Latin text.
2. Expand standard epigraphic abbreviations.
3. Classify name components (praenomen, nomen, cognomen).
4. Identify social status and gender.

## Repository Structure
- `data/`: Contains raw datasets (EDCS, LIRE) and evaluation sets.
- `scripts/`: Python pipeline for data acquisition, NER extraction, and evaluation.
- `docs/`: Implementation plans and research context.

## Current Status
- [x] Data acquisition and environment setup complete.
- [x] Initial pilot (Africa Proconsularis) validated against LIRE ground truth.
- [x] Currently executing a 500-record quantitative evaluation run.

## Methodology
The methodology is detailed in [roman_ner_research_plan.md](roman_ner_research_plan.md). We validate the LLM's performance against the structured `people` data in the LIRE dataset before applying it to the full 537k-record EDCS corpus.

## License
Code is available under the MIT License. Data used in this project is subject to the CC BY-SA 4.0 license of the source databases (EDCS, LIRE).
