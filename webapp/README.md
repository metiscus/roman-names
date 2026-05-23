# Roman Name Attestations Webapp

A static map visualization of Roman name attestations in Africa Proconsularis.

## Features

- **Interactive Map:** Powered by Leaflet and OpenStreetMap.
- **Marker Clustering:** Handles thousands of data points efficiently.
- **Prosopographical Clusters:** Link between different inscriptions identified as mentioning the same person.
- **Filtering:** Filter by name, confidence, gender, and special flags (Imperial, Deity, Fragmentary).
- **Direct Links:** Each inscription links back to its original record on the [Epigraphik-Datenbank Clauss-Slaby (EDCS)](https://db.edcs.eu/).

## Local Development

To view the webapp locally:

1. Ensure you have generated the data artifacts (see below).
2. Open `webapp/index.html` in any modern web browser. No local server is required as it uses relative paths for data.

## Regenerating Data

If the underlying research data changes, you can regenerate the webapp artifacts by running:

```bash
python scripts/09_build_webapp_data.py
```

This script reads `data/roman_names_africa_proconsularis.parquet` and produces:
- `webapp/data/inscriptions.geojson`
- `webapp/data/clusters.json`

## Deployment

This webapp is designed for hosting on **GitHub Pages**. Simply point GitHub Pages to the `webapp/` folder on your `main` branch.

## Data Sources

- **EDCS (Epigraphik-Datenbank Clauss-Slaby):** Source of inscription texts and metadata.
- **LIRE (Latin Inscriptions of the Roman Empire):** Source of geographical coordinates for inscriptions.

## License

The data is provided under **CC BY-SA**.
