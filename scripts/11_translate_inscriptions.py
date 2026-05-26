"""
Translate inscription text using Gemini 2.5 Flash-Lite.

Reads per-province enrichment JSON files, finds records with `text_edition`
but no `translation` yet, calls the API in batches, and writes results back
incrementally.

When `text_edition` is absent, falls back to `raw_text` from the province
GeoJSON (epigraphic notation with parenthesised expansions).

Usage:
    python scripts/11_translate_inscriptions.py --province britannia
    python scripts/11_translate_inscriptions.py --province all --limit 500
    python scripts/11_translate_inscriptions.py --province africa_proconsularis --dry-run
    python scripts/11_translate_inscriptions.py --province all --force  # re-translate existing
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors

load_dotenv()

PROVINCES = [
    'africa_proconsularis', 'britannia', 'dacia', 'dalmatia',
    'moesia_superior', 'noricum', 'numidia', 'pannonia_inferior', 'pannonia_superior'
]

MODEL = 'gemini-2.5-flash-lite'  # matches the NER pipeline; override with --model
MIN_EDITION_LENGTH = 20   # minimum chars for text_edition to be worth translating
MIN_RAW_LENGTH = 15       # minimum chars for raw_text fallback
BATCH_SIZE = 10
CHECKPOINT_EVERY = 50  # save after every N translations

BATCH_PROMPT = """You are an expert in classical Latin epigraphy. I will give you a JSON array of Roman inscription texts as printed in scholarly editions (square brackets enclose restorations or missing characters; [---] marks illegible lacunae).

For each inscription provide:
1. An English translation (readable, not overly literal; preserve proper names).
2. A single sentence describing what this inscription records (type of monument, dedicant, recipient, approximate date if inferable).

Respond with a JSON array in the same order as the input. Each element must have exactly three keys: "id" (the EDCS-ID from the input), "translation", and "summary".

Inscriptions:
{items_json}"""


def load_enrichment(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def save_enrichment(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8'
    )


def load_raw_text_lookup(province: str) -> dict[str, str]:
    """Build edcs_id → raw_text from the province GeoJSON."""
    path = Path(f'webapp/data/inscriptions_{province}.geojson')
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    return {
        f['properties']['edcs_id']: f['properties'].get('raw_text', '')
        for f in data.get('features', [])
        if f['properties'].get('raw_text')
    }


def find_candidates(enrichment: dict, raw_lookup: dict, force: bool) -> list[tuple[str, str]]:
    """Return (edcs_id, text) pairs that need translation.

    Prefers text_edition; falls back to raw_text for records without one.
    """
    out = []
    for edcs_id, rec in enrichment.items():
        if not force and rec.get('translation'):
            continue
        edition = rec.get('text_edition', '')
        if edition and len(edition) >= MIN_EDITION_LENGTH:
            out.append((edcs_id, edition))
        elif len(edition) < MIN_EDITION_LENGTH and edcs_id in raw_lookup:
            raw = raw_lookup[edcs_id]
            if len(raw) >= MIN_RAW_LENGTH:
                out.append((edcs_id, raw))
        elif edition and len(edition) >= MIN_RAW_LENGTH:
            # short edition with no raw fallback — use it anyway
            out.append((edcs_id, edition))
    return out


def translate_batch(client, batch: list[tuple[str, str]]) -> list[dict]:
    """Translate a batch of (edcs_id, text) pairs. Returns list of {id, translation, summary}."""
    items = [{'id': edcs_id, 'text': text} for edcs_id, text in batch]
    prompt = BATCH_PROMPT.format(items_json=json.dumps(items, ensure_ascii=False))
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type='application/json',
            thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return json.loads(resp.text.strip())


def process_province(province: str, client, args, batch_size: int = BATCH_SIZE) -> tuple[int, int]:
    """Returns (translated, errors)."""
    path = Path(f'webapp/data/enrichment_{province}.json')
    enrichment = load_enrichment(path)
    if not enrichment:
        print(f"  [{province}] No enrichment file found — skipping.")
        return 0, 0

    raw_lookup = load_raw_text_lookup(province)
    candidates = find_candidates(enrichment, raw_lookup, args.force)
    already_done = sum(1 for r in enrichment.values() if r.get('translation'))

    print(f"\n[{province}]")
    print(f"  {len(enrichment):,} enrichment records")
    print(f"  {already_done:,} already translated")
    print(f"  {len(candidates):,} to translate")

    if not candidates:
        return 0, 0

    if args.limit:
        full_count = len(candidates)
        candidates = candidates[:args.limit]
        if len(candidates) < full_count:
            print(f"  (limited to {len(candidates)} of {full_count} by --limit)")

    if args.dry_run:
        n_batches = (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  DRY RUN — would translate {len(candidates)} records in {n_batches} batches of {BATCH_SIZE}")
        for edcs_id, text in candidates[:5]:
            print(f"    {edcs_id}: {text[:80]}…")
        if len(candidates) > 5:
            print(f"    … and {len(candidates) - 5} more")
        return 0, 0

    translated = 0
    errors = 0
    checkpoint_due = 0
    total = len(candidates)

    # Process in batches
    for batch_start in range(0, total, batch_size):
        batch = candidates[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        print(f"  Batch {batch_num}/{total_batches} ({batch_start+1}–{min(batch_start+BATCH_SIZE, total)}/{total})… ", end='', flush=True)

        retry = 0
        while True:
            try:
                results = translate_batch(client, batch)
                # Index results by id in case order shifts
                by_id = {r['id']: r for r in results if isinstance(r, dict)}
                batch_ok = 0
                for edcs_id, _ in batch:
                    r = by_id.get(edcs_id)
                    if r and r.get('translation'):
                        enrichment[edcs_id]['translation'] = r['translation']
                        enrichment[edcs_id]['summary'] = r.get('summary', '')
                        translated += 1
                        checkpoint_due += 1
                        batch_ok += 1
                    else:
                        errors += 1
                print(f"OK ({batch_ok}/{len(batch)})")
                break
            except genai_errors.APIError as e:
                if '429' in str(e) or 'quota' in str(e).lower() or 'rate' in str(e).lower():
                    wait = 30 * (2 ** retry)
                    print(f"rate-limited, waiting {wait}s…", end='', flush=True)
                    time.sleep(wait)
                    retry += 1
                    if retry > 4:
                        print("giving up on batch")
                        errors += len(batch)
                        break
                else:
                    print(f"API error: {e}")
                    errors += len(batch)
                    break
            except Exception as e:
                print(f"error: {e}")
                errors += len(batch)
                break

        if checkpoint_due >= CHECKPOINT_EVERY:
            save_enrichment(path, enrichment)
            print(f"  (checkpoint saved — {translated} done so far)")
            checkpoint_due = 0

    # Final save
    save_enrichment(path, enrichment)
    print(f"  Saved {path} — {translated} translated, {errors} errors")
    return translated, errors


def main():
    global MODEL
    parser = argparse.ArgumentParser(description='Translate inscription text with Gemini 2.5 Flash-Lite')
    parser.add_argument('--province', default='all',
                        help=f'Province slug or "all". Choices: {", ".join(PROVINCES)}')
    parser.add_argument('--model', default=MODEL,
                        help=f'Gemini model (default: {MODEL})')
    parser.add_argument('--limit', type=int, default=0,
                        help='Max records to translate per province (0 = no limit)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be translated without calling the API')
    parser.add_argument('--force', action='store_true',
                        help='Re-translate records that already have a translation')
    parser.add_argument('--batch-size', type=int, default=BATCH_SIZE,
                        help=f'Inscriptions per API call (default: {BATCH_SIZE})')
    args = parser.parse_args()
    MODEL = args.model

    if not Path('webapp/data').exists():
        os.chdir(Path(__file__).parent.parent)

    if not args.dry_run:
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            print('ERROR: GEMINI_API_KEY not set in .env', file=sys.stderr)
            sys.exit(1)
        client = genai.Client(api_key=api_key)
    else:
        client = None

    provinces = PROVINCES if args.province == 'all' else [args.province]
    if args.province != 'all' and args.province not in PROVINCES:
        print(f'ERROR: unknown province "{args.province}"', file=sys.stderr)
        sys.exit(1)

    total_translated = 0
    total_errors = 0
    for prov in provinces:
        t, e = process_province(prov, client, args, args.batch_size)
        total_translated += t
        total_errors += e

    print(f'\nDone. Total translated: {total_translated}, errors: {total_errors}')


if __name__ == '__main__':
    main()
