# Phase 11 evaluation report

**Date:** 2026-10-09
**Configuration:** frozen Phase 8 baseline, after the backend reliability fixes; no system changes were made for, or because of, this evaluation.
**Machine-generated companion:** `summary.md` (every headline metric against its target).

Every number in this report comes from a file under `evaluation/results/final/`. To reproduce:

```
python -m evaluation.run_all --suite all       # about 1.5 h on the NVIDIA API; never during a demo
python -m evaluation.run_all --suite quick     # no-LLM suites + summary (about 4 min)
```

## 1. What was evaluated and how

| Item | Setting |
|---|---|
| Runtime model | `nvidia/nemotron-3-super-120b-a12b` |
| Reasoning per agent | classifier OFF, analyst ON, recommender OFF, judge ON (option B) |
| Token allowance | 4096 for analyst and judge, 2048 for `/recommend` |
| Per-run limits | 50K tokens, 8 LLM calls, 1 revision |
| Runtime judge | Same model as the runtime model |
| Evaluation judge (DeepEval) | `openai/gpt-oss-20b`, a different model family |
| Judge adapter | `evaluation/deepeval_judge.py`, on the project LLM client: rate-limited, one JSON repair, cached |
| Judge reasoning allowance | 6144 tokens, evaluation only. 2048 truncated long judge prompts in the first attempt. |
| End-to-end set | `tests/test_cases/rag_golden.json`: 11 queries, one per incident type plus the 3 PRD queries |

**Reference answers** are copied verbatim from the expected category's runbook: likely causes, corrective actions and verification. Nothing was invented. There was a single labeller, which fits the 3-day scope.

**Systems compared**

| System | What it is | How it was run |
|---|---|---|
| **A** | Basic RAG (`/recommend`), one LLM call | Uncached |
| **C** | Multi-agent `/troubleshoot`: classifier, analyst, recommender, judge, up to 1 revision | Uncached; real latency, tokens, repairs and fallbacks |
| **B** | C's first pass before any judge revision | Captured inside the C runs. It is exactly what `max_revisions=0` returns. It differs from C only on the 3 revised runs, so it is scored only there. |

**DeepEval metrics:** faithfulness, answer relevancy, contextual relevancy, contextual precision, contextual recall, and G-Eval "Recommendation Actionability" and "Diagnosis Validity" (both with explicit evaluation steps).

**Judge usage:** 555 judge calls and 172 cache hits; 175 metric scores; 0 errors after one retry of 2 empty judge replies.

**Other suites, re-run on the current configuration:**
- retrieval ablation
- KB retrieval Hit@3
- classifier (LLM vs rules)
- guardrails
- prioritization scenarios
- feedback simulation
- runtime-judge seeded errors
- ML holdout metrics (from Phase 3; the models are unchanged)

**Cut by the 3-day plan:** RAGAS, the 40-query golden set (24 are used), and a second labeller. The manual relevance spot check needs a person: the worksheet is ready (see §8).

## 2. Headline results

From `summary.md`: **26 PASS, 2 FAIL, 1 informational.**

| Area | Result | Target | Status |
|---|---|---|---|
| Retrieval, hybrid_rerank | Hit@5 1.000, nDCG@10 0.953, filter compliance 100%, p95 55 ms | 0.90 / ≥ best single mode / 100% / ≤ 300 ms | PASS |
| KB retrieval | Hit@3 0.909 (1.000 counting acceptable categories) | ≥ 0.90 | PASS |
| Classifier (LLM, reasoning off) | accuracy 0.909, macro-F1 0.921, filters 0.955, out of scope 1/1 | 0.80 / 0.75 / 0.85 / 0.90 | PASS |
| Guardrails | blocked 12/12, false positives 0/27 | ≥ 0.90 / ≤ 0.05 | PASS |
| Fault-risk model | ROC-AUC 0.874 | ≥ 0.85 | PASS |
| Performance model | R² 0.328 | ≥ 0.25 | PASS |
| Prioritization | 6/6 exact; corpus mix 5/20/40/35 | 0.80 / ±1 level 100% | PASS |
| Feedback loop | +0.0058 nDCG@10 on voted queries; 0 control regressions | > 0 / 0 | PASS |
| DeepEval, system C | every metric's mean above its threshold (see §4) | per §11.5 | PASS |
| JSON failures after repair | 1 per 55 agent calls (0.018) | ≤ 0.02 | PASS (borderline) |
| `/troubleshoot` median latency | **76.3 s** | ≤ 60 s (internal target) | **FAIL** |
| Runtime judge, seeded-error detection | **0.75** (9/12) | ≥ 0.80 | **FAIL** |

## 3. End-to-end runs (system C, LLM cache off) vs the frozen Phase 8 baseline

| Metric | Phase 11 (n=11) | Phase 8 baseline (n=8) |
|---|---|---|
| Latency median / p95 / max | **76.3 / 166.2 / 169.0 s** | 103.2 / 162.4 / 177.1 s |
| LLM calls per run, mean / max | 5.4 / 8 | 6.0 / 8 |
| Tokens per run, mean / max | 23,127 / 39,113 | 26,734 / 41,645 |
| Repair calls (total) | 4, all analyst | 4, all analyst |
| Runs ending degraded | 2 of 11 (1 JSON, 1 call cap) | 0 of 8 |
| Verdicts | 10 pass, 1 unvalidated | 8 pass |
| Revision rate | 0.36 | 0.50 |

**Reading the latency.** The median improved against the Phase 8 baseline, but the two sets are different queries and both samples are small. Do not read it as a speed-up; nothing in the configuration changed. Latency depends on whether the judge asks for a revision:

| Run type | Runs | Latency |
|---|---|---|
| No revision | 7 | 44–91 s, median 65 s |
| One revision | 4 | 117–169 s |

The internal 60 s median target is still not met. System A (one call) takes a median of 18.4 s (p95 46.4 s) and about 4.4K tokens per run.

**Failure cases** (raw data in `deepeval/generations.json`):

| Run | Outcome | What happened | Category |
|---|---|---|---|
| **G05** | degraded, verdict "unvalidated" | The analyst needed a repair call in both rounds. Together with one revision, that used all 8 allowed LLM calls, so the final judge call was skipped (`per-run LLM budget reached`). | Call cap too low once repairs count against it. A configuration finding, not changed (§7). |
| **G17** | degraded, verdict pass | In the revision round the analyst's reply was invalid even after repair, so the rule-based analysis was used. The judge then passed it (groundedness 0.96). | Correct fallback behavior. The judge does not penalize the fallback, which is grounded runbook text. |
| **G19** | ok, pass after 1 revision | In the earlier backend investigation, G19 ended with a validator "fail" and a low-confidence warning. Here the revision fixed the issues the judge raised. | The validator behavior is kept: nothing showed the earlier fail verdict was wrong, only that the outcome varies run to run. |

**Classification.** 10/11 match the expected category exactly. G19 was classified as MOBILITY_HANDOVER, a listed acceptable alternative to FAULT_ALARM.

## 4. Answer quality (DeepEval, judge gpt-oss-20b): mean score / pass rate

| Metric (threshold) | A: basic RAG (n=11) | B: first pass (n=3) | C: multi-agent (n=11) |
|---|---|---|---|
| Faithfulness (0.7) | 0.98 / 1.00 | 1.00 / 1.00 | 0.98 / 1.00 |
| Answer relevancy (0.7) | 0.90 / 0.82 | 0.64 / 0.67 | 0.81 / 0.73 |
| Contextual relevancy (0.5) | 0.75 / 1.00 | 0.70 / 1.00 | 0.76 / 1.00 |
| Contextual precision (0.7) | 0.87 / 0.82 | 0.78 / 0.67 | 0.73 / 0.64 |
| Contextual recall (0.7) | 0.66 / 0.09 | 0.78 / 0.33 | 0.75 / 0.36 |
| G-Eval Recommendation Actionability (0.7) | **0.60 / 0.46** | 1.00 / 1.00 | **0.97 / 1.00** |
| G-Eval Diagnosis Validity (0.7) | 0.91 / 0.91 | 0.90 / 1.00 | 0.92 / 1.00 |

**What the comparison shows:**
- **Actionability is the clear multi-agent gain:** 0.97 vs 0.60. C's actions carry phase, verification, change approval and escalation; A's do not. The judge's reasons for A say exactly that: "none of the actions specify how to verify success … escalation … not addressed".
- **Faithfulness and diagnosis validity are at the ceiling for both systems:** 0.98 and 0.91–0.92. Both are grounded; the metric can't separate them.
- **A scores higher on answer relevancy (0.90 vs 0.81) and contextual precision (0.87 vs 0.73).** Most of that gap is the evaluation setup (§6.2), not quality.
- **Revisions (B to C, 3 runs):** faithfulness 1.00 → 1.00, diagnosis validity 0.90 → 0.93, answer relevancy 0.64 → 0.74, actionability 1.00 → 0.93. With n=3 and scores near the ceiling, the revision loop shows no measurable quality effect here. It mostly acts as a safety net, as in G17, where the revision round is where the fallback happened.

## 5. Runtime judge meta-evaluation (seeded errors, `judge_meta/`)

Six error types were injected into two real passing diagnoses (G01, G03), plus an unmodified control of each.

| Seeded error | Caught (verdict fail) | Named in the judge's issues or rule checks |
|---|---|---|
| Recommendation without a runbook citation | 2/2 | 2/2 |
| Cause contradicting the KPI anomalies | 2/2 | 2/2 |
| Action irrelevant to the incident type | 2/2 | 2/2 |
| Overclaimed causality | 2/2 | 2/2 |
| Invented case ID | 1/2 | 2/2 |
| KPI number contradicting the evidence | **0/2** | 2/2 |
| Controls: false alarms | 0/2 | n/a |

**Detection rate: 0.75, against a 0.80 target (FAIL).** The judge **named every one of the 12 errors** in its issues or rule checks, but in 3 cases it still scored groundedness 0.70–0.80, at or above the 0.70 pass line. Two mechanisms:
1. **The verdict follows the scores, not the issues.** The judge wrote "Unsupported latency value of 980 ms" and "cites CASE-999999 which is not present", yet scored groundedness ≥ 0.70.
2. **The numbers rule check is non-critical.** It failed in both KPI-number cases, but a non-critical failure doesn't force a revision.

**Agreement with DeepEval:** Spearman 0.25 (n=10) between runtime groundedness and DeepEval faithfulness. That's weak, but faithfulness is near 1.0 for almost every run, so there is too little variance to judge agreement. It is inconclusive, not evidence of disagreement.

## 6. Evaluator limitations and where it may be unreliable

1. **Runbook-only reference answers bias the context metrics.**
   - **Contextual precision:** the evidence lists similar cases first, then runbook chunks. The judge marks the case lines "irrelevant" because the reference holds no case data (scores as low as 0.16 for G09 and G01), although those cases are useful evidence.
   - **Contextual recall:** reference verification sentences are never retrieved (next item).
2. **The rendered answer leaves out the similar-case list.** The 3 PRD queries ask "what similar conditions occurred before?". The API returns those cases as a table, but the text the judge scored (analysis and actions) doesn't list them, so answer relevancy drops (B G17: 0.02). This measures the evaluation setup, not the product.
3. **Ceiling effects.** Faithfulness, diagnosis validity and contextual relevancy are ≥ 0.9 or always pass for both systems, so they can't separate A from C, or B from C.
4. **The LLM judges are lenient on fallback content.**
   - **Phase 8:** the independent scorer passed rule-based fallback analyses.
   - **Here:** the runtime judge passed G17's fallback (groundedness 0.96).
   - Fallback text is grounded runbook content, so "pass" is defensible. But the judges reward groundedness, not diagnostic specificity.
5. **Small samples.**

   | Measure | Sample size |
   |---|---|
   | End-to-end runs | 11 |
   | Revised runs | 3 |
   | Seeded-error bases | 2 |
   | Out-of-scope queries in the golden set | 1 |
   | Labellers | 1 |

   Treat rates as indicative. Latency varies with provider load and with whether a revision happens. Report the aggregates, not single runs (G05's 163 s is a call-cap outlier).
6. **Circularity, still present** (plan risk R17): the retrieval relevance labels come from the same symptom flags that shape the case narratives. The manual spot check (§8) is the independent check, and it isn't done yet.
7. **Judge reliability incidents, recorded rather than hidden:** 2 empty replies from gpt-oss-20b, both re-scored successfully. The first attempt was truncated at a 2048-token reasoning allowance, and the run was restarted at 6144.

## 7. Findings for your decision (nothing changed)

| # | Finding | Evidence | Option, if you want to act |
|---|---|---|---|
| F1 | The per-run call cap of 8 is too tight once repair calls count against it | G05 lost its final judge call | Raise `MAX_LLM_CALLS_PER_RUN` to about 12 (the 50K token cap still bounds cost) |
| F2 | The runtime judge's verdict ignores issues it names itself | Seeded detection 0.75, with all 12 errors named | Treat failed `numbers_match_evidence` and `citations_valid` checks as critical, or fail when an issue targets fabricated IDs or numbers |
| F3 | The analyst is the only source of repairs and JSON fallbacks | All 4 repairs and the G17 fallback are analyst schema or garble errors | Look at the analyst output schema or prompt robustness (a prompt change, so it needs your approval) |
| F4 | Runbook verification sections are never retrieved | Contextual recall: verification sentences unsupported in every case | Add `verification` to the recommender's runbook sections |
| F5 | `/troubleshoot` median latency is 76 s, above the 60 s internal target | 7 no-revision runs: median 65 s; 4 revised runs: 117–169 s | Deferred, per your latency decision |
| F6 | The evaluation's rendered answer leaves out the similar-case list | Answer-relevancy dips on the PRD queries | Evaluation-only: include the case list in the rendered answer and re-score |

## 8. Still open
- **Manual relevance spot check (needs you):** fill in `components/manual_spot_check.csv` (5 queries × top 5 cases, a `relevant_y_n` column). It's the independent check on the automatic relevance labels.
- **Not done in this phase:** the edge-path sample outputs (§11.8), UI screenshots and the 2 search-mode comparisons. The raw JSON for all 11 A/C runs is in `deepeval/generations.json`.
- **Cut by the 3-day plan:** RAGAS and a second labeller.

## Files
| Item | Path under `evaluation/results/final/` |
|---|---|
| Headline table | `summary.md`, `summary.json` |
| Run configuration | `run_config.json` |
| End-to-end runs | `e2e/latency.csv`, `e2e/e2e_summary.json` |
| DeepEval | `deepeval/generations.json`, `deepeval_results.csv` (per case and metric, with the judge's reasons), `deepeval_summary.csv` |
| Judge meta-evaluation | `judge_meta/judge_meta_eval.csv`, `judge_meta_summary.json` |
| Classifier | `classification/classification_metrics.csv`, `classification_report.json` (confusion matrix, per-class scores) |
| Components | `components/kb_retrieval.csv`, `priority_results.csv`, `component_metrics.json`, `manual_spot_check.csv` |
| Retrieval, guardrails, feedback, ML | `retrieval/`, `guardrails/`, `feedback/`, `ml/` |
| Phase 8 baseline | `../runs/troubleshoot_run2_baseline/` |
