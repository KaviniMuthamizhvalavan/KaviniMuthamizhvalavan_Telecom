> **NVIDIA-era document (historical).** Everything below describes the first Phase 11 run on NVIDIA (runtime `nvidia/nemotron-3-super-120b-a12b`, evaluation judge `openai/gpt-oss-20b`), before the Claude migration. Its findings are kept unchanged as the record of that run. The current Phase 11 results (Claude Sonnet 5.5 runtime, Claude Opus 5.5 evaluation judge, 2026-10-09 09:39–10:10 UTC) are in `EVALUATION_REPORT.md` and `summary.md`; the NVIDIA results referred to below are preserved in `../runs/phase11_nvidia_final_snapshot/`. The Claude run did not regenerate `components/manual_spot_check*` or `deepeval_v2/`, so the spot-check section (§1) still applies as written.

# Phase 11 follow-up: evaluation-only work and proposed runtime changes

**Date:** 2026-10-09
**Production code, configuration, prompts and frontend:** unchanged.
**Baselines kept:** the Phase 11 v1 results stay where they were, with a snapshot and SHA-256 checksums in `../runs/phase11_baseline_v1/`. All checksums verify OK, including the annotated spot-check CSV. The frozen Phase 8 baseline is untouched.

## 1. Manual relevance spot check (AI-annotated)

**Inputs.** `components/manual_spot_check.csv` covers 5 queries × the top 5 cases from `hybrid_rerank`.
- Its `relevant_y_n` and `notes` columns were filled by a separate AI, which read the query, the case rank, the one-line case summary and the automatic symptom overlap.
- The file is read-only here. The review is a separate file, `components/manual_spot_check_review.csv` (`.json` for the totals), built by `evaluation/review_spot_check.py`.

**How to read the labels.** "yes" means the AI judged that a case shows the query's symptoms, from the case summary text. It does **not** mean the case is a useful precedent beyond matching symptoms; nobody judged location, cause or outcome.

| | Result |
|---|---|
| AI-labelled relevant (Precision@5) | 24 / 25 (0.96) |
| Dataset symptom flags: case has every expected symptom | 25 / 25 (1.00) |
| AI label agrees with the dataset | 24 / 25 (0.96) |
| AI notes mention only symptoms visible in the summary it was given | 25 / 25 |

**Rows flagged for your review.** None were relabelled.

| Row | AI label | Why flagged |
|---|---|---|
| G17 #1 CASE-037746 | **no** ("missing throughput degradation") | **Probably a mislabel.** The dataset flags throughput as degraded (336.7 Mbps). The case has 5 abnormal KPIs, but its summary shows only the first 4, and throughput was the 5th. The annotator judged correctly from the text it saw; the text was incomplete. |
| G05 #1–#4 | yes | Each case has both expected symptoms (weak signal, low setup success), but symptom overlap is only 0.33–0.40 because several unrelated KPIs are also abnormal (e.g. critical latency). Whether a case with many extra problems counts as "relevant" is a judgement call. The label is defensible either way. |

**Limitations of the AI annotations**
1. **Not independent of the system.** The annotator read the same summaries and the automatic overlap score that the automatic labels come from, so it can't fully break the circularity noted in §6.6 of the report. It checks the summaries, not the underlying data.
2. **Summary truncation.** Case summaries list at most 4 abnormal KPIs, and that is how G17 #1 went wrong.
3. **Not a person.** It's a single AI annotator, with no measure of agreement between annotators. The plan asked for a person; these labels stand in for one until you review them.
4. **Small, easy sample.** 5 queries, all single-incident-type symptom queries with filters, so it doesn't test vague or mixed queries.

**Conclusion (provisional):** the annotations support the automatic relevance labels, with 0.96 agreement and 1 explainable disagreement. They remain AI-generated and should be described that way in any report.

## 2. Corrected scoring input (evaluation only)

**The problem.** The first scoring passed the judge only the analysis and actions, without the similar-case list the API returns. The 3 PRD queries ask "what similar conditions have occurred before?" and similar questions.

**The correction.** `evaluation/run_deepeval_rescore.py` puts the API's `similar_cases` list in front of the original scored answer. Nothing else changed: same generations (no new system runs), retrieved evidence, references, metrics, thresholds and judge. Results are in `deepeval_v2/`: `comparison_per_case.csv` and `comparison_summary.csv`.

**Which metrics could change.** Contextual precision, recall and relevancy never read the scored answer, so they cannot change because of the correction. Any change in them is evaluator noise.

### Before (v1) → after (v2), mean score; deltas paired on cases scored both times

| Metric | A: basic RAG | B: first pass (n=3) | C: multi-agent |
|---|---|---|---|
| Answer relevancy | 0.896 → **0.945** | 0.640 → **0.755** | 0.840 → 0.847 (n=10, see note) |
| … PRD queries only (G17–G19) | 0.618 → **0.903** | n/a | 0.597 → 0.688 |
| … other 8 queries | 1.000 → 0.961 | n/a | 0.894 → 0.886 |
| Faithfulness | 0.985 → 1.000 | 1.000 → 1.000 | 0.981 → 0.991 |
| Actionability (G-Eval) | 0.600 → 0.636 | 1.000 → 1.000 | 0.973 → 0.986 |
| Diagnosis validity (G-Eval) | 0.914 → 0.905 | 0.900 → 0.917 | 0.923 → 0.918 |
| Contextual precision | 0.868 → 0.868 | 0.778 → 0.778 | 0.733 → 0.729 (1 case, noise) |
| Contextual recall | 0.655 → 0.655 | 0.778 → 0.778 | 0.752 → 0.739 (1 case, noise) |
| Contextual relevancy | 0.753 → 0.754 (1 case, noise) | 0.698 → 0.716 (1 case, noise) | 0.762 → 0.762 |

**Note on C answer relevancy.** G18 C errored in v2 three times: one timeout and two empty judge replies. It is **unscored**, so the C comparison is paired over 10 cases.

### Attribution
- **Real effect of the correction: answer relevancy on the PRD queries.**
  - **System A:** G17 went 0.32 → 1.00, and G18 0.54 → 0.71.
  - **System B:** G17 went 0.02 → 0.57.
  - These answers were being marked down for "not listing past conditions" that the system had in fact returned.
- **Little effect for C.** C's G17 answer is the rule-based fallback (§4), and it stays low (0.39 → 0.38). Answer relevancy scores the *share* of answer statements that address the question. A long answer full of causes and actions stays mostly "off-question" even with 5 case lines added.
- **Evaluator noise, not an input effect:**
  1. **Contextual metrics.** Four of them changed on unchanged input, by up to **0.13** (G17 C contextual recall 0.80 → 0.67). Their original judge replies had needed a JSON repair, and repaired replies aren't cached, so they were re-generated. **Treat any difference under about 0.13 on a single case as noise.**
  2. **Non-PRD answer relevancy.** It moved by up to 0.32 in both directions (e.g. G05 A 1.00 → 0.68; G03 C 0.55 → 0.76). Those queries don't ask for precedents, so this is mostly noise, plus some "off-question" penalty for the added case lines.
- **No change in system quality.** The system was not re-run; v1 and v2 score the same generations. The corrected input fixes a measurement error only: the real gain is on queries asking for precedents, and everything else is evaluator variation.

**Updated reading of the A-vs-C answer-relevancy gap.** With the case list included, the gap is 0.945 vs 0.847. A still leads, because the metric rewards short, on-question answers and C's answers are longer and more complete. Actionability remains the clearest difference (C 0.986 vs A 0.636).

## 3. Measured vs provisional

| Result | Status | Why |
|---|---|---|
| Retrieval metrics, KB Hit@3, guardrails, prioritization, ML holdout, feedback simulation | **Measured** | Deterministic; rerunnable |
| End-to-end latency, calls, tokens, repairs, fallbacks (n=11, cache off) | **Measured**, small sample | Provider load and revision rate move latency; one run per query |
| Classifier accuracy and macro-F1 (22 labelled queries) | **Measured**, small sample | Single labeller; 1 off-topic query |
| DeepEval scores | **Provisional** | One judge model; per-case noise up to about 0.13 (v1 vs v2), more for answer relevancy; 1 unscored case (G18 C, v2); runbook-only references bias the context metrics |
| Revision effect (B vs C) | **Provisional** | n=3; scores near the ceiling |
| Runtime-judge seeded-error detection (0.75) | **Measured on a small seeded set** | 12 seeds on 2 bases |
| Runtime judge vs DeepEval agreement (Spearman 0.25) | **Inconclusive** | n=10 with almost no variance in faithfulness |
| Manual relevance spot check | **Provisional** | AI-generated labels, not independent; 1 likely mislabel |

## 4. Failure analysis

**G05 ("Weak signal and customers cannot connect, calls failing to set up"): ended degraded, verdict "unvalidated", 163.5 s.**
1. **Calls used:** classifier (1), analyst (1) + analyst repair (1), recommender (1), judge (1, verdict fail: groundedness 0.60, 5 issues). The judge asked for one revision.
2. **Revision round:** analyst (1) + repair (1), recommender (1). That brought the run to **8 calls**, the per-run cap.
3. **Cause:** the second judge call was refused (`per-run LLM budget reached`), so the run fell back to rule checks only, with verdict "unvalidated" and a warning. Tokens (30,954) were well under the 50K cap; the *call* cap was the binding limit.
4. **Root cause:** a cap of 8 assumes no repairs (4 agents + 3 revision calls = 7). Analyst repairs each use a call.
5. **Repair causes:** a citation sent as a list where a string is expected (round 1), then hypotheses over-length or garbled (round 2).

**G17 (PRD query 1, latency, packet loss, throughput): ended degraded, verdict pass, 116.9 s.**
1. **Round 1:** analyst OK, recommender OK; the judge asked for a revision (groundedness 0.55).
2. **Revision round:** the analyst's reply was structurally garbled. Contributing-factors content spilled into the `hypotheses` array (4 items where at most 3 are allowed) and required fields went missing. The one repair attempt was also invalid, so the deterministic fallback analysis (runbook root causes plus KPI evidence) was used.
3. **Outcome:** the recommender ran on the fallback analysis, and the judge passed it (groundedness 0.96). The response correctly reports `degraded` with "the analyst agent was unavailable; a rule-based analysis is shown".
4. **Root cause:** analyst JSON robustness under reasoning mode, not the graph. The fallback and status handling worked as designed. Note that the judge passing a fallback says the content is grounded, not that it's specific.

## 5. Proposed runtime changes (NOT implemented; for your decision)

### P1. Raise the per-run LLM call cap from 8 to 12
```diff
# src/utils/config.py
-    max_llm_calls_per_run: int = 8
+    max_llm_calls_per_run: int = 12  # 4 agents + 3 revision calls + up to 4 repair calls = 11, plus headroom

# .env.example (document it; it is not listed there today)
+MAX_LLM_CALLS_PER_RUN=12
```
- **Expected benefit:** runs like G05 keep their final judge call, so they end "pass" or "fail" instead of "unvalidated". In Phase 11 this affects 1 of 11 runs.
- **Risk:** the worst-case run gets longer. Each extra call is a repair (10–20 s) or a judge call (15–30 s), so the worst case grows by about 1 minute (it was 169 s). The 50K token cap still bounds cost; the maximum seen is 39K. The median is unaffected, since most runs use 4 calls.

### P2. Strengthen the judge's revision triggers
**Problem.** The judge named all 12 seeded errors but only failed 9. On real runs, `citations_valid` failed only on formatting variants, never on a fabricated ID.

```diff
# src/rag/context_builder.py: strip_unknown parses citations before checking them
+ID_RE = re.compile(r"CASE-\d{6}|KB-[A-Z_]+-[a-z0-9-]+")
 def strip_unknown(citations, allowed):
-    for c in citations:
-        cid = str(c).strip().strip("[]")
+    for c in citations:
+        # "CASE-055660; SEGMENT STATS" and "SIMILAR CASES (CASE-080863)" carry valid IDs; keep those, plus known section names
+        found = ID_RE.findall(str(c)) or [p.strip().strip("[]") for p in re.split(r"[;,]", str(c)) if p.strip()]
+        for cid in found: ...

# src/agents/judge_agent.py: rule_checks
+    fabricated = sorted({x for x in removed if ID_RE.fullmatch(x)})  # well-formed IDs that are not in the evidence
+    checks.append({"rule": "no_fabricated_ids", "passed": not fabricated, "critical": True, "target": "analyst", ...})
-    checks.append({"rule": "numbers_match_evidence", ..., "critical": False, ...})
+    checks.append({"rule": "numbers_match_evidence", ..., "critical": True, ...})
```

- **Expected benefit:**
  - Seeded detection should rise from 0.75 to about 1.0: the 3 misses were a fabricated case ID and two contradicted KPI numbers, and both would now force a revision.
  - Fixing the citation parsing also stops 3 of 11 real runs from logging a spurious `citations_valid` failure.
- **Risks:**
  1. **False alarms from the number check.** It matches numbers by regex within ±1% and is best-effort. It failed on 0 of 11 real Phase 11 runs, but a derived number (e.g. a computed percentage) could still trigger a needless revision, costing about 50–70 s, and the low-confidence warning would appear more often.
  2. **Stricter outcome after a revision.** A critical failure that survives the one allowed revision makes the verdict "fail". Mitigation: re-run the seeded-error test and the 11-query end-to-end set after the change.

### P3. Improve analyst output robustness (no prompt change in step 1)

**Step 1: normalize before validating** (`src/agents/analyst_agent.py`, Pydantic `field_validator(mode="before")`):
- `ContributingFactor.citation`: a list becomes its first element (fixes the most common error, seen twice in Phase 11).
- `supporting_evidence` and `citations`: a single string becomes a one-item list.
- `hypotheses` and `contributing_factors`: drop items that aren't objects (the "garbled" pattern), then keep the first 3 hypotheses and the first 6 factors. The prompt already orders hypotheses most likely first. Log a warning whenever anything is dropped or truncated.
- Required fields stay required: a reply missing `impact_narrative` still goes to repair and then to the fallback.

**Step 2, optional and probe first:** NVIDIA NIM structured generation for the analyst call only (`extra_body={"nvext": {"guided_json": AnalystOutput schema}}`), the fallback that plan §6.4a anticipated. Before adopting it, check that Nemotron 3 Super supports it and what it does to latency.

- **Expected benefit:** in Phase 11, step 1 would have removed the type-error repairs and made the over-length replies valid, so 2–3 of the 4 repairs and possibly G17's fallback would not have happened. That saves 10–20 s per avoided repair, a call against the cap, and degraded outcomes.
- **Risks:**
  1. **Hidden drift.** Normalization can hide model drift; a counter and a warning log keep it visible.
  2. **Lost hypotheses.** Truncating to 3 could drop a valid lower-ranked hypothesis; that is the existing contract, now enforced instead of rejected.
  3. **Bad garbled recovery.** Dropping garbled items may recover a reply whose remaining fields are poor; the judge still reviews it.
  4. **Step 2 is unverified:** NIM support and latency must be checked before relying on it.

### P4. Retrieve runbook verification sections for the recommender
```diff
# src/rag/hybrid_retriever.py
-    "recommender": ["diagnostic-checks", "corrective-actions", "escalation-criteria"],
+    "recommender": ["diagnostic-checks", "corrective-actions", "verification", "escalation-criteria"],

# src/agents/graph.py (gather_evidence)
-    out["kb_recommender"] = tools.search_runbook(c, text, cats, role="recommender", k=4)
+    out["kb_recommender"] = tools.search_runbook(c, text, cats, role="recommender", k=5)
```
- **Expected benefit:** each action's "Verify" step can cite a runbook verification section instead of being written by the model unsupported. In Phase 11 no verification sentence of a reference answer was ever supported by the retrieved evidence.
- **Risks:**
  1. **More tokens.** One more runbook chunk is about 150–250 extra input tokens per recommender call. The runbook budget in the evidence pack is 1,000 tokens, so the lowest-ranked chunk (possibly escalation criteria) could be dropped when chunks are long.
  2. **Retrieval and output change.** This is a retrieval change, so KB retrieval, the classifier-to-retrieval path and the 11-query end-to-end set must be re-run. With no prompt change, the recommender may still not cite the verification section consistently.

**Suggested order if approved:** P1 and P3-step-1 first (small, local, with a direct reliability gain). Then P2, re-running the seeded-error test and the end-to-end set. Then P4. Then one end-to-end re-run to measure everything together against this Phase 11 baseline.

## Files added in this follow-up (evaluation only)

| Path | Contents |
|---|---|
| `evaluation/review_spot_check.py`, `components/manual_spot_check_review.csv` / `.json` | Spot-check review |
| `evaluation/run_deepeval_rescore.py`, `deepeval_v2/` | Corrected scoring input and re-scored results |
| `tests/test_evaluation_scoring.py` | Corrected input contains every returned case; original answer kept; annotations preserved |
| `../runs/phase11_baseline_v1/` | Baseline snapshot and checksums |
