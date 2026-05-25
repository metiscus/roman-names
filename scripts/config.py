"""
Central data-path configuration.

All versioned source datasets are defined here. When a new dataset release
is available, update the relevant constant and all scripts pick it up
automatically.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# ── Versioned source datasets ─────────────────────────────────────────────────
# Update these when new releases are published on Zenodo.
# EDCS: https://zenodo.org/records/7072337  (current: 2022-09-12, v2.0)
# LIRE: https://zenodo.org/records/8431452  (current: v3.0, 2023-10)
EDCS_PATH = REPO_ROOT / "data" / "EDCS_text_cleaned_2022-09-12.json"
LIRE_PATH = REPO_ROOT / "data" / "LIRE_v3-0.geojson"

# ── Derived / cached data ─────────────────────────────────────────────────────
LIRE_ENRICHMENT_PATH = REPO_ROOT / "data" / "lire_enrichment.json"
R1B1_GT_PATH         = REPO_ROOT / "data" / "r1b1_gt.json"

# ── Output directories ────────────────────────────────────────────────────────
EVAL_DIR   = REPO_ROOT / "data" / "eval"
OUTPUT_DIR = REPO_ROOT / "data" / "output"
