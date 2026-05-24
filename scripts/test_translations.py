"""
Test script: sample ~25 inscriptions across provinces and types,
translate with Gemini 2.5 Flash, print results for evaluation.
"""
import json
import os
import random
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()

PROVINCES = [
    'africa_proconsularis', 'britannia', 'dacia', 'dalmatia',
    'moesia_superior', 'noricum', 'pannonia_inferior', 'pannonia_superior'
]

TARGET_TYPES = [
    'tituli sepulcrales',
    'tituli sacri',
    'tituli honorarii',
    'miliaria',
    'carmina, tituli sepulcrales',
    'inscriptiones christianae, tituli sepulcrales',
    'unknown',
]

PROMPT = """You are an expert in classical Latin epigraphy. I will give you the text of a Roman inscription as printed in a scholarly edition (with editorial conventions: square brackets for restorations, lacunae marked [---], etc.).

Please provide:
1. An English translation of the inscription text (readable, not overly literal).
2. A single sentence describing what this inscription records (e.g. "A funerary dedication by a freedman to his patron, dating to the 1st century AD.").

Respond in JSON with two keys: "translation" and "summary".

Inscription text:
{text}"""


def load_candidates():
    by_type: dict[str, list] = {}
    for prov in PROVINCES:
        p = Path(f"webapp/data/enrichment_{prov}.json")
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        for edcs_id, rec in data.items():
            text = rec.get('text_edition', '')
            itype = rec.get('inscription_type', '') or 'unknown'
            if not text or len(text) < 80:
                continue
            entry = {
                'edcs_id': edcs_id,
                'text': text,
                'type': itype,
                'province': prov,
                'publication': rec.get('publication', ''),
            }
            if itype not in by_type:
                by_type[itype] = []
            by_type[itype].append(entry)
    return by_type


def pick_samples(by_type, n=25):
    samples = []
    # First, one from each target type
    rng = random.Random(42)
    for t in TARGET_TYPES:
        items = by_type.get(t, [])
        if items:
            samples.append(rng.choice(items))

    # Fill remaining slots from high-count buckets, ensuring province diversity
    covered_provinces = {s['province'] for s in samples}
    remaining = n - len(samples)
    fallback_pool = []
    for t, items in sorted(by_type.items(), key=lambda x: -len(x[1])):
        for item in items:
            if item not in samples:
                fallback_pool.append(item)

    # Prioritise under-represented provinces
    uncovered = [i for i in fallback_pool if i['province'] not in covered_provinces]
    covered_extra = [i for i in fallback_pool if i['province'] in covered_provinces]
    candidates = uncovered + covered_extra

    seen_ids = {s['edcs_id'] for s in samples}
    for item in candidates:
        if remaining <= 0:
            break
        if item['edcs_id'] not in seen_ids:
            samples.append(item)
            seen_ids.add(item['edcs_id'])
            remaining -= 1

    rng.shuffle(samples)
    return samples


def translate(client, text: str) -> dict:
    prompt = PROMPT.format(text=text)
    resp = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type='application/json',
        ),
    )
    raw = resp.text.strip()
    return json.loads(raw)


def main():
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print('ERROR: GEMINI_API_KEY not set in .env', file=sys.stderr)
        sys.exit(1)

    # Run from repo root
    if not Path('webapp/data').exists():
        os.chdir(Path(__file__).parent.parent)

    by_type = load_candidates()
    total = sum(len(v) for v in by_type.values())
    print(f"Candidate pool: {total:,} inscriptions across {len(by_type)} types\n")

    samples = pick_samples(by_type, n=25)
    print(f"Selected {len(samples)} samples:\n")
    for i, s in enumerate(samples, 1):
        print(f"  {i:2d}. {s['edcs_id']}  [{s['province']}]  {s['type']}")
    print()

    client = genai.Client(api_key=api_key)

    for i, s in enumerate(samples, 1):
        print(f"{'='*70}")
        print(f"[{i}/{len(samples)}] {s['edcs_id']}  |  {s['province']}  |  {s['type']}")
        if s['publication']:
            print(f"Ref: {s['publication']}")
        print(f"\nLatin text:\n{s['text']}\n")
        try:
            result = translate(client, s['text'])
            print(f"Translation:\n{result.get('translation', '(none)')}\n")
            print(f"Summary: {result.get('summary', '(none)')}")
        except Exception as e:
            print(f"ERROR: {e}")
        print()


if __name__ == '__main__':
    main()
