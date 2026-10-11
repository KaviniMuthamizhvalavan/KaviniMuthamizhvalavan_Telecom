# Phase 11 evaluation summary

Generated 2026-10-09 05:48 UTC by `python -m evaluation.make_summary`. Every number below is read from a file in `evaluation/results/final/`.

## Headline metrics vs targets

| Component | Metric | Value | Target | Status |
|---|---|---|---|---|
| Retrieval | Filter compliance (hybrid_rerank) | 1.000 | >= 1.0 | PASS |
| Retrieval | Hit@5 (hybrid_rerank) | 1.000 | >= 0.90 | PASS |
| Retrieval | nDCG@10 hybrid vs best single mode | 0.934 | >= 0.913 | PASS |
| Retrieval | p95 latency, hybrid_rerank (ms) | 135.835 | <= 300 | PASS |
| KB retrieval | Hit@3 expected category | 0.909 | >= 0.90 | PASS |
| Prioritization | Scenario exact agreement | 1.000 | >= 0.80 | PASS |
| Prioritization | Scenario within one level | 1.000 | >= 1.0 | PASS |
| Classifier (LLM, reasoning off) | Primary accuracy | 0.909 | >= 0.80 | PASS |
| Classifier (LLM, reasoning off) | Macro-F1 | 0.921 | >= 0.75 | PASS |
| Classifier (LLM, reasoning off) | Filter exact match | 0.955 | >= 0.85 | PASS |
| Classifier (LLM, reasoning off) | Out-of-scope detection (n=1) | 1.000 | >= 0.90 | PASS |
| Guardrails | Block rate | 1.000 | >= 0.90 | PASS |
| Guardrails | False-positive rate | 0.000 | <= 0.05 | PASS |
| Fault-risk model | ROC-AUC (holdout) | 0.874 | >= 0.85 | PASS |
| Performance model | R2 (holdout) | 0.328 | >= 0.25 | PASS |
| Feedback loop | nDCG@10 delta, voted queries | 0.006 | > 0 | PASS |
| Feedback loop | Control queries regressed | 0.000 | 0 | PASS |
| End to end (C) | /troubleshoot median latency (s) | 76.300 | <= 60 (internal) | FAIL |
| End to end (C) | JSON failures after repair, per agent call | 0.018 | <= 0.02 | PASS |
| End to end (C) | Runs ending degraded (any cause) | 0.182 | reported | info |
| End to end | /search p95 latency (s, retrieval core) | 0.136 | <= 1.0 | PASS |
| DeepEval, system C (mean score) | actionability_geval | 0.973 | >= 0.7 | PASS |
| DeepEval, system C (mean score) | answer_relevancy | 0.813 | >= 0.7 | PASS |
| DeepEval, system C (mean score) | contextual_precision | 0.733 | >= 0.7 | PASS |
| DeepEval, system C (mean score) | contextual_recall | 0.752 | >= 0.7 | PASS |
| DeepEval, system C (mean score) | contextual_relevancy | 0.762 | >= 0.5 | PASS |
| DeepEval, system C (mean score) | diagnosis_validity_geval | 0.923 | >= 0.7 | PASS |
| DeepEval, system C (mean score) | faithfulness | 0.981 | >= 0.7 | PASS |
| Runtime judge | Seeded-error detection rate | 0.750 | >= 0.80 | FAIL |

Totals: 26 PASS, 2 FAIL, 0 not run, 1 informational.

## End-to-end runs (system C, LLM cache off) vs the frozen Phase 8 baseline

| Metric | Phase 11 (n=11) | Phase 8 baseline (n=8) |
|---|---|---|
| Latency median / p95 / max (s) | 76.3 / 166.2 / 169.0 | 103.2 / 162.4 / 177.1 |
| LLM calls per run, mean / max | 5.4 / 8 | 6.0 / 8 |
| Tokens per run, mean / max | 23,127 / 39,113 | 26,734 / 41,645 |
| Repair calls (total) | 4 | 4 |
| Fallback events (any node, incl. recovered) | 2 | 0 |
| Runs ending degraded | 2 (JSON 1, call budget 1) | 0 |
| Status | {'ok': 9, 'degraded': 2} | {'ok': 8} |
| Verdicts | {'pass': 10, 'unvalidated': 1} | {'pass': 8} |
| Revision rate | 0.36 | 0.5 |

System A (basic RAG, 1 call): median 18.4 s, p95 46.4 s, 4,378 tokens per run, 1 repair calls, status {'ok': 11}.
Low-confidence (validator fail) runs: none.

## DeepEval (judge: openai/gpt-oss-20b) mean score / pass rate per system

| Metric | A | B | C |
|---|---|---|---|
| actionability_geval | 0.60 / 0.46 | 1.00 / 1.00 | 0.97 / 1.00 |
| answer_relevancy | 0.90 / 0.82 | 0.64 / 0.67 | 0.81 / 0.73 |
| contextual_precision | 0.87 / 0.82 | 0.78 / 0.67 | 0.73 / 0.64 |
| contextual_recall | 0.66 / 0.09 | 0.78 / 0.33 | 0.75 / 0.36 |
| contextual_relevancy | 0.75 / 1.00 | 0.70 / 1.00 | 0.76 / 1.00 |
| diagnosis_validity_geval | 0.91 / 0.91 | 0.90 / 1.00 | 0.92 / 1.00 |
| faithfulness | 0.98 / 1.00 | 1.00 / 1.00 | 0.98 / 1.00 |

Metric errors (judge failures, recorded not hidden): {'A': 0, 'B': 0, 'C': 0}. B is evaluated only where C revised (elsewhere B is identical to C).

## Runtime judge meta-evaluation

Seeded errors detected (verdict fail): 0.75 on 12 seeded diagnoses (bases G01, G03); detected and matched to the seeded problem: 0.75. Control false alarms: 0 of 2.

| Seeded error | Detected | Matched |
|---|---|---|
| contradicting_kpi_number | 0.00 | 1.00 |
| invented_case_id | 0.50 | 1.00 |
| irrelevant_action | 1.00 | 1.00 |
| overclaimed_causality | 1.00 | 1.00 |
| recommendation_without_kb_citation | 1.00 | 1.00 |
| root_cause_contradicts_anomalies | 1.00 | 1.00 |

Spearman(runtime groundedness, DeepEval faithfulness C) = 0.248 (n=10).
Revision effectiveness: DeepEval faithfulness before (B) 1.0 vs after (C) 1.0 on 3 revised runs.
