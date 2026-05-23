# Roman Name Attestations Webapp

A static map visualization of Roman personal name attestations extracted from Latin inscriptions, covering Africa Proconsularis and Britannia.

## Features

- **Interactive Map:** Powered by Leaflet with DARE Roman-period base tiles.
- **Province Selector:** Switch between Africa Proconsularis and Britannia; map re-centers automatically.
- **Marker Clustering:** Handles thousands of data points efficiently.
- **Prosopographical Clusters:** Link attestations across inscriptions identified as likely the same individual.
- **Filtering:** Filter by name search, cluster confidence, gender, and flags (Imperial, Deity, Fragmentary).
- **Direct Links:** Each inscription links back to its record on [EDCS](https://db.edcs.eu/).

## Data

| Province | Inscriptions | Attestations | Eval F1 |
|---|---|---|---|
| Africa Proconsularis | 22,754 | 34,788 | 0.77 |
| Britannia | 6,966 | 9,094 | 0.86 |

Extracted using Gemini 2.5 Flash with structured output. Validated against [LIRE](https://doi.org/10.5281/zenodo.5776109) ground truth. Source: [EDCS 2022](https://db.edcs.eu/).

## Local Development

Serve from the `webapp/` directory with any static file server:

```bash
python3 -m http.server 8080 --directory webapp/
# then open http://localhost:8080
```

Opening `index.html` directly via `file://` will fail due to browser CORS restrictions on local JSON/GeoJSON fetches.

## Regenerating Data

Run the full pipeline for each province (requires Python venv with dependencies):

```bash
# Export NER results → parquet
python scripts/06_export_to_dataset.py --province africa_proconsularis
python scripts/06_export_to_dataset.py --province britannia --province-name "Britannia"

# Deduplicate / cluster
python scripts/08_cluster_attestations.py --province africa_proconsularis
python scripts/08_cluster_attestations.py --province britannia

# Build webapp data files
python scripts/09_build_webapp_data.py --province africa_proconsularis
python scripts/09_build_webapp_data.py --province britannia
```

Outputs per province: `webapp/data/inscriptions_{province}.geojson` and `webapp/data/clusters_{province}.json`.

## Deployment

Designed for **GitHub Pages**. Enable Pages in repo Settings → Pages → Source: GitHub Actions, then push to `main`. The Actions workflow in `.github/workflows/deploy.yml` handles the rest.

## Data Sources

- **EDCS:** Epigraphik-Datenbank Clauss-Slaby — inscription texts and metadata.
- **LIRE:** Latin Inscriptions of the Roman Empire — geographic coordinates and ground-truth people data used for validation.

## License

Data: CC BY-SA. Code: MIT.
