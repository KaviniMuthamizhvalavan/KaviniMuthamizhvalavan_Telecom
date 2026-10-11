"""Classifier evaluation: LLM agent vs the rule baseline on the golden queries (plan §11.4, Phase 6 verify).

Run from the repo root:  python -m evaluation.run_classification_eval [--rules-only] [--no-cache]
Metrics per system:
- primary_acc: primary_category == expected_primary (queries with an expected category)
- primary_acc_lenient: primary in expected + acceptable_primary
- symptom precision / recall / F1 (micro), filter exact match
- vague handling: G21-style queries (no expected category, in scope) -> needs_clarification
- out-of-scope: in_scope == False for off-topic queries (classifier only; guardrails normally block first)
Uses the runtime LLM API (one call per query, cached after the first run). Never run during a demo (shared RPM).
"""
import argparse
import json
import time

import pandas as pd

from src.agents.classifier_agent import classify, rule_classify
from src.services.llm_client import LLMClient
from src.utils.config import PROJECT_ROOT, get_settings
from src.utils.net import use_system_certificates

GOLDEN = PROJECT_ROOT / "tests" / "test_cases" / "golden_queries.json"
OUT = PROJECT_ROOT / "evaluation" / "results" / "final" / "classification"


def score(system: str, q: dict, c, latency_ms: float, degraded: bool) -> dict:
    exp_syms, got_syms = set(q["expected_symptoms"]), set(c.symptoms)
    exp_f = {k: sorted(v) for k, v in q["expected_filters"].items() if v and k in ("state", "season", "weather")}
    got_f = {k: sorted(v) for k, v in c.filters.model_dump().items() if v and k in ("state", "season", "weather")}
    return {"system": system, "query_id": q["id"], "expected": q["expected_primary"], "predicted": c.primary_category,
            "correct": q["expected_primary"] is not None and c.primary_category == q["expected_primary"],
            "correct_lenient": q["expected_primary"] is not None and
            c.primary_category in [q["expected_primary"], *q["acceptable_primary"]],
            "tp": len(exp_syms & got_syms), "fp": len(got_syms - exp_syms), "fn": len(exp_syms - got_syms),
            "filters_exact": exp_f == got_f, "needs_clarification": c.needs_clarification, "in_scope": c.in_scope,
            "confidence": c.confidence, "degraded": degraded, "latency_ms": round(latency_ms, 1)}


def summarize(df: pd.DataFrame, queries: list[dict]) -> pd.DataFrame:
    labelled = {q["id"] for q in queries if q["expected_primary"]}
    vague = {q["id"] for q in queries if not q["expected_primary"] and q["in_scope"]}
    off = {q["id"] for q in queries if not q["in_scope"]}
    rows = []
    for system, g in df.groupby("system", sort=False):
        lab = g[g.query_id.isin(labelled)]
        tp, fp, fn = lab.tp.sum(), lab.fp.sum(), lab.fn.sum()
        p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        rows.append({"system": system, "n": len(lab), "primary_acc": lab.correct.mean(),
                     "primary_acc_lenient": lab.correct_lenient.mean(), "symptom_precision": p, "symptom_recall": r,
                     "symptom_f1": 2 * p * r / max(p + r, 1e-9), "filters_exact": lab.filters_exact.mean(),
                     "vague_clarified": g[g.query_id.isin(vague)].needs_clarification.mean(),
                     "off_topic_flagged": (~g[g.query_id.isin(off)].in_scope).mean(),
                     "degraded_rate": g.degraded.mean(), "latency_p50_ms": g.latency_ms.median(),
                     "latency_p95_ms": g.latency_ms.quantile(0.95)})
    return pd.DataFrame(rows).set_index("system").round(3)


def per_class_report(df: pd.DataFrame, queries: list[dict]) -> dict:
    """Macro-F1, per-class precision/recall/F1 and the confusion matrix per system (plan §11.4)."""
    from sklearn.metrics import classification_report, confusion_matrix, f1_score
    labelled = {q["id"] for q in queries if q["expected_primary"]}
    out = {}
    for system, g in df.groupby("system", sort=False):
        lab = g[g.query_id.isin(labelled)]
        labels = sorted(set(lab.expected) | set(lab.predicted))
        out[system] = {"macro_f1": round(float(f1_score(lab.expected, lab.predicted, average="macro", zero_division=0)), 3),
                       "per_class": classification_report(lab.expected, lab.predicted, labels=labels, zero_division=0,
                                                          output_dict=True),
                       "confusion_matrix": {"labels": labels,
                                            "matrix": confusion_matrix(lab.expected, lab.predicted, labels=labels).tolist()},
                       "errors": lab[~lab.correct][["query_id", "expected", "predicted"]].to_dict("records")}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    use_system_certificates()
    s = get_settings()
    if args.no_cache:
        s = s.model_copy(update={"llm_cache_enabled": False})
    queries = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rows = []
    for q in queries:
        t = time.perf_counter()
        rows.append(score("rules", q, rule_classify(q["query"]), (time.perf_counter() - t) * 1000, True))
    usage = None
    if not args.rules_only:
        llm = LLMClient(s, cache_path=s.artifacts_dir / "llm_cache.db")
        if not llm.available:
            raise SystemExit("No LLM configured; use --rules-only")
        usage = llm.new_usage()
        usage.max_calls, usage.max_tokens = 10_000, 10_000_000
        for q in queries:
            t = time.perf_counter()
            c, _, degraded = classify(llm, q["query"], None, usage)
            rows.append(score(f"llm:{llm.model}", q, c, (time.perf_counter() - t) * 1000, degraded))
            print(f"{q['id']} {c.primary_category:20} conf={c.confidence:.2f} clarify={c.needs_clarification} "
                  f"in_scope={c.in_scope} {'DEGRADED' if degraded else ''}")
    df = pd.DataFrame(rows)
    summary = summarize(df, queries)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "classification_per_query.csv", index=False)
    summary.to_csv(OUT / "classification_metrics.csv")
    (OUT / "classification_report.json").write_text(json.dumps(per_class_report(df, queries), indent=2),
                                                    encoding="utf-8")
    info = {"queries": len(queries), "prompt_version": "classifier_v1", "model": s.runtime_model,
            "reasoning": s.llm_reasoning, "usage": usage.summary() if usage else None}
    (OUT / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(summary.T.to_string())
    if usage:
        print("usage:", usage.summary())


if __name__ == "__main__":
    main()
