# Phase 11 evaluation report (Claude)

**Date:** 2026-10-09 (run 09:39–10:10 UTC, 31 min)
**Configuration:** Claude Sonnet 5.5 for every runtime agent, including the runtime judge; Claude Opus 5.5 as the independent evaluation judge; per-run limit of 50K tokens and 12 LLM calls. No system changes were made for, or because of, this evaluation.
**Current default configuration differs from this run:** after the evaluation, all runtime agents and the evaluation judge were switched to Claude Haiku 5.5 for cost reasons (§8). The Phase 11 figures below are for the Sonnet 5.5 / Opus 5.5 configuration that was evaluated.
**Machine-generated companion:** `summary.md` (every headline metric against its target).
**Previous (NVIDIA) Phase 11 results:** kept unchanged in `../runs/phase11_nvidia_final_snapshot/` (45 files, SHA-256 manifest), including the NVIDIA version of this report. `PHASE11_FOLLOWUP.md` and `deepeval_v2/` in this folder also describe the NVIDIA run (see their headers).

Every number in this report comes from a file under `evaluation/results/final/`. To reproduce:

```
python -m evaluation.run_all --suite all       # about 30 min on the Claude API (about $11); never during a demo
python -m evaluation.run_all --suite quick     # no-LLM suites + summary (about 4 min)
```

## 1. What was evaluated and how

| Item | Setting |
|---|---|
| Runtime model | `claude-sonnet-5-5` (Anthropic Messages API) for classifier, analyst, recommender and runtime judge |
| Reasoning per agent | option B mapped to Claude: classifier and recommender thinking off (`between_tools`, effort low); analyst and judge adaptive thinking (effort medium) |
| Output limits | classifier 400, analyst 900 + 4096, recommender 2500, judge 500 + 4096 tokens |
| Per-run limits | 50K tokens, 12 LLM calls (repairs count), 1 revision |
| Runtime judge | Same model as the runtime agents (Sonnet 5.5) |
| Evaluation judge (DeepEval) | `claude-opus-5-5`, effort medium: a different tier from the runtime model, but the same model family |
| Judge adapter | `evaluation/deepeval_judge.py`, on the project LLM client: rate-limited, one JSON repair, cached (`artifacts/llm_cache_eval.db`) |
| End-to-end set | `tests/test_cases/rag_golden.json`: 11 queries, one per incident type plus the 3 PRD queries |

**Reference answers** are copied verbatim from the expected category's runbook: likely causes, corrective actions and verification (`evaluation/build_rag_golden.py`). Nothing was invented. Single labeller.

**Systems compared**

| System | What it is | How it was run |
|---|---|---|
| **A** | Basic RAG (`/recommend`), one LLM call | Uncached |
| **C** | Multi-agent `/troubleshoot`: classifier, analyst, recommender, judge, up to 1 revision | Uncached; real latency, tokens, repairs and fallbacks |
| **B** | C's first pass before any judge revision | Not scored this time: no C run was revised, so B is identical to C everywhere |

**DeepEval metrics:** faithfulness, answer relevancy, contextual relevancy, contextual precision, contextual recall, and G-Eval "Recommendation Actionability" and "Diagnosis Validity".

**API usage and cost** (Anthropic list prices; the evaluation judge's usage is in `deepeval/deepeval_judge_usage.json`, the runtime usage in `deepeval/generations.json` and `classification/`):

| Stage | Model | Calls | Input / output tokens | Cost |
|---|---|---|---|---|
| Classification (24 queries) | Sonnet 5.5 | 24 | 50,910 / 4,775 | ≈ $0.15 |
| End to end, C (11 runs) | Sonnet 5.5 | 44 | 174,024 / 48,986 | ≈ $0.84 |
| End to end, A (11 runs) | Sonnet 5.5 | 11 | 28,957 / 15,383 | ≈ $0.21 |
| DeepEval judge (154 scores) | Opus 5.5 | 520 (+102 cache hits within the run) | 982,199 / 296,992 | ≈ $9.87 |
| Runtime-judge meta-evaluation | Sonnet 5.5 | 14 | not recorded by the script | ≈ $0.3 (estimate) |
| **Total** | | | | **≈ $11.4** |

**Other suites, re-run on the current configuration:** retrieval ablation, KB retrieval Hit@3, classifier (LLM vs rules), guardrails, prioritization scenarios, feedback simulation, runtime-judge seeded errors, ML holdout metrics (from Phase 3; the models are unchanged). The no-LLM suites reproduce the NVIDIA-run numbers exactly (retrieval latency varies by a few milliseconds).

**Cut by the 3-day plan:** RAGAS, the 40-query golden set (24 are used), and a second labeller.

## 2. Headline results

From `summary.md`: **26 PASS, 2 FAIL, 1 informational.**

| Area | Result | Target | Status |
|---|---|---|---|
| Retrieval, hybrid_rerank | Hit@5 1.000, nDCG@10 0.953 (hybrid 0.934 vs best single mode 0.913), filter compliance 100%, p95 130 ms | 0.90 / ≥ best single mode / 100% / ≤ 300 ms | PASS |
| KB retrieval | Hit@3 0.909 | ≥ 0.90 | PASS |
| Classifier (LLM, reasoning off) | accuracy 0.955 (21/22), macro-F1 0.964, filters 1.000, out of scope 1/1 | 0.80 / 0.75 / 0.85 / 0.90 | PASS |
| Guardrails | block rate 1.000, false-positive rate 0.000 | ≥ 0.90 / ≤ 0.05 | PASS |
| Fault-risk model | ROC-AUC 0.874 | ≥ 0.85 | PASS |
| Performance model | R² 0.328 | ≥ 0.25 | PASS |
| Prioritization | exact 1.000, within one level 1.000 | 0.80 / 1.0 | PASS |
| Feedback loop | +0.006 nDCG@10 on voted queries; 0 control regressions | > 0 / 0 | PASS |
| `/troubleshoot` median latency | **31.4 s** | ≤ 60 s (internal target) | PASS |
| JSON failures after repair | 0 per 44 agent calls | ≤ 0.02 | PASS |
| Runtime judge, seeded-error detection | **1.00** (12/12) | ≥ 0.80 | PASS |
| DeepEval C: faithfulness, answer relevancy, contextual relevancy, actionability, diagnosis validity | 0.99 / 0.96 / 0.85 / 0.84 / 0.86 | per §11.5 | PASS |
| DeepEval C: **contextual precision** | **0.23** | ≥ 0.70 | **FAIL** (evaluation design, §6.1) |
| DeepEval C: **contextual recall** | **0.67** | ≥ 0.70 | **FAIL** (structural cap, §6.1) |

## 3. End-to-end runs (system C, LLM cache off)

| Metric | Phase 11, Claude (n=11) | Phase 11, NVIDIA (n=11, archived) | Phase 8 baseline, NVIDIA (n=8) |
|---|---|---|---|
| Latency median / p95 / max | **31.4 / 33.4 / 33.9 s** | 76.3 / 166.2 / 169.0 s | 103.2 / 162.4 / 177.1 s |
| LLM calls per run, mean / max | 4.0 / 4 | 5.4 / 8 | 6.0 / 8 |
| Tokens per run, mean / max | 20,273 / 22,561 | 23,127 / 39,113 | 26,734 / 41,645 |
| Repair calls (total) | 0 | 4 | 4 |
| Fallback events | 0 | 2 | 0 |
| Runs ending degraded | 0 | 2 of 11 | 0 of 8 |
| Verdicts | 11 pass | 10 pass, 1 unvalidated | 8 pass |
| Revision rate | 0.00 | 0.36 | 0.50 |

**Reading the latency.** Every run took 29–34 s because every run passed the runtime judge on the first round, so no run paid for a revision (on NVIDIA, revised runs took 117–169 s). Comparisons across providers and query sets are indicative only. System A (one call) takes a median of 8.8 s (p95 10.0 s) and about 4.0K tokens per run.

**Token budget.** The largest run used 22,561 tokens, 45% of the 50K budget. No run hit the token or call limit.

**Classification.** 11/11 end-to-end runs got the expected category exactly, including G19 (FAULT_ALARM; the NVIDIA run chose the acceptable alternative MOBILITY_HANDOVER). On the 22-query classifier set the only miss is G23 (CONGESTION_CAPACITY instead of TRANSPORT_QOS; counted correct under the lenient rule).

**No failure cases** in this run: no repairs, fallbacks, budget stops or low-confidence (validator fail) runs. The revision path and the fallback paths were therefore not exercised on Claude by this evaluation; they are covered by the unit and graph tests only.

## 4. Answer quality (DeepEval, judge claude-opus-5-5): mean score / pass rate

| Metric (threshold) | A: basic RAG (n=11) | C: multi-agent (n=11) |
|---|---|---|
| Faithfulness (0.7) | 1.00 / 1.00 | 0.99 / 1.00 |
| Answer relevancy (0.7) | 0.94 / 0.91 | 0.96 / 0.91 |
| Contextual relevancy (0.5) | 0.85 / 1.00 | 0.85 / 1.00 |
| Contextual precision (0.7) | 0.23 / 0.00 | 0.23 / 0.00 |
| Contextual recall (0.7) | 0.61 / 0.00 | 0.67 / 0.00 |
| G-Eval Recommendation Actionability (0.7) | **0.60 / 0.09** | **0.84 / 1.00** |
| G-Eval Diagnosis Validity (0.7) | 0.73 / 0.82 | 0.86 / 1.00 |

All 154 scores were produced; 0 judge errors, nothing missing or timed out.

**What the comparison shows:**
- **Actionability is the clear multi-agent gain:** 0.84 vs 0.60, pass rate 1.00 vs 0.09. The judge calls A's actions "concrete and sensibly ordered" but scores them 0.5–0.6; C's actions add verification, expected KPI effects, change approval and escalation.
- **Diagnosis validity also separates the systems:** 0.86 vs 0.73. A fails on G09 and G19 (0.6).
- **Faithfulness and contextual relevancy are at the ceiling for both systems.**
- **Answer relevancy fails only on G17, for both A (0.62) and C (0.69):** the PRD query asks for similar past conditions, which the API returns as a case table that the rendered answer does not include (§6.3).
- **Contextual precision and recall are identical in design for A and C** and do not measure answer quality (§6.1).

## 5. Runtime judge meta-evaluation (seeded errors, `judge_meta/`)

Six error types were injected into two real passing diagnoses (G01, G03), plus an unmodified control of each.

| Seeded error | Caught (verdict fail) | Named in the judge's issues or rule checks |
|---|---|---|
| Recommendation without a runbook citation | 2/2 | 2/2 |
| Cause contradicting the KPI anomalies | 2/2 | 2/2 |
| Action irrelevant to the incident type | 2/2 | 2/2 |
| Overclaimed causality | 2/2 | 2/2 |
| Invented case ID | 2/2 | 2/2 |
| KPI number contradicting the evidence | 2/2 | 2/2 |
| Controls: false alarms | 0/2 | n/a |

**Detection rate: 1.00 against a 0.80 target (PASS).** The NVIDIA runtime judge reached 0.75 because it named errors but scored above the pass line; the Claude judge fails every seeded diagnosis and raises no false alarm on the controls. No judge code or prompt changed between the two runs.

**Agreement with DeepEval:** Spearman 0.58 (n=11) between runtime groundedness and DeepEval faithfulness. Faithfulness is near 1.0 for every run, so there is little variance to agree on; treat it as weakly positive.

## 6. Evaluator limitations and where it may be unreliable

1. **Contextual precision and recall measure the evaluation's context layout, not answer quality.** Investigated in detail on 2026-10-09:
   - **Precision is decided by position.** The `retrieval_context` passed to DeepEval is built by `evidence_items()` in `run_e2e_generate.py` as: all similar-case lines, then runbook chunks, then data sections. It is not a ranked retrieval list. The reference answers contain only runbook text, so the judge counts only runbook chunks as relevant. For system A (5 cases, then 3 runbook chunks) that gives (1/6 + 2/7 + 3/8) / 3 = **0.2758**, exactly the score recorded for G01, G03, G11, G13 and G17. System A's context is byte-identical to the NVIDIA run, where gpt-oss-20b scored the same items 1.00 by calling the case records "relevant examples"; Opus applies DeepEval's definition strictly.
   - **Recall is capped at 2/3 by design.** Each reference answer has three parts: likely causes, corrective actions and verification. No agent retrieves the runbook `verification` section (`ROLE_SECTIONS` in `src/rag/hybrid_retriever.py` covers only KPI signature, root causes, diagnostic checks, corrective actions and escalation), so the third part is never supported: 0.667 on 21 of 22 cases (G19 A: 0.00). gpt-oss scored 0.75 by crediting it.
   - **A product gap behind the recall cap:** the recommender writes a `verification` field for every step, but the runbook's verification criteria are never in its evidence, so those verification steps are not grounded in the knowledge base.
2. **Same-family judge.** Opus 5.5 judging Sonnet 5.5 output is less independent than the earlier cross-family setup (gpt-oss judging Nemotron); self-preference cannot be ruled out. The two runs are a new baseline, not comparable metric by metric with the NVIDIA run.
3. **The rendered answer leaves out the similar-case list** (G17 answer relevancy, both systems). This measures the evaluation setup, not the product.
4. **The revision and fallback paths were not exercised**: 0 revisions, repairs and fallbacks in 11 runs. Their behavior on Claude is covered only by tests.
5. **Ceiling effects.** Faithfulness (means 0.99–1.00) and contextual relevancy (means ≈ 0.85) pass on every case for both systems, so they cannot separate A from C.
6. **Small samples:** 11 end-to-end runs, 2 seeded-error bases, 1 out-of-scope query, 1 labeller. Treat rates as indicative.
7. **Circularity** (plan risk R17): retrieval relevance labels come from the same symptom flags that shape the case narratives. The AI-annotated spot check (`components/manual_spot_check.csv`, reviewed in `PHASE11_FOLLOWUP.md`) is the independent check.
8. **DeepEval telemetry was on during this run.** `DEEPEVAL_TELEMETRY_OPT_OUT` was not in the process environment, so DeepEval initialised its telemetry (PostHog events, Sentry, an OpenTelemetry exporter whose New Relic connection failed certificate verification). Fixed afterwards: `evaluation/__init__.py` now sets the opt-out before any DeepEval import. Results are unaffected.

## 7. Status of the earlier findings, and open findings (nothing changed by this evaluation)

| # | Finding | Status |
|---|---|---|
| F1 | Call cap of 8 too tight once repairs count | Done before this run: cap 12 (P1). No run needed more than 4 calls. |
| F2 | Runtime judge verdict ignored issues it named | Not reproduced on Claude: seeded detection 1.00. No code change was made. |
| F3 | Analyst was the only source of repairs | Analyst-output normalization added (P3); 0 repairs in this run. |
| F4 | Runbook verification sections are never retrieved | **Open.** Causes the 0.667 recall cap and ungrounded verification steps (§6.1). |
| F5 | Median latency above 60 s | Met: 31.4 s. |
| F6 | Rendered answer leaves out the similar-case list | **Open.** G17 answer relevancy (A and C). |
| F7 | Contextual precision depends on the order of the evaluation's context list | **New.** Evaluation-only (§6.1). |

## 8. Cost decision after this run: Claude Haiku 5.5 (2026-10-09)

The full evaluation above cost about $11.4, mostly the Opus 5.5 judge. For budget reasons every runtime agent (including the runtime judge) and the default evaluation judge now use **Claude Haiku 5.5** ($0.10 / $0.50 per million input / output tokens, against $2 / $10 for Sonnet 5.5 and $4 / $20 for Opus 5.5). The full Phase 11 suite was **not** re-run on Haiku. The evidence for the switch is a $0.12 agent-only test on the same queries (`../runs/haiku_runtime_test/`: classification, the 11 end-to-end queries, and the seeded-error judge test; no DeepEval judge).

| | Haiku 5.5 (test) | Sonnet 5.5 (this report) |
|---|---|---|
| Cost per `/troubleshoot` query | ≈ $0.0074 | ≈ $0.076 |
| Cost per `/recommend` query | ≈ $0.0013 | ≈ $0.019 |
| Classifier primary accuracy (22 queries) | 0.955 | 0.955 |
| Verdicts (11 runs) | 8 pass, 3 fail (low confidence) | 11 pass |
| Runs with a revision | 5 | 0 |
| Repairs / fallbacks / degraded runs | 1 judge repair / 0 / 0 | 0 / 0 / 0 |
| Latency median / max | 35.6 s / 72.6 s | 31.4 s / 33.9 s |
| Tokens per run, mean / max | 33,765 / 54,625 | 20,273 / 22,561 |
| Runtime judge seeded-error detection | 12/12, 0 false alarms on 2 controls | 12/12, 0 false alarms |

**What changes with Haiku:**
- **Weaker citation discipline.** The `citations_valid` rule failed on 8 of 11 runs: the analyst cites the section label `IMPACT & PRIORITY`, and in one run (G07) a runbook ID that was not in its evidence. The rule removes them; the judge then marks the affected claims as weak.
- **More overclaiming.** Correlations stated as causes ("made worse by adverse weather"); in G01 a disruptive reroute is placed before the diagnostic checks.
- **The judge is not the weak link.** The Haiku runtime judge caught every seeded error, raised no false alarm, and its issues on the real runs were correct. The revisions it requests are what raise latency and tokens on the affected runs.
- **The 50K per-run token budget can be exceeded by the final call.** The budget is checked before each call, and G11 (8 calls, including 1 repair) ended at 54,625 tokens. Nothing was refused. At Haiku prices that run cost about $0.01.
- **The evaluation judge is no longer independent.** With Haiku as both runtime model and default evaluation judge, any future DeepEval scores come from the model that wrote the answers. Set `EVAL_LLM_MODEL=claude-opus-5-5` (or `claude-sonnet-5-5`) to repeat this report's judge setup, at about $10 (or about $5) per full DeepEval pass.

**Cost of a future full Phase 11 run (all Haiku):** roughly $0.35–0.50, estimated from this run's token counts and current list prices. Not run.

## Files
| Item | Path under `evaluation/results/final/` |
|---|---|
| Headline table | `summary.md`, `summary.json` |
| Run configuration | `run_config.json` |
| End-to-end runs | `e2e/latency.csv`, `e2e/e2e_summary.json` |
| DeepEval | `deepeval/generations.json`, `deepeval_results.csv` (per case and metric, with the judge's reasons), `deepeval_summary.csv`, `deepeval_judge_usage.json` |
| Judge meta-evaluation | `judge_meta/judge_meta_eval.csv`, `judge_meta_summary.json` |
| Classifier | `classification/classification_metrics.csv`, `classification_report.json` |
| Components | `components/kb_retrieval.csv`, `priority_results.csv`, `component_metrics.json`, `manual_spot_check.csv` |
| Retrieval, guardrails, feedback, ML | `retrieval/`, `guardrails/`, `feedback/`, `ml/` |
| NVIDIA-era (historical) | `PHASE11_FOLLOWUP.md`, `deepeval_v2/`, `deepeval/deepeval_results_partial_run1.csv`, `troubleshoot/` (Phase 8), `../runs/phase11_nvidia_final_snapshot/` |
| Run log | `../runs/phase11_claude_run.log` |
| Haiku 5.5 agent test (cost decision) | `../runs/haiku_runtime_test/` |
| Phase 8 baseline | `../runs/troubleshoot_run2_baseline/` |

## 9. Appended 2026-10-11: demo configuration (Claude Haiku 5.5 via AICredits)

Everything above is unchanged and remains the record of the Sonnet 5.5 / Opus 5.5 configuration, the highest capability measured. The full suite was then re-run on the configuration used for the demo: Claude Haiku 5.5 for all agents through the AICredits gateway, with `openai/gpt-oss-120b` as the evaluation judge. Its results are in a separate folder, `../runs/aicredits_haiku_demo/` (report: `DEMO_CONFIG_REPORT.md`, headline table: `summary.md`). The Quality page shows both runs, named by their models. Cost: $0.27 (about ₹27.5).

| | Haiku 5.5 via AICredits | Sonnet 5.5 (this report) |
|---|---|---|
| Targets met | 27 of 28 | 26 of 28 |
| Classifier primary accuracy | 0.955 | 0.955 |
| `/troubleshoot` median / max latency | 34.8 / 78.8 s | 31.4 / 33.9 s |
| Verdicts (11 runs) | 9 pass, 2 low confidence; 3 revised | 11 pass; 0 revised |
| Runtime judge, seeded errors caught | 12/12, 0 false alarms | 12/12, 0 false alarms |

The no-LLM results (retrieval, KB, prioritization, guardrails, ML, feedback loop) reproduce this report exactly. The answer-quality (DeepEval) scores come from a different judge family and are not comparable with §4. For example, contextual precision is 0.80 there against 0.23 here, on identical retrieval. See `DEMO_CONFIG_REPORT.md` §2.
