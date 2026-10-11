"""Review the AI-annotated manual relevance spot check without modifying it (Phase 11 follow-up).

Reads components/manual_spot_check.csv (read-only; the relevant_y_n and notes columns were filled by a separate AI)
and writes components/manual_spot_check_review.csv next to it: for every row, the dataset's symptom flags for the
query's expected symptoms, agreement with the AI label, and a flag for rows a person should review.
Run from the repo root:  python -m evaluation.review_spot_check
"""
import json

import pandas as pd

from src.utils.config import PROJECT_ROOT, get_settings

COMP = PROJECT_ROOT / "evaluation" / "results" / "final" / "components"
GOLDEN = PROJECT_ROOT / "tests" / "test_cases" / "golden_queries.json"
SUMMARY_KPIS_SHOWN = 4  # case summaries list at most this many abnormal KPIs (documents.build_case_summary)


def main() -> None:
    sheet = pd.read_csv(COMP / "manual_spot_check.csv")  # read-only
    golden = {q["id"]: q for q in json.loads(GOLDEN.read_text(encoding="utf-8"))}
    cases = pd.read_parquet(get_settings().artifacts_dir / "processed" / "cases.parquet").set_index("case_id")
    rows = []
    for _, r in sheet.iterrows():
        exp = golden[r.query_id]["expected_symptoms"]
        row = cases.loc[r.case_id]
        missing = [s for s in exp if not row[f"sym_{s}"]]
        n_abnormal = int(sum(row[c] for c in cases.columns if c.startswith("sym_")))
        data_rel = "yes" if not missing else "no"
        ai = str(r.relevant_y_n).strip().lower()
        agree = ai == data_rel
        reasons = []
        if not agree:
            reasons.append("AI label disagrees with the dataset symptom flags")
            if n_abnormal > SUMMARY_KPIS_SHOWN:
                reasons.append(f"the case has {n_abnormal} abnormal KPIs but its summary shows only {SUMMARY_KPIS_SHOWN}, "
                               "so a symptom the annotator looked for can be absent from the text it read")
        if r.auto_symptom_overlap < 0.5 and ai == "yes":
            reasons.append("low automatic symptom overlap (Jaccard): the case also has many unrelated abnormal KPIs")
        rows.append({"query_id": r.query_id, "rank": r["rank"], "case_id": r.case_id, "ai_label": ai,
                     "ai_notes": r.notes, "data_has_all_expected_symptoms": data_rel, "missing_expected": ",".join(missing),
                     "abnormal_kpis_in_case": n_abnormal, "auto_symptom_overlap": r.auto_symptom_overlap,
                     "agrees": agree, "flag_for_review": bool(reasons), "flag_reason": "; ".join(reasons)})
    out = pd.DataFrame(rows)
    out.to_csv(COMP / "manual_spot_check_review.csv", index=False)
    summary = {"rows": len(out), "ai_relevant": int((out.ai_label == "yes").sum()),
               "data_relevant": int((out.data_has_all_expected_symptoms == "yes").sum()),
               "agreement": round(float(out.agrees.mean()), 3), "flagged": int(out.flag_for_review.sum()),
               "ai_precision_at_5": round(float((out.ai_label == "yes").mean()), 3),
               "data_precision_at_5": round(float((out.data_has_all_expected_symptoms == "yes").mean()), 3)}
    (COMP / "manual_spot_check_review.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(out[out.flag_for_review][["query_id", "rank", "case_id", "ai_label", "data_has_all_expected_symptoms",
                                    "flag_reason"]].to_string(index=False))


if __name__ == "__main__":
    main()
