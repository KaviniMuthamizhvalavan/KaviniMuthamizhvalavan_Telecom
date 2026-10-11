# Evaluation Report

AI-Powered Telecom Network Operations Assistant. This report gives a general view of how the system was evaluated and what the results show. The full per-run records, with every metric and file, are:

- `evaluation/results/final/EVALUATION_REPORT.md`: Claude Sonnet 5.5 agents, Claude Opus 5.5 judge (2026-10-09).
- `evaluation/results/runs/aicredits_haiku_demo/DEMO_CONFIG_REPORT.md`: Claude Haiku 5.5 agents through AICredits, gpt-oss-120b judge (2026-10-11).

The app's Quality page shows both runs.

## 1. What was evaluated

| Question | How it was measured |
|---|---|
| Does search find the right historical cases? | 22 labelled queries; Hit@5, nDCG@10, filter compliance, latency; four search modes compared |
| Does the classifier understand the incident? | 24 golden queries (one or more per incident type, plus vague and off-topic queries) |
| Do the guardrails block bad input without blocking good input? | 12 should-block cases (injection, off-topic, gibberish, PII) and 27 should-pass queries |
| Are the ML predictions and priorities sound? | 20,000-row holdout for both models; 6 priority scenarios |
| Is the multi-agent answer better than a single-call (basic RAG) answer? | 11 end-to-end queries with runbook-based reference answers, scored by an LLM judge with DeepEval (faithfulness, relevancy, actionability, diagnosis validity, context metrics) |
| Can the built-in judge agent catch bad answers? | 6 types of error planted into real answers, plus clean controls |
| Does engineer feedback improve search? | Simulated relevance votes on 10 queries, with 10 control queries |
| Is it fast and affordable? | Latency, tokens and cost of every end-to-end run |

## 2. Two configurations

The LLM-based parts were measured twice. All other parts (search, guardrails, ML, prioritization, feedback) use no model and gave identical results in both runs.

| | Best capability | Demo setup (what the app runs) |
|---|---|---|
| Agents | Claude Sonnet 5.5, Claude API | Claude Haiku 5.5, AICredits gateway |
| Evaluation judge | Claude Opus 5.5 | gpt-oss-120b |
| Targets met | 26 of 28 | 27 of 28 |
| Cost of the full evaluation | about $11.4 | about $0.27 |
| Cost per analysis | about $0.076 | about $0.007 |

The answer-quality scores of the two runs come from different judges, so they are compared within a run, not across runs.

## 3. Results in brief

**Search.** The hybrid search (semantic + keyword, fused and reranked) found a relevant case in the top 5 for every query (Hit@5 1.0) and ranked results better than either search alone (nDCG@10 0.953 against 0.913 for keyword and 0.861 for semantic). It respected every filter and answers in about 0.13 to 0.15 s.

**Classifier and guardrails.** The AI classifier picked the right incident type for 21 of 22 queries (0.955) with both models, and the one miss was an acceptable alternative. The guardrails blocked 12 of 12 bad inputs and none of the 27 good ones.

**ML and prioritization.** The fault-risk model reaches ROC-AUC 0.874 and the throughput model R² 0.328. These scores are deliberately honest: columns that are formulas of the target were excluded. All 6 priority scenarios got the expected level.

**Multi-agent vs basic RAG.** Within each run, the multi-agent pipeline gives clearly more actionable answers, with verification steps, expected effects, change approval and escalation. Grounding is equally high in both systems.

| Within one run | Basic RAG | Multi-agent |
|---|---|---|
| Actionability, Sonnet run (Opus judge) | 0.60 | 0.84 |
| Actionability, demo run (gpt-oss judge) | 0.66 | 0.99 |
| Faithfulness (both runs) | 0.96 to 1.00 | 0.99 |

**Judge agent.** It caught 12 of 12 planted errors with no false alarm, with both Sonnet and Haiku.

**Feedback loop.** Votes improved ranking on the voted queries (nDCG@10 +0.006, 4 improved, 0 worse) and left control queries unchanged.

**Speed and reliability.**

| | Sonnet 5.5 | Haiku 5.5 (demo) |
|---|---|---|
| Median time per analysis | 31 s | 35 s |
| Slowest analysis | 34 s | 79 s |
| Answers passing the judge first time | 11 of 11 | 8 of 11 |
| Answers revised by the judge / marked low confidence | 0 / 0 | 3 / 2 |
| Failed or degraded runs | 0 | 0 |

## 4. What the results mean

1. **Search, classification, guardrails and the judge agent are solid** and do not depend on which model runs the agents.
2. **The multi-agent design is worth its extra calls:** answers are more actionable than a single call, and every answer is checked.
3. **Haiku is the right demo choice:** about 10× cheaper per analysis, with the same classification accuracy. It is less consistent than Sonnet, and the judge catches this: it revises weak answers and labels the rest "low confidence" instead of hiding them.
4. **Sonnet 5.5 remains the best measured capability** if quality matters more than cost.

## 5. Known gaps

- **Context metrics miss their target.** Contextual precision and recall measure how the evaluation's context list is ordered, and a runbook "verification" section the system never retrieves, not answer quality. Retrieving that section is listed as future work.
- **Synthetic data.** The dataset is generated, so results may not carry over directly to a real network.
- **Small test sets** (11 end-to-end queries) and a single labeller.
- **LLM judges are not perfect references.** The two judges score the same retrieval differently, which is why runs are compared internally.
