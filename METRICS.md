# Canonical Per-Province Evaluation Metrics

**Generated:** 2026-06-11 · **Code state:** commit `2b65d4f` + Apulia/Aquitanica reruns (branch `feature/webapp-rewrite`)

All numbers in this table were produced by the **current** evaluation harness
(`scripts/05b_eval_from_corpus.py`), re-scoring full-corpus NER predictions against
LIRE v3.0 ground truth. Apulia et Calabria and Aquitanica were re-extracted fresh
(~2 min, ~$0.70 total) to produce missing prediction files. This table supersedes
the per-week F1 numbers scattered through `PROGRESS.md`, some of which were computed
under an earlier harness that over-counted matches.

**Harness properties** (the "honest" eval, post Week-6 fixes):
- One-to-one greedy bipartite matching (a prediction can match at most one GT person)
- Name-length guard (`Victor` does not match `Victorinus`)
- Strict damage accounting: GT names are only excluded as unrecoverable when
  lacuna-dominated; damage-filtered inscriptions counted separately (`fn_filtered`)
- Predictions scored as the production deliverable: praenomen-whitelist rotation and
  nomen case fix applied before scoring
- Non-person FPs (deity / imperial / place / bare epithet) excluded from adjusted
  precision; remaining FPs are "candidate discoveries"

**Regenerate:**
```bash
for p in <slug>; do python scripts/05b_eval_from_corpus.py --province $p; done
```

## Results (22 provinces with LIRE ground truth)

| Province | F1 (adj) | Recall (adj) | Precision (adj) | Eval records scored | TP | Candidate discoveries |
|---|---|---|---|---|---|---|
| Apulia et Calabria | **0.93** | 0.91 | 0.95 | 116 / 128 | 200 | 10 |
| Bruttium et Lucania | **0.91** | 0.89 | 0.93 | 37 / 42 | 57 | 4 |
| Roma | **0.87** | 0.86 | 0.88 | 310 / 500 | 482 | 63 |
| Mauretania Caesariensis | **0.85** | 0.82 | 0.89 | 109 / 129 | 183 | 22 |
| Numidia | **0.84** | 0.83 | 0.85 | 469 / 500 | 459 | 80 |
| Baetica | **0.82** | 0.79 | 0.85 | 434 / 500 | 500 | 88 |
| Moesia superior | **0.79** | 0.76 | 0.82 | 433 / 500 | 716 | 152 |
| Noricum | **0.79** | 0.75 | 0.83 | 422 / 500 | 938 | 193 |
| Picenum | **0.79** | 0.73 | 0.86 | 16 / 24 | 19 | 3 |
| Britannia | **0.78** | 0.71 | 0.85 | 399 / 500 | 369 | 64 |
| Dacia | **0.78** | 0.76 | 0.79 | 395 / 500 | 462 | 122 |
| Etruria | **0.78** | 0.75 | 0.81 | 262 / 366 | 378 | 88 |
| Germania superior | **0.77** | 0.78 | 0.76 | 406 / 500 | 592 | 185 |
| Venetia et Histria | **0.77** | 0.74 | 0.81 | 352 / 423 | 433 | 103 |
| Africa proconsularis | **0.76** | 0.75 | 0.77 | 335 / 477 | 414 | 127 |
| Hispania citerior | **0.76** | 0.74 | 0.78 | 412 / 500 | 507 | 140 |
| Pannonia inferior | **0.76** | 0.73 | 0.80 | 399 / 500 | 515 | 130 |
| Pannonia superior | **0.76** | 0.74 | 0.78 | 399 / 500 | 569 | 156 |
| Dalmatia | **0.75** | 0.75 | 0.74 | 405 / 500 | 530 | 183 |
| Moesia inferior | **0.75** | 0.74 | 0.77 | 382 / 500 | 632 | 192 |
| Latium et Campania | **0.68** | 0.69 | 0.68 | 385 / 500 | 581 | 275 |
| Lusitania | **0.65** | 0.64 | 0.66 | 134 / 145 | 169 | 86 |
| Gallia Narbonensis | **0.62** | 0.64 | 0.61 | 27 / 33 | 34 | 22 |

**Range: F1 0.62–0.93 across 23 provinces** (median 0.78).

"Eval records scored" = records surviving the >30%-lacuna damage filter / total eval
records. Provinces with small scored pools (Picenum n=16, Gallia Narbonensis n=27,
Bruttium n=37, Apulia n=116 from a 128-record LIRE pool) have wide uncertainty on
their point estimates.

## Notes and caveats

- **Gallia Narbonensis (0.62, n=27)** is LIRE-scored. An EDH-based eval (Week 10,
  `05_evaluate_ner.py --source edh`) gave F1 0.70 on 2× the validation density; EDH is
  the more representative number for this province but is not regenerated in this table.
- **Lusitania (0.65)**: known eval artifacts — LIRE counts filiation fathers as separate
  GT persons where the model correctly emits a `pater` record, and indigenous name
  morphology defeats the prefix match. See PROGRESS.md Week 7.
- **Latium et Campania (0.68)**: lowest large-province score; high candidate-discovery
  count (275) suggests either genuine LIRE coverage gaps or an FP pattern worth a triage
  pass before quoting this province's numbers.

## Provinces without scores

| Province | Reason |
|---|---|
| Aegyptus, Creta et Cyrenaica, Mauretania Tingitana, Sicilia | Eval set files exist but are **empty** — LIRE v3.0 has no usable `people` ground truth for these provinces |
| Aquitanica | NER predictions exist (15,229 records processed); LIRE v3.0 only has ~19 parseable GT records for this province — too sparse to produce a meaningful score |
| Samnium, Umbria, Aemilia, Liguria, Transpadana | `has_eval=False` — no eval sets built |
| Belgica, Germania inferior, Sardinia, Corsica | In config / database but no eval artifacts on disk |
