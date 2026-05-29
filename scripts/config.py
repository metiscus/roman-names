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

# ── Province registry ─────────────────────────────────────────────────────────
# Single source of truth for the provinces the pipeline manages. Each entry is
#   (slug, EDCS province-name, has_lire_eval_set)
# - slug: used in output/webapp filenames and as the --province value downstream.
# - EDCS province-name: the exact string in the EDCS 'province' field (passed to
#   03_generate_validation_set and 06_run_full_corpus).
# - has_eval: whether a LIRE ground-truth eval set exists/should be built (gates
#   the eval_set + eval stages).
# Both run_pipeline.py and 11_translate_inscriptions.py consume this, so adding a
# province here propagates everywhere — no per-script lists to keep in sync.
PROVINCES = [
    # slug,                  EDCS province name,      has_eval
    ("africa_proconsularis", "Africa proconsularis",  True),
    ("britannia",            "Britannia",             True),
    ("dacia",                "Dacia",                 True),
    ("dalmatia",             "Dalmatia",              True),
    ("noricum",              "Noricum",               True),
    ("numidia",              "Numidia",               True),
    ("pannonia_inferior",    "Pannonia inferior",     True),
    ("pannonia_superior",    "Pannonia superior",     True),
    ("moesia_superior",      "Moesia superior",       True),
    ("moesia_inferior",      "Moesia inferior",       True),
    ("baetica",              "Baetica",               True),
    ("lusitania",            "Lusitania",             True),
    ("hispania_citerior",    "Hispania citerior",     True),
    ("mauretania_tingitana",    "Mauretania Tingitana",    True),
    ("mauretania_caesariensis", "Mauretania Caesariensis", True),
    ("creta_et_cyrenaica",      "Creta et Cyrenaica",      True),
    ("aegyptus",              "Aegyptus",               True),
    ("corsica",                 "Corsica",                 True),
    ("sardinia",                "Sardinia",                True),
    ("sicilia",                 "Sicilia",                 True),
    ("gallia_narbonensis",     "Gallia Narbonensis",      True),
    ("belgica",                "Belgica",                 True),
    ("aquitanica",             "Aquitani(c)a",            True),
    ("germania_superior",      "Germania superior",       True),
    ("germania_inferior",      "Germania inferior",       True),
    ("etruria",                "Etruria / Regio VII",     True),
    ("latium_et_campania",     "Latium et Campania / Regio I", True),
]

PROVINCE_SLUGS = [slug for slug, _name, _has_eval in PROVINCES]

# Lookup: EDCS province name → slug (for scripts that receive the EDCS name)
EDCS_NAME_TO_SLUG = {edcs_name: slug for slug, edcs_name, _ in PROVINCES}
SLUG_TO_EDCS_NAME = {slug: edcs_name for slug, edcs_name, _ in PROVINCES}
