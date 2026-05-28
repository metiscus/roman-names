# Week 1 Implementation Plan: Data Acquisition and Exploration

## Objective
Execute the initial steps (Week 1) of the Roman NER research plan: acquire the foundational datasets, finalize the Python environment, perform exploratory data analysis on the Egyptian inscriptions subset, and verify the Trismegistos (TM) APIs for ground-truth cross-referencing.

## Key Files & Context
- Environment: Existing `venv/`
- Data Directory: `data/` (to be created)
- Scripts Directory: `scripts/` (to be created)
- Targets: 
  - EDCS Dataset (DOI 10.5281/zenodo.7072337)
  - LIRE Dataset (DOI 10.5281/zenodo.8431452)

## Implementation Steps

1. **Install Dependencies:**
   - Run `pip install` within the existing `venv` to install: `pandas`, `geopandas`, `requests`, `tqdm`, `pyarrow`, `fastparquet`, and `anthropic`.

2. **Download Datasets:**
   - Create a `data/` directory.
   - Use `wget` or `curl` to download the EDCS 2022 dataset from Zenodo (`sdam-dat/edcs-2022-09-08.json` or equivalent zip/tar).
   - Use `wget` or `curl` to download the LIRE dataset from Zenodo.

3. **Data Exploration Script (`scripts/01_explore_egypt.py`):**
   - Write a script to load the EDCS JSON file via `pandas`.
   - Filter the dataset for Egyptian provinces (e.g., matching "Aegyptus", "Thebais", "Arcadia", etc. in the `province` field).
   - Print the total count of Egyptian records.
   - Sample and print 10-20 raw inscription texts to understand standard abbreviations and data structure.
   - Export a small list of sampled EDCS-IDs (e.g., 50 records) to a temporary JSON or CSV file for API testing.

4. **TM API Verification Script (`scripts/02_test_tm_api.py`):**
   - Write a script to load the sampled EDCS-IDs.
   - Query the TM TexRelations API (`https://www.trismegistos.org/dataservices/texrelations/`) to see if cross-references exist for these IDs.
   - For a subset that returns TM PER_IDs, query the TM PerResponder API (`https://www.trismegistos.org/dataservices/rdf/per/?id={PER_ID}&format=json`).
   - Output the raw JSON responses to verify the structure and ensure we are not blocked by rate limits or authentication walls.

## Verification & Testing
- Ensure the datasets download successfully and are readable by pandas.
- Run `01_explore_egypt.py` and verify the console output shows reasonable sample texts and a record count.
- Run `02_test_tm_api.py` and verify the API returns valid JSON mappings rather than HTTP errors or empty results.