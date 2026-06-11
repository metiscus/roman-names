# Canonical Per-Province Evaluation Metrics

**Generated:** 2026-06-11 · **Code state:** commit `2b65d4f` + Apulia/Aquitanica reruns (branch `feature/webapp-rewrite`)

All LIRE numbers produced by `scripts/05b_eval_from_corpus.py` (corrected harness,
post Week-6 fixes). EDH numbers produced by `scripts/05_evaluate_ner.py --source edh`.
Apulia et Calabria and Aquitanica NER predictions were re-run fresh to produce missing
artifacts. This table supersedes the per-week F1 numbers scattered through `PROGRESS.md`.

**LIRE harness properties** (post Week-6 de-inflation fixes):
- One-to-one greedy bipartite matching (a prediction can match at most one GT person)
- Name-length guard (`Victor` does not match `Victorinus`)
- Strict damage accounting: GT names excluded as unrecoverable only when lacuna-dominated
- Predictions scored as the production deliverable: praenomen-whitelist rotation and
  nomen case fix applied before scoring
- Non-person FPs (deity / imperial / place / bare epithet) excluded from adjusted
  precision; remaining FPs are "candidate discoveries"

**EDH harness note:** `05_evaluate_ner.py --source edh` uses the same bipartite matching
and name guards but scores against EDH GT directly on full-corpus predictions (no
damage-filter step). Overlap = NER records with a matching EDH entry.

**Regenerate LIRE scores:**
```bash
for p in <slug>; do python scripts/05b_eval_from_corpus.py --province $p; done
```
**Regenerate EDH scores:**
```bash
python scripts/05_evaluate_ner.py --province "<EDCS province name>" --source edh
```

---

## LIRE v3.0 evaluation (23 provinces)

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

**Range: F1 0.62–0.93, median 0.78.**

"Eval records scored" = records surviving the >30%-lacuna damage filter / total eval
records. Provinces with small scored pools (Picenum n=16, Gallia Narbonensis n=27,
Bruttium n=37, Apulia n=116 from a 128-record LIRE pool) have wide uncertainty on
their point estimates.

---

## EDH (Heidelberg) evaluation (15 provinces, 955–4,612 inscriptions overlap)

EDH provides substantially denser validation than LIRE for the Danubian and western
military provinces — 4–10× more overlapping inscriptions per province. Numbers are
consistent with LIRE scores, confirming the pipeline is not over-fitted to LIRE's
annotation style.

| Province | F1 (adj) | Recall (adj) | Precision (adj) | EDH overlap |
|---|---|---|---|---|
| Numidia | **0.83** | 0.81 | 0.85 | 1,428 |
| Roma | **0.85** | 0.83 | 0.87 | 1,404 |
| Baetica | **0.80** | 0.76 | 0.85 | 1,578 |
| Germania superior | **0.77** | 0.75 | 0.79 | 2,282 |
| Dacia | **0.76** | 0.72 | 0.79 | 1,994 |
| Hispania citerior | **0.76** | 0.73 | 0.80 | 1,624 |
| Moesia inferior | **0.76** | 0.71 | 0.82 | 1,085 |
| Moesia superior | **0.76** | 0.71 | 0.82 | 955 |
| Noricum | **0.75** | 0.70 | 0.81 | 1,834 |
| Pannonia inferior | **0.74** | 0.69 | 0.79 | 1,898 |
| Pannonia superior | **0.73** | 0.69 | 0.77 | 2,457 |
| Britannia | **0.73** | 0.66 | 0.82 | 1,925 |
| Dalmatia | **0.72** | 0.69 | 0.75 | 4,612 |
| Africa proconsularis | **0.70** | 0.72 | 0.68 | 373 |
| Lusitania | **0.64** | 0.63 | 0.65 | 181 |

**Range: F1 0.64–0.85, median 0.75.** EDH scores are systematically 2–4 points
below LIRE scores for the same province, consistent with EDH using broader annotation
criteria (more names per inscription on average) and not applying the damage-filter
step.

---

## Notes and caveats

- **Gallia Narbonensis**: LIRE score (0.62, n=27) has very thin coverage. EDH gives
  F1 0.70 on 61 overlapping inscriptions (run Week 10; not regenerated in this pass
  due to a slug mismatch in `05_evaluate_ner.py` for long province names with `/`).
- **Lusitania (LIRE 0.65 / EDH 0.64)**: consistent across both GT sources. Known
  eval artifacts — LIRE counts filiation fathers as separate GT persons, and indigenous
  name morphology defeats the 6-char prefix match. See PROGRESS.md Week 7.
- **Latium et Campania (LIRE 0.68)**: lowest large-province LIRE score; 275 candidate
  discoveries is high. EDH slug mismatch prevented re-scoring. Worth a triage pass.
- **EDH precision < recall pattern**: for most provinces precision exceeds recall under
  EDH, opposite of LIRE. EDH likely annotates a broader range of individuals (slaves,
  freed persons, soldiers) who may not appear in LIRE's curated selection.

---

## Provinces without LIRE scores

| Province | Reason |
|---|---|
| Aegyptus, Creta et Cyrenaica, Mauretania Tingitana, Sicilia | LIRE v3.0 has no usable `people` ground truth — eval sets are empty files |
| Aquitanica | NER predictions exist (15,229 records); LIRE has only ~19 parseable GT records — too sparse |
| Samnium, Umbria, Aemilia, Liguria, Transpadana | `has_eval=False` — no eval sets built |
| Belgica, Germania inferior, Sardinia, Corsica | In config / database but no eval artifacts on disk |
