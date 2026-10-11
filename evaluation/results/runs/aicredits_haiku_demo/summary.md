# Phase 11 evaluation summary

Generated 2026-10-11 07:55 UTC by `python -m evaluation.make_summary`. Every number below is read from a file in `evaluation/results/runs/aicredits_haiku_demo/`.

## Headline metrics vs targets

| Component | Metric | Value | Target | Status |
|---|---|---|---|---|
| Retrieval | Filter compliance (hybrid_rerank) | 1.000 | >= 1.0 | PASS |
| Retrieval | Hit@5 (hybrid_rerank) | 1.000 | >= 0.90 | PASS |
| Retrieval | nDCG@10 hybrid vs best single mode | 0.934 | >= 0.913 | PASS |
| Retrieval | p95 latency, hybrid_rerank (ms) | 151.020 | <= 300 | PASS |
| KB retrieval | Hit@3 expected category | 0.909 | >= 0.90 | PASS |
| Prioritization | Scenario exact agreement | 1.000 | >= 0.80 | PASS |
| Prioritization | Scenario within one level | 1.000 | >= 1.0 | PASS |
| Classifier (LLM, reasoning off) | Primary accuracy | 0.955 | >= 0.80 | PASS |
| Classifier (LLM, reasoning off) | Macro-F1 | 0.964 | >= 0.75 | PASS |
| Classifier (LLM, reasoning off) | Filter exact match | 1.000 | >= 0.85 | PASS |
| Classifier (LLM, reasoning off) | Out-of-scope detection (n=1) | 1.000 | >= 0.90 | PASS |
| Guardrails | Block rate | 1.000 | >= 0.90 | PASS |
| Guardrails | False-positive rate | 0.000 | <= 0.05 | PASS |
| Fault-risk model | ROC-AUC (holdout) | 0.874 | >= 0.85 | PASS |
| Performance model | R2 (holdout) | 0.328 | >= 0.25 | PASS |
| Feedback loop | nDCG@10 delta, voted queries | 0.006 | > 0 | PASS |
| Feedback loop | Control queries regressed | 0.000 | 0 | PASS |
| End to end (C) | /troubleshoot median latency (s) | 34.800 | <= 60 (internal) | PASS |
| End to end (C) | JSON failures after repair, per agent call | 0.000 | <= 0.02 | PASS |
| End to end (C) | Runs ending degraded (any cause) | 0.000 | reported | info |
| End to end | /search p95 latency (s, retrieval core) | 0.151 | <= 1.0 | PASS |
| DeepEval, system C (mean score) | actionability_geval | 0.991 | >= 0.7 | PASS |
| DeepEval, system C (mean score) | answer_relevancy | 0.873 | >= 0.7 | PASS |
| DeepEval, system C (mean score) | contextual_precision | 0.799 | >= 0.7 | PASS |
| DeepEval, system C (mean score) | contextual_recall | 0.697 | >= 0.7 | FAIL |
| DeepEval, system C (mean score) | contextual_relevancy | 0.780 | >= 0.5 | PASS |
| DeepEval, system C (mean score) | diagnosis_validity_geval | 0.891 | >= 0.7 | PASS |
| DeepEval, system C (mean score) | faithfulness | 0.993 | >= 0.7 | PASS |
| Runtime judge | Seeded-error detection rate | 1.000 | >= 0.80 | PASS |

Totals: 27 PASS, 1 FAIL, 0 not run, 1 informational.

## End-to-end runs (system C, LLM cache off) vs the frozen Phase 8 baseline

| Metric | Phase 11 (n=11) | Phase 8 baseline (n=8) |
|---|---|---|
| Latency median / p95 / max (s) | 34.8 / 78.6 / 78.8 | 103.2 / 162.4 / 177.1 |
| LLM calls per run, mean / max | 5.0 / 8 | 6.0 / 8 |
| Tokens per run, mean / max | 31,823 / 59,019 | 26,734 / 41,645 |
| Repair calls (total) | 2 | 4 |
| Fallback events (any node, incl. recovered) | 0 | 0 |
| Runs ending degraded | 0 (JSON 0, call budget 0) | 0 |
| Status | {'ok': 11} | {'ok': 8} |
| Verdicts | {'pass': 9, 'fail': 2} | {'pass': 8} |
| Revision rate | 0.27 | 0.5 |

System A (basic RAG, 1 call): median 9.5 s, p95 11.5 s, 4,845 tokens per run, 0 repair calls, status {'ok': 11}.
Low-confidence (validator fail) runs: ['G18', 'G19'].

## DeepEval (judge: openai/gpt-oss-120b) mean score / pass rate per system

| Metric | A | B | C |
|---|---|---|---|
| actionability_geval | 0.66 / 0.46 | 1.00 / 1.00 | 0.99 / 1.00 |
| answer_relevancy | 0.86 / 0.82 | 0.87 / 0.67 | 0.87 / 0.80 |
| contextual_precision | 0.67 / 0.55 | 0.97 / 1.00 | 0.80 / 0.73 |
| contextual_recall | 0.67 / 0.18 | 0.67 / 0.00 | 0.70 / 0.09 |
| contextual_relevancy | 0.78 / 1.00 | 0.82 / 1.00 | 0.78 / 1.00 |
| diagnosis_validity_geval | 0.89 / 1.00 | 0.90 / 1.00 | 0.89 / 1.00 |
| faithfulness | 0.96 / 1.00 | 0.98 / 1.00 | 0.99 / 1.00 |

Metric errors (judge failures, recorded not hidden): {'A': 0, 'B': 0, 'C': 2}. B is evaluated only where C revised (elsewhere B is identical to C).

## Runtime judge meta-evaluation

Seeded errors detected (verdict fail): 1.0 on 12 seeded diagnoses (bases G01, G03); detected and matched to the seeded problem: 1.0. Control false alarms: 0 of 2.

| Seeded error | Detected | Matched |
|---|---|---|
| contradicting_kpi_number | 1.00 | 1.00 |
| invented_case_id | 1.00 | 1.00 |
| irrelevant_action | 1.00 | 1.00 |
| overclaimed_causality | 1.00 | 1.00 |
| recommendation_without_kb_citation | 1.00 | 1.00 |
| root_cause_contradicts_anomalies | 1.00 | 1.00 |

Spearman(runtime groundedness, DeepEval faithfulness C) = 0.469 (n=10).
Revision effectiveness: DeepEval faithfulness before (B) 0.977 vs after (C) 0.993 on 3 revised runs.
