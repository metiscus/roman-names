"""
A/B test: feed the model raw 'inscription' (with lacunae markers) vs 'clean_text_interpretive_word'
on the same sample of eval records, compare precision/recall/fragmentary signal.
"""
import os
import sys
import json
import random
import time
from google import genai
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import EDCS_PATH, EVAL_DIR, OUTPUT_DIR as _OUTPUT_DIR

load_dotenv()

SAMPLE_SIZE = 30
RANDOM_SEED = 7
OUTPUT_DIR = str(_OUTPUT_DIR / 'ab_test')

PRAENOMINA = {
    'Aulus', 'Appius', 'Gaius', 'Caius', 'Gnaeus', 'Decimus', 'Kaeso',
    'Lucius', 'Marcus', 'Manius', 'Mamercus', 'Numerius', 'Publius',
    'Quintus', 'Sextus', 'Servius', 'Spurius', 'Titus', 'Tiberius',
}

TRIBUS = {
    'Aemilia', 'Aniensis', 'Arnensis', 'Camilia', 'Claudia', 'Clustumina',
    'Collina', 'Cornelia', 'Esquilina', 'Fabia', 'Falerna', 'Galeria',
    'Horatia', 'Lemonia', 'Maecia', 'Menenia', 'Oufentina', 'Palatina',
    'Papiria', 'Pollia', 'Pomptina', 'Publilia', 'Pupinia', 'Quirina',
    'Romilia', 'Sabatina', 'Scaptia', 'Sergia', 'Stellatina', 'Suburana',
    'Teretina', 'Tromentina', 'Velina', 'Voltinia', 'Voturia',
}

BASE_RULES = f"""
PRAENOMEN RULES — critical:
- Only these 18 names are valid praenomina: {', '.join(sorted(PRAENOMINA))}
- Any name not in this list is NEVER a praenomen, even if it appears first.
- Iulius, Flavius, Aurelius, Valerius, etc. are NOMINA, not praenomina.
- If only one name is present with no praenomen, classify it as cognomen (not nomen).

TRIBUS (voting tribe) — must not be confused with nomen:
- The following words are Roman voting tribes, not family names. If present, record in status as 'tribus: X':
- {', '.join(sorted(TRIBUS))}

NAME FIELD RULES:
- praenomen, nomen, cognomen fields must contain ONLY name text.
- If a name element is missing or uncertain, use null — do not fill with gender or status values.

NAME COHERENCE — multiple cognomina / agnomen:
- When consecutive Latin name elements appear with NO separator between them, they belong to the SAME person.
- Separators: 'et', 'cum', filiation ('filius', 'filia', 'uxor'), verbs ('posuit', 'vixit', 'pia'), punctuation.
- Example: 'Aemilia Victoria Fipiorina pia vixit' → ONE person: nomen=Aemilia, cognomen='Victoria Fipiorina'.
"""

# Prompt A: current behavior — cleaned interpretive text
PROMPT_A = f"""You are an expert Latin epigrapher. Perform NER on the provided inscription batch.
For each person, extract praenomen, nomen, cognomen, gender, status, raw_name, fragmentary.
Set fragmentary=true if the name is visibly incomplete.
Expand abbreviations ('L.' → 'Lucius', etc.).
{BASE_RULES}
"""

# Prompt B: raw inscription with lacunae markers
PROMPT_B = f"""You are an expert Latin epigrapher. Perform NER on the provided inscription batch.
For each person, extract praenomen, nomen, cognomen, gender, status, raw_name, fragmentary.
Expand abbreviations ('L.' → 'Lucius', etc.).

INSCRIPTION CONVENTIONS (these texts contain epigraphic markers):
- '[abc]' = letters [abc] are damaged but restored by editors. Treat as present.
- '[3]' or '[6]' etc. = a lacuna of approximately N missing characters. The name there is INCOMPLETE.
- '<a=b>' = letter b was actually inscribed in place of intended a. Use the intended letter.
- '/' = line break in the original. Ignore for parsing.
- '(...)' = editorial abbreviation expansion. Use the expansion.
- '?' = uncertain reading.

If a name overlaps a '[N]' lacuna or has unrestored fragments (single dangling letters like 'M' or 'Sa'),
set fragmentary=true. Restored brackets like '[Mar]cus' are fine — that's still Marcus, fragmentary=false.
{BASE_RULES}
"""

GENDER_VALUES = {'male', 'female', 'unknown', 'homo', 'vir', 'mulier'}

class Person(BaseModel):
    praenomen: Optional[str] = Field(None)
    nomen: Optional[str] = Field(None)
    cognomen: Optional[str] = Field(None)
    gender: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    raw_name: str
    fragmentary: bool = Field(False)

    def model_post_init(self, __context):
        for f in ('praenomen', 'nomen', 'cognomen', 'status', 'gender'):
            v = getattr(self, f)
            if isinstance(v, str) and v.strip().lower() == 'null':
                object.__setattr__(self, f, None)
        for f in ('praenomen', 'nomen', 'cognomen'):
            v = getattr(self, f)
            if v and v.lower().strip() in GENDER_VALUES:
                object.__setattr__(self, f, None)

class InscriptionResult(BaseModel):
    id: str
    persons: List[Person]

class BatchNEROutput(BaseModel):
    results: List[InscriptionResult]


def run_batch(client, system_prompt, batch_input):
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=f"Please process this batch of inscriptions: {json.dumps(batch_input, ensure_ascii=False)}",
        config={
            'system_instruction': system_prompt,
            'response_mime_type': 'application/json',
            'response_schema': BatchNEROutput,
            'thinking_config': {'thinking_budget': 0},
        },
    )
    return response.parsed.model_dump()


def name_signature(p):
    """Make a lowercase concatenation of name fields for matching."""
    parts = [p.get('praenomen'), p.get('nomen'), p.get('cognomen')]
    return ' '.join(s.lower().strip() for s in parts if s)


def words_overlap(pred_sig, gt_sig, threshold=0.5):
    if not pred_sig or not gt_sig:
        return False
    pw = pred_sig.split()
    gw = gt_sig.split()
    if not pw or not gw:
        return False
    short, long = (pw, gw) if len(pw) <= len(gw) else (gw, pw)
    matched = sum(1 for w in short if any(w[:6] == t[:6] for t in long))
    return matched / len(short) >= threshold


def evaluate(predictions, ground_truth):
    """Return tp, fp, fn for one record."""
    gt_sigs = []
    for p in ground_truth:
        if not isinstance(p, dict):
            continue
        parts = [p.get('praenomen'), p.get('nomen'), p.get('cognomen'), p.get('name')]
        sig = ' '.join(str(x).lower().strip() for x in parts if x and str(x).lower() != 'none')
        if sig:
            gt_sigs.append(sig)
    pred_sigs = [name_signature(p) for p in predictions if name_signature(p)]

    used_gt = set()
    tp = 0
    for ps in pred_sigs:
        for i, gs in enumerate(gt_sigs):
            if i in used_gt:
                continue
            if words_overlap(ps, gs):
                used_gt.add(i)
                tp += 1
                break
    fp = len(pred_sigs) - tp
    fn = len(gt_sigs) - tp
    return tp, fp, fn


def main():
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print('Error: GEMINI_API_KEY not found.')
        return
    client = genai.Client(api_key=api_key)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load eval set and EDCS data
    with open(EVAL_DIR / 'africa_proconsularis_eval.jsonl') as f:
        eval_recs = [json.loads(l) for l in f]
    with open(EDCS_PATH) as f:
        edcs = {r['EDCS-ID']: r for r in json.load(f) if r.get('EDCS-ID')}

    # Sample from records that have brackets in inscription (where the difference matters)
    candidates = []
    for ev in eval_recs:
        eid = ev['id']
        r = edcs.get(eid)
        if not r:
            continue
        ins = r.get('inscription') or ''
        cit = r.get('clean_text_interpretive_word') or ''
        if '[' in ins and cit and ins.strip():
            candidates.append({
                'id': eid,
                'inscription': ins,
                'clean_text': cit,
                'ground_truth': ev.get('ground_truth_people', []),
            })

    random.seed(RANDOM_SEED)
    sample = random.sample(candidates, min(SAMPLE_SIZE, len(candidates)))
    print(f'Sampled {len(sample)} bracketed records. Running both prompts...')

    batch_a = [{'id': r['id'], 'text': r['clean_text']} for r in sample]
    batch_b = [{'id': r['id'], 'text': r['inscription']} for r in sample]

    print('Running A (clean_text)...')
    out_a = run_batch(client, PROMPT_A, batch_a)
    time.sleep(2)
    print('Running B (inscription with brackets)...')
    out_b = run_batch(client, PROMPT_B, batch_b)

    with open(f'{OUTPUT_DIR}/run_a_clean.json', 'w') as f:
        json.dump(out_a, f, indent=2, ensure_ascii=False)
    with open(f'{OUTPUT_DIR}/run_b_inscription.json', 'w') as f:
        json.dump(out_b, f, indent=2, ensure_ascii=False)

    # Build comparison
    by_id = {r['id']: r for r in sample}
    a_by_id = {r['id']: r['persons'] for r in out_a['results']}
    b_by_id = {r['id']: r['persons'] for r in out_b['results']}

    a_tot_p = a_tot_frag = a_tp = a_fp = a_fn = 0
    b_tot_p = b_tot_frag = b_tp = b_fp = b_fn = 0
    diffs = []

    for sid, rec in by_id.items():
        ap = a_by_id.get(sid, [])
        bp = b_by_id.get(sid, [])
        a_tot_p += len(ap)
        b_tot_p += len(bp)
        a_tot_frag += sum(1 for p in ap if p.get('fragmentary'))
        b_tot_frag += sum(1 for p in bp if p.get('fragmentary'))

        tp_a, fp_a, fn_a = evaluate(ap, rec['ground_truth'])
        tp_b, fp_b, fn_b = evaluate(bp, rec['ground_truth'])
        a_tp += tp_a; a_fp += fp_a; a_fn += fn_a
        b_tp += tp_b; b_fp += fp_b; b_fn += fn_b

        diffs.append({
            'id': sid,
            'gt_count': len([g for g in rec['ground_truth'] if isinstance(g, dict)]),
            'a_count': len(ap), 'b_count': len(bp),
            'a_frag': sum(1 for p in ap if p.get('fragmentary')),
            'b_frag': sum(1 for p in bp if p.get('fragmentary')),
            'a_tp': tp_a, 'a_fp': fp_a, 'a_fn': fn_a,
            'b_tp': tp_b, 'b_fp': fp_b, 'b_fn': fn_b,
        })

    def pr_f1(tp, fp, fn):
        p = tp / (tp + fp) if (tp + fp) else 0
        r = tp / (tp + fn) if (tp + fn) else 0
        f = 2 * p * r / (p + r) if (p + r) else 0
        return p, r, f

    print()
    print('=' * 70)
    print(f'Sample size: {len(sample)} records (all with brackets in raw inscription)')
    print('=' * 70)
    print(f'                              A (clean_text)    B (inscription)')
    print(f'  Total persons extracted:    {a_tot_p:>13}    {b_tot_p:>13}')
    print(f'  Fragmentary flagged:        {a_tot_frag:>13}    {b_tot_frag:>13}')
    print(f'  TP:                          {a_tp:>13}    {b_tp:>13}')
    print(f'  FP:                          {a_fp:>13}    {b_fp:>13}')
    print(f'  FN:                          {a_fn:>13}    {b_fn:>13}')
    pa, ra, fa = pr_f1(a_tp, a_fp, a_fn)
    pb, rb, fb = pr_f1(b_tp, b_fp, b_fn)
    print(f'  Precision:                   {pa:>13.3f}    {pb:>13.3f}')
    print(f'  Recall:                      {ra:>13.3f}    {rb:>13.3f}')
    print(f'  F1:                          {fa:>13.3f}    {fb:>13.3f}')
    print()

    # Show per-record diffs where they differ
    differing = [d for d in diffs if d['a_count'] != d['b_count'] or d['a_frag'] != d['b_frag']]
    print(f'Records where A and B differed in count or frag flag: {len(differing)}/{len(diffs)}')
    print()
    print(f"{'EDCS-ID':<22}{'GT':>4}{'A#':>4}{'B#':>4}{'Afrag':>6}{'Bfrag':>6}{'Atp':>4}{'Btp':>4}{'Afp':>4}{'Bfp':>4}")
    for d in differing[:20]:
        print(f"{d['id']:<22}{d['gt_count']:>4}{d['a_count']:>4}{d['b_count']:>4}{d['a_frag']:>6}{d['b_frag']:>6}{d['a_tp']:>4}{d['b_tp']:>4}{d['a_fp']:>4}{d['b_fp']:>4}")

    with open(f'{OUTPUT_DIR}/comparison.json', 'w') as f:
        json.dump({
            'summary': {
                'n': len(sample),
                'a_total_persons': a_tot_p, 'b_total_persons': b_tot_p,
                'a_frag': a_tot_frag, 'b_frag': b_tot_frag,
                'a_tp': a_tp, 'a_fp': a_fp, 'a_fn': a_fn,
                'b_tp': b_tp, 'b_fp': b_fp, 'b_fn': b_fn,
                'a_p': pa, 'a_r': ra, 'a_f1': fa,
                'b_p': pb, 'b_r': rb, 'b_f1': fb,
            },
            'per_record': diffs,
        }, f, indent=2)


if __name__ == '__main__':
    main()
