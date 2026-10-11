"""Segment statistics for contributing-factor analysis (plan §6.2, analyst tool `segment_stats`).

Compares a segment of historical cases (selected by a boolean mask from filters/symptoms) with the
whole corpus. Lift = P(flag | segment) / P(flag | corpus): co-occurrence, not causation.
"""
import numpy as np
import pandas as pd

from src.utils.schema import PRIORITIES, SEVERITY_KPIS, SYMPTOMS

ENV_TAGS = ["env_adverse_weather", "env_extreme_temperature", "env_high_humidity"]


def segment_stats(cases: pd.DataFrame, mask: np.ndarray, compare_by: str | None = None,
                  exclude_symptoms: tuple[str, ...] = (), top_n: int = 8) -> dict:
    seg = cases.loc[mask]
    n = len(seg)
    result = {"count": n, "share_of_corpus": round(n / len(cases), 4)}
    if n == 0:
        return result

    lifts = []
    for code in SYMPTOMS:
        if code in exclude_symptoms:
            continue
        base = cases[f"sym_{code}"].mean()
        rate = seg[f"sym_{code}"].mean()
        lifts.append({"factor": code, "segment_rate": round(float(rate), 3), "corpus_rate": round(float(base), 3),
                      "lift": round(float(rate / base), 2) if base else None})
    for tag in ENV_TAGS:
        base, rate = cases[tag].mean(), seg[tag].mean()
        lifts.append({"factor": tag.removeprefix("env_"), "segment_rate": round(float(rate), 3),
                      "corpus_rate": round(float(base), 3), "lift": round(float(rate / base), 2) if base else None})
    for w in sorted(cases["weather"].unique()):
        base, rate = (cases["weather"] == w).mean(), (seg["weather"] == w).mean()
        lifts.append({"factor": f"weather={w}", "segment_rate": round(float(rate), 3),
                      "corpus_rate": round(float(base), 3), "lift": round(float(rate / base), 2)})
    lifts.sort(key=lambda d: -(d["lift"] or 0))
    result["top_lifts"] = lifts[:top_n]

    medians = []
    for kpi in SEVERITY_KPIS:
        s_med, c_med = float(seg[kpi].median()), float(cases[kpi].median())
        spread = float(cases[kpi].std()) or 1.0
        medians.append({"kpi": kpi, "segment_median": round(s_med, 2), "corpus_median": round(c_med, 2),
                        "shift_in_std": round((s_med - c_med) / spread, 2)})
    medians.sort(key=lambda d: -abs(d["shift_in_std"]))
    result["kpi_medians"] = medians[:top_n]

    if "priority" in seg:
        mix = seg["priority"].value_counts(normalize=True)
        result["priority_mix"] = {p: round(float(mix.get(p, 0.0)), 3) for p in PRIORITIES}
    result["median_fault_rate"] = round(float(seg["fault_occurrence_rate_pct"].median()), 2)
    result["primary_category_mix"] = {k: round(float(v), 3) for k, v in
                                      seg["primary_category"].value_counts(normalize=True).head(5).items()}
    if compare_by:
        grp = seg.groupby(compare_by)
        result[f"by_{compare_by}"] = {str(k): {"count": int(len(g)),
                                               "median_fault_rate": round(float(g["fault_occurrence_rate_pct"].median()), 2)}
                                      for k, g in grp}
    return result
