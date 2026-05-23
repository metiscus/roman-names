# NER-Based Personal Name Extraction from Latin Inscriptions
## Research Plan — May 2026

---

## 1. Project Summary

Extract and classify personal names from the corpus of Latin inscriptions in the Roman world using LLM-based Named Entity Recognition, validate the methodology against the Trismegistos People database (which has dense coverage for Egypt), then extend the pipeline to provinces with no existing prosopographical coverage.

The deliverable is a structured, openly published dataset: one row per name attestation, with name components classified (praenomen, nomen, cognomen, other), linked to source inscription, province, findspot, and date range. Not a prosopography (no entity resolution / person-identification claims), but a name index that future prosopographical work can build on.

---

## 2. Prior Work and Gap

### What Exists

| Resource | Coverage | Strengths | Limitations |
|----------|----------|-----------|-------------|
| **EDCS** (Clauss-Slaby) | ~542k Latin inscriptions, all provinces | Largest single corpus, full text | No structured person/name fields |
| **EDH** (Heidelberg) | ~81k inscriptions | Better metadata, API access | Smaller corpus |
| **LIRE** (SDAM, Aarhus) | ~136k inscriptions (merged EDCS+EDH) | Geolocated, dated, deduplicated | Subset: only geolocated + dated records |
| **Trismegistos People** | ~569k name attestations, Egypt only | Gold-standard person identification | Egypt only, documentary texts (papyri/ostraca), not monumental epigraphy |
| **PIR** | ~14k individuals, Imperial period | Scholarly prosopography | Elite individuals only |
| **DPRR** | ~6k individuals, Republic | Searchable online | Magistrates/elites only |

### The Gap

No structured name index exists for the full EDCS corpus outside Egypt. Trismegistos director Mark Depauw stated in 2014 that an NER-based approach could produce one, but wrote in 2022 that "8 years later this has not yet materialized" due to lack of funding.

LLM-based NER is now capable enough to attack this problem at scale, but no published work has validated an LLM pipeline against the TM People ground truth for Latin epigraphic texts.

---

## 3. Methodology

### Phase 1: Pilot and Validation (Egypt)

**Objective:** Validate the NER pipeline against TM People for Egyptian Latin inscriptions.

#### 3.1 Data Acquisition

1. **EDCS dataset (SDAM 2022 extract)**
   - Source: Zenodo, DOI 10.5281/zenodo.7072337
   - Format: JSON, ~465 MB, 537k records
   - License: CC BY-SA
   - Filter to: `province == "Aegyptus"` (and related provinces: Aegyptus Herculia, Aegyptus Iovia, Thebais, Arcadia, etc.)
   - Key fields: `EDCS-ID`, `inscription`, `province`, `place`, `dating from`, `dating to`, `inscr_type`

2. **LIRE dataset** (optional enrichment)
   - Source: Zenodo, DOI 10.5281/zenodo.5776109
   - Format: GeoJSON/Parquet, 136k records
   - Provides coordinates and merged EDH metadata for records that overlap

3. **Trismegistos People (validation ground truth)**
   - Access method: TM APIs (TexRelations + PerResponder)
     - TexRelations API: `https://www.trismegistos.org/dataservices/texrelations/`
       - Input: EDCS inscription ID → Output: TM Text ID
     - PerResponder API: `https://www.trismegistos.org/dataservices/rdf/per/?id={PER_ID}&format=json`
       - Input: TM PER_ID → Output: person record with name, attestation links
   - Limitation: one-record-at-a-time; no bulk download without institutional access
   - Strategy: build a validation sample of 500–1000 inscriptions, not the full corpus
   - Alternative: contact TM team directly for a data extract (see Section 6)

4. **Reference name lists** (for classification heuristics)
   - Kajanto, *The Latin Cognomina* (1965) — cognomen frequency lists
   - Solin & Salomies, *Repertorium Nominum Gentilium et Cognominum Latinorum* (1994)
   - Standard praenomen abbreviation table (18 canonical praenomina)
   - These may need to be digitized or sourced from existing digitization efforts

#### 3.2 NER Pipeline Design

The core task: given an inscription text like

```
D(is) M(anibus) / M(arcus) Aur(elius) Maxim/us vet(eranus) vix(it) / ann(os) LXV
```

extract `Marcus Aurelius Maximus` and classify as `praenomen: Marcus`, `nomen: Aurelius`, `cognomen: Maximus`.

**Challenges specific to epigraphic Latin:**
- Heavy abbreviation (`M` for Marcus, `AVR` for Aurelius, `VET` for veteranus)
- Line breaks indicated by `/` that split words mid-name
- Lacunae: `[---]`, `[Mar]cus`, editorial reconstructions in brackets
- Formulaic context (D M, H S E, V A, etc.) — useful for segmentation
- Multiple people per inscription (dedicator, deceased, witnesses)
- Non-Latin names (Greek, Egyptian, Semitic) in Latin script
- Freed/slave names with status indicators (lib., ser., verna)

**Approach: LLM-based NER with structured output**

Use Claude API (or local Qwen on RTX 4090) with a prompt that:
1. Takes raw inscription text as input
2. Expands known abbreviations
3. Identifies all personal names
4. Classifies each name component
5. Returns structured JSON

```
Input:  "D M / M AVR MAXIM/VS VET VIX ANN LXV"
Output: {
  "persons": [
    {
      "raw_spans": ["M AVR MAXIM/VS"],
      "expanded": "Marcus Aurelius Maximus",
      "components": {
        "praenomen": "Marcus",
        "nomen": "Aurelius",
        "cognomen": "Maximus"
      },
      "status": "veteranus",
      "role": "deceased",
      "confidence": "high"
    }
  ]
}
```

**Prompt engineering considerations:**
- Include a reference list of standard abbreviations in the system prompt
- Include the 18 canonical praenomina and their abbreviations
- Provide 10–20 few-shot examples spanning common inscription types (funerary, votive, honorific, military)
- Ask the model to flag uncertain expansions
- Ask for role identification (dedicator, deceased, patron, freedman, etc.)

**Local vs API tradeoffs:**
- Claude API: higher quality, costs credits, rate limits
- Qwen 27B local: free, fast on 4090, but likely lower accuracy on abbreviated Latin
- Strategy: develop and test prompts on Claude, then try Qwen to see if quality is acceptable for bulk runs

#### 3.3 Validation Protocol

1. Select 500–1000 EDCS inscriptions from Egypt that have TM cross-references
2. Run NER pipeline on these inscriptions
3. Pull corresponding TM People records via API
4. Score:
   - **Name-level precision**: what fraction of names the pipeline found are real names (vs. false positives from place names, divine names, formulaic text)?
   - **Name-level recall**: what fraction of names TM has did the pipeline find?
   - **Component classification accuracy**: of correctly identified names, how often are praenomen/nomen/cognomen correctly assigned?
5. Error analysis: categorize failure modes (missed abbreviations, confused name/place, wrong component assignment, etc.)
6. Iterate on prompt until metrics stabilize

**Target metrics** (based on prior NER work on Latin):
- Precision ≥ 85%
- Recall ≥ 80%
- Component classification ≥ 90% for names correctly identified

**Important caveat:** TM People covers documentary texts (papyri) while EDCS covers monumental inscriptions (stone). The overlap for Egypt may be limited. Before committing to Egypt as the validation province, run the TexRelations API on a sample of EDCS Egyptian IDs to measure how many actually have TM cross-references. If overlap is too thin, consider using EDH's person fields as an alternative ground truth (EDH has structured person data for its ~81k inscriptions).

---

### Phase 2: Target Province

**Objective:** Apply the validated pipeline to a province with no existing structured name data.

#### Candidate Provinces (ranked by suitability)

| Province | Est. EDCS Records | Why Good | Why Hard |
|----------|-------------------|----------|----------|
| **Africa Proconsularis** | ~15,000+ | Large corpus, diverse names (Libyan/Punic + Roman), understudied | Punic/Libyan names may confuse classifier |
| **Hispania Citerior** | ~15,000+ | Large corpus, romanization study potential | Less exotic, more "standard" Roman names |
| **Britannia** | ~3,000+ | Manageable size, Celtic substrate names, high scholarly interest | Small corpus limits statistical claims |
| **Pannonia** | ~5,000+ | Military province, good for studying army demographics | Mix of Celtic, Illyrian, Roman names |

Recommendation: **Africa Proconsularis** — large enough to be statistically interesting, diverse enough to stress-test the pipeline, and a region where a structured name index would genuinely fill a gap.

#### Phase 2 Workflow

1. Filter EDCS/LIRE to target province
2. Run validated NER pipeline (adjusting few-shot examples for provincial naming patterns)
3. Manual spot-check of ~200 records for quality assurance
4. Produce output dataset (see Section 4)
5. Basic analysis: name frequency distributions, geographic clustering, temporal trends

---

### Phase 3: Extension to Full Corpus

Once the pipeline is validated on Egypt and applied to one province, extension to the remaining ~60 provinces is primarily a compute and QA problem.

**Scaling considerations:**
- ~537k inscriptions × ~$0.01–0.05 per API call = $5k–$27k on Claude API at full scale
- Local LLM (Qwen on 4090): essentially free but slower and potentially lower quality
- Hybrid approach: use local model for bulk, Claude for low-confidence flagged records
- QA: can't hand-check everything; statistical sampling per province (50–100 records each)
- Some provinces will need province-specific few-shot examples (Greek East names differ from Latin West)

**This phase is optional and probably requires collaboration or grant funding.** The pilot + one province is a complete, publishable project on its own.

---

## 4. Output Schema

Each row in the output dataset represents one name attestation (not one person — no entity resolution claims).

```
{
  "attestation_id": "ATT-00001",
  "source_id": "EDCS-12345678",
  "source_db": "EDCS",
  "tm_text_id": null,
  "province": "Africa Proconsularis",
  "findspot": "Carthago",
  "latitude": 36.8528,
  "longitude": 10.3233,
  "date_from": 100,
  "date_to": 200,
  "inscription_type": "epitaph",
  "raw_text": "D M S / Q IVLIVS FORTVNATVS / VIX ANN LXXII",
  "person_index": 0,
  "raw_name_span": "Q IVLIVS FORTVNATVS",
  "expanded_name": "Quintus Iulius Fortunatus",
  "praenomen": "Quintus",
  "nomen": "Iulius",
  "cognomen": "Fortunatus",
  "supernomen": null,
  "status_indicators": [],
  "role_in_inscription": "deceased",
  "confidence": "high",
  "flags": [],
  "model_used": "claude-sonnet-4-20250514",
  "pipeline_version": "0.1.0"
}
```

Output format: Parquet (primary), with CSV and JSON exports. Deposited on Zenodo with DOI.

---

## 5. Technical Requirements

### Software / Infrastructure

- **Python 3.10+** with: `pandas`, `geopandas`, `requests`, `json`, `anthropic` SDK, `tqdm`
- **Claude API access** (for NER prompt development and high-confidence runs)
- **Local LLM** (optional, for bulk processing): Qwen3-27B via llama.cpp on RTX 4090
- **Git** for version control of scripts and prompt iterations
- **Zenodo** account for data publication

### Compute Estimates

| Task | Method | Est. Time | Est. Cost |
|------|--------|-----------|-----------|
| Egypt validation (1000 inscriptions) | Claude API | ~2 hours | ~$10–50 |
| TM API validation data pull | TexRelations + PerResponder | ~4 hours (rate-limited) | Free |
| Target province NER (~15k inscriptions) | Claude API | ~12 hours | ~$150–750 |
| Target province NER (~15k inscriptions) | Qwen local | ~6–8 hours | Free |
| Full corpus (~537k inscriptions) | Qwen local | ~10–14 days | Free |
| Full corpus (~537k inscriptions) | Claude API | ~2 weeks | ~$5k–27k |

### Data Storage

- EDCS JSON: ~465 MB
- LIRE Parquet: ~50 MB
- TM validation extract: <10 MB
- Output dataset (one province): ~5–20 MB
- Output dataset (full corpus): ~200–500 MB

---

## 6. Contacts and Outreach

### Required Before Starting

None. All Phase 1 data (EDCS, LIRE, TM APIs) is openly accessible. You can begin immediately.

### Recommended Outreach (after preliminary results)

| Who | Why | When |
|-----|-----|------|
| **Mark Depauw** (KU Leuven, TM director) | Validate methodology against TM People; possible bulk data access; potential collaboration. He has publicly stated this work needs doing. | After you have precision/recall numbers from Phase 1 |
| **Petra Heřmánková** (Aarhus, SDAM project) | She built the EDCS/LIRE datasets you're using. Courtesy notification + potential feedback on data quirks. | After Phase 1, before publication |
| **Anne Kolb** (U Zürich, new EDCS steward) | EDCS is being rebuilt at Zürich. Your structured output could feed back into the new system. | After Phase 2, when you have a province-level deliverable |
| **Jonathan Prag** (Oxford, I.Sicily / FAIR epigraphy) | Active in digital epigraphy standards and FAIR data. Could advise on output schema and interoperability. | When preparing for publication |

### Email Template (adapt after you have results)

> Subject: LLM-based NER validation against TM People — preliminary results
>
> Dear Prof. Depauw,
>
> I am an independent researcher working on automated personal name extraction from Latin inscriptions using large language models. I have run a pilot NER pipeline on [N] EDCS inscriptions from Egypt and validated the output against TM People records accessed via the PerResponder API, achieving [X]% precision and [Y]% recall at the name level.
>
> I am writing to ask whether you would be interested in reviewing the methodology, and whether a larger validation against the TM People REF table might be possible. My goal is to produce an openly published structured name index for provinces currently lacking prosopographical coverage, beginning with [target province].
>
> The pipeline code and preliminary dataset are available at [GitHub link]. I would be happy to share the full results and discuss how this might complement TM's ongoing work.
>
> Best regards,
> Steve [surname]

---

## 7. Publication Plan

### Primary Output
- **Dataset**: structured name attestation index for target province, deposited on Zenodo (CC BY-SA 4.0)
- **Code**: GitHub repository with full pipeline (prompts, scripts, evaluation code)

### Optional Paper
- Venue: *Digital Scholarship in the Humanities* (Oxford), *Journal of Data Mining and Digital Humanities*, or *JACT* / *Journal of Roman Studies* data note
- Framing: methodology validation (LLM NER vs. TM ground truth) + application to new province
- Co-authorship: if TM team contributes data or validation, offer co-authorship

### What Makes This Citable
1. First published validation of LLM-based NER against TM People for Latin epigraphy
2. First structured name index for [target province]
3. Reproducible pipeline applicable to remaining provinces
4. Open data and open code

---

## 8. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Low EDCS↔TM overlap for Egypt (documentary vs. monumental texts) | Medium | High — undermines validation | Check overlap before committing; fall back to EDH person fields as alternative ground truth |
| LLM performs poorly on heavily abbreviated text | Medium | High | Preprocessing step to expand standard abbreviations before LLM sees text; extensive few-shot examples |
| TM subscription wall blocks API access | Low | Medium | Rate-limit politely; contact TM team; use EDH as fallback |
| Name component classification is ambiguous (nomen vs. cognomen for late empire) | High | Low | Document ambiguity honestly; flag uncertain classifications; provide raw extraction alongside classification |
| Someone publishes the same thing first | Low | Medium | Move quickly; the validation-against-TM angle is distinctive |
| Scope creep into entity resolution | High | Medium | Explicitly out of scope. The deliverable is a name index, not a prosopography. |

---

## 9. Suggested Timeline

| Week | Task |
|------|------|
| 1 | Download EDCS and LIRE datasets. Explore Egyptian inscriptions: how many, what do they look like, what inscription types. Check EDCS↔TM overlap via TexRelations API sample. |
| 2 | Design NER prompt. Build evaluation harness. Hand-annotate 50 inscriptions as dev set. Iterate prompt. |
| 3 | Pull TM validation data for 500–1000 inscriptions via API. Run NER on validation set. Score precision/recall. Error analysis and prompt refinement. |
| 4 | Finalize Egypt validation. Write up methodology. Begin target province NER run. |
| 5–6 | Complete target province run. Manual spot-check 200 records. Basic frequency/geographic analysis. |
| 7–8 | Package dataset for Zenodo. Write README and documentation. Draft outreach emails. Optional: draft paper. |

---

## 10. Quick-Start Checklist

- [ ] Download EDCS 2022 JSON from Zenodo (DOI 10.5281/zenodo.7072337)
- [ ] Download LIRE parquet from Zenodo (DOI 10.5281/zenodo.5776109)
- [ ] Set up Python environment with required packages
- [ ] Filter EDCS to Egyptian provinces; count records and inspect inscription text samples
- [ ] Test TM TexRelations API with 10 EDCS IDs to verify cross-reference availability
- [ ] Test TM PerResponder API with returned PER_IDs to verify data format
- [ ] Design initial NER prompt with 10 few-shot examples
- [ ] Hand-annotate 50 Egyptian inscriptions as development set
- [ ] Evaluate, iterate, proceed
