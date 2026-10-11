# Demo configuration evaluation: Claude Haiku 5.5 via AICredits (2026-10-11)

**What this is:** the full Phase 11 suite, re-run on the configuration the app uses for the demo:
- **Agents:** Claude Haiku 5.5 for every runtime agent, including the runtime judge, through the AICredits gateway (`anthropic/claude-haiku-5.5`).
- **Evaluation judge:** `openai/gpt-oss-120b`, also through AICredits.

**What it is not:** a replacement for the Phase 11 report. That report is `evaluation/results/final/EVALUATION_REPORT.md`: Claude Sonnet 5.5 agents and a Claude Opus 5.5 judge, through the direct Claude API. It stays unchanged as the record of the system's highest measured capability. Before this run, all 46 files under `final/` were checksummed; they were identical after it. The only later change to `final/` is the §9 pointer appended to its report.

**Files:** everything in this folder. `summary.md` holds every headline metric against its target. `run.log` is the full console log; it is kept locally only (8.9 MB, ignored by `*.log` like the other run logs). `run_config.json` records the models and the commit (`af9a7d8`).

**Reproduce:**

```
python -m evaluation.run_variant --out evaluation/results/runs/aicredits_haiku_demo --suite all
```

This uses `.env` as is: `LLM_PROVIDER=aicredits`, `EVAL_LLM_MODEL=openai/gpt-oss-120b`. The no-LLM suites take about 4 min; the LLM suites took about 2 h, mostly the evaluation judge at 2 concurrent calls.

**Cost:** $0.27, about ₹27.5, from the spend ledger `artifacts/llm_spend.db` for 2026-10-11:

| Model | Calls | Cost |
|---|---|---|
| Claude Haiku 5.5 (agents) | 105 | $0.13 |
| gpt-oss-120b (judge) | 562 | $0.14 |

The total includes a first scoring attempt that was stopped (see "Run notes") and a few single-call probes.

## 1. Results next to the Phase 11 run

The first block of rows does not depend on the model and reproduces the Phase 11 values exactly; only timing varies. The later blocks depend on the model or on the judge.

| Area | Haiku 5.5 via AICredits (this run) | Sonnet 5.5, Phase 11 (`final/`) |
|---|---|---|
| **No model involved** | | |
| Retrieval, KB, prioritization, guardrails, ML, feedback loop | Same values | Same values |
| Retrieval p95 latency | 151 ms | 130 ms |
| **Agents (model-dependent)** | | |
| Classifier primary accuracy (22 queries) | 0.955 | 0.955 |
| Classifier macro-F1 | 0.964 | 0.964 |
| `/troubleshoot` latency, median / p95 / max | 34.8 / 78.6 / 78.8 s | 31.4 s median, 33.9 s max |
| Model calls per run, mean / max | 5.0 / 8 | 4 per run (no revisions) |
| Tokens per run, mean / max | 31,823 / 59,019 | 20,273 / 22,561 |
| Verdicts (11 runs) | 9 pass, 2 low confidence (G18, G19) | 11 pass |
| Runs revised by the judge | 3 (G11, G18, G19) | 0 |
| Repairs / fallbacks / degraded runs | 2 / 0 / 0 | 0 / 0 / 0 |
| Runtime judge, seeded errors caught | 12/12, 0 false alarms on 2 controls | 12/12, 0 false alarms |
| Basic RAG (system A), median latency / tokens per run | 9.5 s / 4,845 | 8.8 s / 4,030 |
| **Answer quality (judge-dependent: see §2)** | judge gpt-oss-120b | judge Claude Opus 5.5 |
| Faithfulness, C | 0.99 | 0.99 |
| Answer relevancy, C | 0.87 | 0.96 |
| Contextual relevancy, C | 0.78 | 0.85 |
| Recommendation actionability, A → C | 0.66 → 0.99 | 0.60 → 0.84 |
| Diagnosis validity, C | 0.89 | 0.86 |
| Contextual precision, C | 0.80 (PASS) | 0.23 (FAIL) |
| Contextual recall, C | 0.70, i.e. 0.697 (FAIL by 0.003) | 0.67 (FAIL) |
| Targets met | 27 of 28 | 26 of 28 |

## 2. How to read it

- **Haiku answers as well on most queries but is less consistent.** Classification is identical. 8 of 11 runs passed the runtime judge first time. The judge revised 3 runs and marked 2 of them low confidence. Those 3 runs explain the higher p95 latency and token use.
- **The runtime judge is not the weak link.** The Haiku judge caught every planted error with no false alarm, as in the Sonnet run.
- **Answer-quality scores are not comparable across the two runs.** They come from different judges in different model families. The clearest sign is contextual precision: 0.80 here against 0.23 under Opus, on retrieval that is identical in both runs. Contextual precision, recall and relevancy never read the answer (see the Phase 11 report, §6.1), so that gap is the judge alone. Compare the systems within this run (A, B, C), not the numbers across runs.
- **Within this run, the multi-agent pipeline still beats basic RAG where it matters:** actionability 0.99 against 0.66, and faithfulness 0.99 against 0.96. The judge's revisions helped: faithfulness on the 3 revised runs went from 0.977 (first pass, B) to 0.993 (after revision, C).
- **Contextual recall misses its target by 0.003**, the same structural cap of about 0.67 described in the Phase 11 report §6.1. It is not a regression.

## 3. Run notes and deviations

1. **AICredits cannot switch thinking off.** In this run the classifier and recommender may reason, where the Phase 11 configuration had thinking off for them. The classifier rows in this run's summary are therefore labelled "Classifier (LLM)", not "Classifier (LLM, reasoning off)" (label corrected on 2026-10-11; no values changed).
2. **The evaluation judge was rate-limited at first.** gpt-oss-120b through AICredits returned 429 on bursts of simultaneous calls, although sequential calls succeeded and the gateway reported 1,000 requests per minute remaining. The first scoring attempt was stopped with no scores. `evaluation/deepeval_judge.py` now allows 2 judge calls at a time and retries a rate-limited call with backoff. This is evaluation-only; the app's runtime client is unchanged. Scoring was then re-run in full; the agents' outputs (`deepeval/generations.json`) were not regenerated.
3. **Two scores could not be produced.** For G03, system C, the judge's verdict list for faithfulness and for answer relevancy exceeded its 1,500-token output limit and was cut off (invalid JSON). This happened again on retry, so both are recorded as judge failures. Those two metrics are averaged over 10 queries, not 11.
4. **The ML holdout metrics are copied, not recomputed.** `ml/` is copied from `final/ml/` (see `ml/COPIED_FROM_FINAL.txt`): the scikit-learn models are unchanged and no evaluation script recomputes them.
5. **Same test sets as Phase 11:** 24 classification queries (22 scored for accuracy), 11 end-to-end queries, 12 seeded errors plus 2 controls. Single labeller, AI-annotated spot check, as described in the Phase 11 report.
