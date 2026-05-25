#!/usr/bin/env python3
"""Orchestrate the full per-province pipeline end to end.

Chain (in dependency order):
    eval_set  -> rebuild LIRE validation set         (03_generate_validation_set.py)
    ner       -> run NER over the corpus             (06_run_full_corpus.py)
    export    -> build the flagged deliverable       (06_export_to_dataset.py)
    eval      -> score against LIRE GT               (05b_eval_from_corpus.py)
    cluster   -> dedup into clusters                 (08_cluster_attestations.py)
    webapp    -> emit geojson + clusters for the map (09_build_webapp_data.py)

Two scripts take the EDCS *province name* (with a space, first word capitalised,
e.g. "Pannonia inferior"); the rest take the *slug* ("pannonia_inferior"). This
orchestrator keeps both in one registry so the right form goes to each script.

IMPORTANT — `06_run_full_corpus.py` resumes by record ID: re-running it over an
existing output file does nothing (every ID is already present). So for a real
rerun on a new model/prompt the NER stage backs up the old output and starts
fresh. Pass --resume to append instead (e.g. to continue an interrupted run).

Examples:
    python scripts/run_pipeline.py                          # all provinces, all stages, fresh NER
    python scripts/run_pipeline.py --province britannia
    python scripts/run_pipeline.py --stages export,eval,cluster,webapp   # regen only, no API cost
    python scripts/run_pipeline.py --resume                 # append to existing NER output
    python scripts/run_pipeline.py --dry-run
"""
import argparse
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
OUTPUT_DIR = REPO_ROOT / "data" / "output"
PY = sys.executable

# slug, EDCS province-name (exact string in the EDCS 'province' field), has LIRE eval set.
# baetica and moesia_inferior have corpus output but are not in the maintained set and
# lack eval GT — add a row here (has_eval=False) if you want them in the loop.
PROVINCES = [
    ("africa_proconsularis", "Africa proconsularis", True),
    ("britannia",            "Britannia",            True),
    ("dacia",                "Dacia",                True),
    ("dalmatia",             "Dalmatia",             True),
    ("noricum",              "Noricum",              True),
    ("numidia",              "Numidia",              True),
    ("pannonia_inferior",    "Pannonia inferior",    True),
    ("pannonia_superior",    "Pannonia superior",    True),
    ("moesia_superior",      "Moesia superior",      False),
]

ALL_STAGES = ["eval_set", "ner", "export", "eval", "cluster", "webapp"]
EVAL_ONLY_STAGES = {"eval_set", "eval"}  # skipped for provinces without a LIRE eval set


def stage_cmd(stage, slug, edcs_name, model, workers):
    s = str(SCRIPTS)
    if stage == "eval_set":
        return [PY, f"{s}/03_generate_validation_set.py", "--province", edcs_name]
    if stage == "ner":
        return [PY, f"{s}/06_run_full_corpus.py", "--province", edcs_name,
                "--model", model, "--workers", str(workers)]
    if stage == "export":
        return [PY, f"{s}/06_export_to_dataset.py", "--province", slug,
                "--province-name", edcs_name]
    if stage == "eval":
        return [PY, f"{s}/05b_eval_from_corpus.py", "--province", slug]
    if stage == "cluster":
        return [PY, f"{s}/08_cluster_attestations.py", "--province", slug]
    if stage == "webapp":
        return [PY, f"{s}/09_build_webapp_data.py", "--province", slug]
    raise ValueError(f"unknown stage: {stage}")


def backup_ner_output(slug):
    out = OUTPUT_DIR / f"{slug}_ner_full.jsonl"
    if not out.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = out.parent / f"{out.name}.bak.{ts}"
    shutil.move(str(out), str(dest))
    return dest


def summary(results):
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for slug, stage, status, dt in results:
        print(f"  {slug:24} {stage:9} {status:14} {dt:7.1f}s")
    fails = [r for r in results if r[2].startswith("FAIL")]
    print(f"\n{len(results)} stage runs · {len(fails)} failed")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--province", default="all", help="slug or 'all' (default: all)")
    ap.add_argument("--stages", default=",".join(ALL_STAGES),
                    help=f"comma-separated subset of {ALL_STAGES}")
    ap.add_argument("--model", default="gemini-2.5-flash-lite")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--resume", action="store_true",
                    help="ner stage: append to existing output instead of a fresh "
                         "run (default: back up the old output and rerun from scratch)")
    ap.add_argument("--exclude", default="",
                    help="comma-separated slugs to skip (e.g. an already-done province)")
    ap.add_argument("--continue-on-error", action="store_true",
                    help="move to the next province on failure (default: stop)")
    ap.add_argument("--dry-run", action="store_true", help="print commands, run nothing")
    args = ap.parse_args()

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    bad = [s for s in stages if s not in ALL_STAGES]
    if bad:
        ap.error(f"unknown stage(s): {bad}; valid: {ALL_STAGES}")
    # Keep canonical dependency order regardless of how the user listed them.
    stages = [s for s in ALL_STAGES if s in stages]

    known = {p[0] for p in PROVINCES}
    if args.province == "all":
        provinces = list(PROVINCES)
    else:
        wanted = [s.strip() for s in args.province.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in known]
        if unknown:
            ap.error(f"unknown province(s): {unknown}; known: {', '.join(sorted(known))}")
        provinces = [p for p in PROVINCES if p[0] in wanted]

    excluded = {s.strip() for s in args.exclude.split(",") if s.strip()}
    if excluded - known:
        ap.error(f"unknown --exclude province(s): {sorted(excluded - known)}")
    if excluded:
        provinces = [p for p in provinces if p[0] not in excluded]
    if not provinces:
        ap.error("no provinces left to run after applying --province/--exclude")

    print("=" * 72)
    print("PIPELINE PLAN")
    print(f"  provinces : {', '.join(p[0] for p in provinces)}")
    print(f"  stages    : {', '.join(stages)}")
    print(f"  model     : {args.model}   workers: {args.workers}")
    print(f"  ner mode  : {'RESUME (append)' if args.resume else 'FRESH (backup + rerun)'}")
    if args.dry_run:
        print("  *** DRY RUN — nothing will execute ***")
    print("=" * 72)

    results = []
    for slug, edcs_name, has_eval in provinces:
        print(f"\n{'#' * 72}\n# {slug}  ({edcs_name})\n{'#' * 72}")
        for stage in stages:
            if stage in EVAL_ONLY_STAGES and not has_eval:
                print(f"  -- skip {stage}: no LIRE eval set for {slug}")
                results.append((slug, stage, "skipped", 0.0))
                continue

            if stage == "ner" and not args.resume and not args.dry_run:
                bak = backup_ner_output(slug)
                if bak:
                    print(f"  backed up existing NER output -> {bak.name}")

            cmd = stage_cmd(stage, slug, edcs_name, args.model, args.workers)
            print(f"\n>>> [{slug}] {stage}\n    {shlex.join(cmd)}")
            if args.dry_run:
                results.append((slug, stage, "dry-run", 0.0))
                continue

            t0 = time.time()
            rc = subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode
            dt = time.time() - t0
            status = "ok" if rc == 0 else f"FAIL(rc={rc})"
            results.append((slug, stage, status, dt))
            print(f"<<< [{slug}] {stage}: {status} in {dt:.1f}s")

            if rc != 0:
                if args.continue_on_error:
                    print(f"  !! {stage} failed — skipping remaining stages for {slug}")
                    break
                print("\nABORTING. Re-run with --continue-on-error to skip past failures.")
                summary(results)
                sys.exit(1)

    summary(results)


if __name__ == "__main__":
    main()
