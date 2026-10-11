# /troubleshoot latency baseline and target decision (Phase 8, 2026-10-07)

## Decision
- Internal engineering target relaxed from "p95 <= 30 s" to **median end-to-end `/troubleshoot` latency <= 60 s**.
  p95 is reported separately and is not required to be under 60 s.
- This is an internal engineering target. The original project brief specifies no latency SLA.
- Rationale: the corrected Option B configuration has a measured clean-call floor of about 62 s before any
  revision or repair (classifier 2.1 s + analyst 30.0 s + recommender 7.5 s + judge 22.5 s per call), so 30 s is
  not realistic for this model/configuration.
- **Open gap:** the measured baseline median (103.2 s) does not meet the 60 s target either; the clean-call floor
  (~62 s) is itself just above it. No further latency optimization is to be done unless a later evaluation shows a
  concrete need (user instruction).

## Baseline configuration (frozen for later phases)
- Model `nvidia/nemotron-3-super-120b-a12b` (runtime and runtime judge); independent scorer `openai/gpt-oss-20b`.
- Reasoning (approved Option B): classifier OFF, analyst ON, recommender OFF, judge ON.
- Token allowances: analyst/judge reasoning allowance 4096 (`AGENT_REASONING_ALLOWANCE`); `/recommend` keeps 2048.
  `MAX_TOKENS_PER_RUN` 50000. Prompts: classifier_v1, analyst_v1, recommender_v1, judge_v1. Max revisions 1.

## Baseline measurement (run 2, after the three reliability fixes; LLM cache off; 8 queries: G17-G19 PRD + G05, G09, G13, G15, G24)
| Metric | Value |
|---|---|
| Median / p95 / max end-to-end latency | **103.2 s / 162.4 s / 177.1 s** |
| Runs completed successfully | **8/8** (`status=ok`, verdict pass 8/8; 4 after one revision) |
| Rule-based fallbacks | **0** |
| Truncation failures | **0** (run 1: 9) |
| Repair calls | 4 (schema violations only; all repaired) |
| LLM calls / tokens per run | 6.0 mean (max 8) / 26.7K mean (max 41.6K) |
| Mean time per agent (per call) | classifier 2.1 s (2.1), analyst 60.1 s (30.0), recommender 11.2 s (7.5), judge 33.8 s (22.5) |
| Classification | 7/8 strict, 8/8 counting acceptable alternatives |
| Tests | **103/103 passing** (all 5 required workflow paths) |
| Runtime judge quality (mean) | groundedness **0.84**, KPI consistency **0.90**, actionability **0.86**, completeness **0.91** |
| Independent judge (gpt-oss-20b) | **PROVISIONAL**: only 4/8 runs scored (the scoring client hit 3 timeouts and its own circuit opened). On those 4: 0.99 / 0.99 / 0.98 / 0.98, all pass. |

## Latency/quality trade-off observed
- Run 1 (allowance 2048, budget 30K): median 75.6 s, but 9 truncations, 4 fallbacks, 3 degraded runs, 1 PRD query
  wrongly stopped at clarification.
- Run 2 (allowance 4096, budget 50K, plan §8.2 clarification rule): every run completes with no fallback, but reasoning
  calls are longer (analyst ~16 s -> ~30 s per call) and the judge requests a revision in 50% of runs.
- Reliability was chosen over speed; reasoning settings were not changed to chase latency.

## Caveats
- The runtime judge and the diagnosis share one model (self-assessment bias); the independent scorer also passed the
  deterministic fallback analyses in run 1, so the LLM rubric is lenient. DeepEval (Phase 11) is the real quality measure.
- Provider latency varies (G05: 135 s with 4 calls and no repair).

Files: `troubleshoot_summary.json`, `troubleshoot_runs.csv`, `troubleshoot_samples.json` (run 2);
run 1 in `evaluation/results/runs/troubleshoot_run1_pre_fixes/`; logs `artifacts/troubleshoot_eval*.log`.
