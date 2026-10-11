"""Guardrail evaluation (plan §11.4, Phase 6 verify: block >= 90% of attacks/off-topic, <= 5% false positives).

Run from the repo root:  python -m evaluation.run_guardrail_eval
Positives (should be blocked): guardrail_cases with expect != ALLOW, plus off-topic golden queries.
Negatives (must pass): ALLOW guardrail cases plus every in-scope golden query.
No LLM is used. The "uncertain" band counts as passed here (the classifier decides it at runtime).
"""
import json

import pandas as pd

from src.rag.embeddings import Embedder
from src.services.guardrails import IN_SCOPE_MIN, OUT_OF_SCOPE_MAX, GuardrailError, Guardrails
from src.utils.config import PROJECT_ROOT, get_settings
from src.utils.net import use_system_certificates

CASES = PROJECT_ROOT / "tests" / "test_cases"
OUT = PROJECT_ROOT / "evaluation" / "results" / "final" / "guardrails"


def main() -> None:
    use_system_certificates()
    guard = Guardrails(Embedder(get_settings().embedding_model))
    items = [{"id": c["id"], "kind": c["kind"], "query": c["query"], "expect": c["expect"]}
             for c in json.loads((CASES / "guardrail_cases.json").read_text(encoding="utf-8"))]
    items += [{"id": q["id"], "kind": "golden" if q["in_scope"] else "off_topic", "query": q["query"],
               "expect": "ALLOW" if q["in_scope"] else "OUT_OF_SCOPE"}
              for q in json.loads((CASES / "golden_queries.json").read_text(encoding="utf-8"))]
    rows = []
    for it in items:
        try:
            r = guard.check(it["query"])
            got, rel, band = "ALLOW", r.relevance, r.band
        except GuardrailError as exc:
            got, rel, band = exc.code, exc.details.get("relevance"), "blocked"
        rows.append({**it, "got": got, "band": band, "relevance": rel, "correct": got == it["expect"]})
    df = pd.DataFrame(rows)
    pos, neg = df[df.expect != "ALLOW"], df[df.expect == "ALLOW"]
    summary = {"blocked_rate": round(float((pos.got != "ALLOW").mean()), 3),
               "exact_code_rate": round(float(pos.correct.mean()), 3),
               "false_positive_rate": round(float((neg.got != "ALLOW").mean()), 3),
               "uncertain_band_negatives": int((neg.band == "uncertain").sum()),
               "n_positive": len(pos), "n_negative": len(neg),
               "thresholds": {"in_scope_min": IN_SCOPE_MIN, "out_of_scope_max": OUT_OF_SCOPE_MAX},
               "by_kind": df.groupby("kind").correct.mean().round(3).to_dict()}
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "guardrail_per_case.csv", index=False)
    (OUT / "guardrail_metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(df[~df.correct][["id", "kind", "expect", "got", "relevance"]].to_string() if (~df.correct).any()
          else "all cases correct")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
