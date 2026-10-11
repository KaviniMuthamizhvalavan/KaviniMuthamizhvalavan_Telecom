"""Case narratives, compact summaries and vector-store metadata (plan §7.2, §7.5).

Narratives describe only abnormal KPIs (severity word, value, percentile, synonyms), so keyword
search gets meaningful IDF and dense vectors focus on the symptom combination.
"""
import pandas as pd

from src.utils.schema import CATEGORIES, KPI_SPECS, NARRATIVE_TEMPLATE_VERSION, NUMERIC_COLUMNS, SEVERITY_KPIS, SYMPTOMS

_SYM_BY_KPI = {s.kpi: s for s in SYMPTOMS.values()}
_FIELDS_STR = ("state", "city_lc", "season", "weather", "primary_category", "secondary_1", "secondary_2",
               "priority", "fault_risk_band")


def category_name(code: str) -> str:
    return CATEGORIES[code].name if code in CATEGORIES else "No significant degradation"


def _fmt(value: float, unit: str) -> str:
    if unit in ("users", "alarms", "changes", "incidents", "failures"):
        return f"{value:,.0f} {unit}" if value != int(value) or unit == "users" else f"{int(value)} {unit}"
    if unit == "%":
        return f"{value:.1f}%"
    return f"{value:,.1f} {unit}"


def anomalies(row) -> list[dict]:
    """Abnormal KPIs of one case, most severe first."""
    out = []
    for kpi in SEVERITY_KPIS:
        sev = int(row[f"sev_{kpi}"])
        if sev:
            spec = KPI_SPECS[kpi]
            out.append({"kpi": kpi, "label": spec.label, "value": float(row[kpi]), "unit": spec.unit,
                        "band": "critical" if sev == 2 else "degraded",
                        "percentile": round(float(row[f"bad_{kpi}"]), 4)})
    return sorted(out, key=lambda a: (a["band"] != "critical", -a["percentile"]))


def _phrase(a: dict) -> str:
    sym = _SYM_BY_KPI[a["kpi"]]
    pct = min(a["percentile"] * 100, 99.0)  # values beyond the observed range would read "worse than 100%"
    return (f"{sym.label} {_fmt(a['value'], a['unit'])} (worse than {pct:.0f}% of records; "
            f"{', '.join(sym.synonyms[:2])})")


def build_case_text(row) -> str:
    """Narrative used for embeddings and BM25 (template NARRATIVE_TEMPLATE_VERSION)."""
    an = anomalies(row)
    crit = [_phrase(a) for a in an if a["band"] == "critical"]
    deg = [_phrase(a) for a in an if a["band"] == "degraded"]
    parts = [f"{row['case_id']}, {row['state']}, {row['season']}, {row['weather']}, {row['temperature_c']:.1f} C."]
    if crit:
        parts.append("Critical: " + "; ".join(crit) + ".")
    if deg:
        parts.append("Degraded: " + "; ".join(deg) + ".")
    if not an:
        parts.append("All KPIs within normal range.")
    secondaries = [category_name(c) for c in (row["secondary_1"], row["secondary_2"]) if c]
    parts.append(f"Primary issue: {category_name(row['primary_category'])}"
                 + (f"; secondary: {', '.join(secondaries)}." if secondaries else "."))
    parts.append(f"Load {row['user_count']:,.0f} users, {row['data_usage_gb']:.1f} GB. "
                 f"Fault occurrence rate {row['fault_occurrence_rate_pct']:.1f}%. "
                 f"Fault risk {row['fault_risk_band']}. Priority {row['priority']}.")
    return " ".join(parts)


def build_case_summary(row, max_anomalies: int = 4) -> str:
    """Compact one-line summary for LLM context (about 40-80 tokens)."""
    an = anomalies(row)[:max_anomalies]
    kp = ", ".join(f"{a['label'].lower()} {_fmt(a['value'], a['unit'])} ({'crit' if a['band'] == 'critical' else 'deg'})"
                   for a in an) or "no abnormal KPIs"
    sec = "+" + row["secondary_1"] if row["secondary_1"] else ""
    return (f"[{row['case_id']}] {row['state']}/{row['season']}/{row['weather']}, {row['priority']}, "
            f"{row['primary_category']}{sec}: {kp}; fault rate {row['fault_occurrence_rate_pct']:.1f}%")


def build_case_metadata(row) -> dict:
    """Chroma metadata: scalars only, never None (plan §7.5)."""
    meta = {f: str(row[f]) for f in _FIELDS_STR}
    meta["priority_score"] = float(row["priority_score"])
    meta["fault_risk_prob"] = float(row["fault_risk_prob"])
    meta["n_anomalies"] = int(row["n_anomalies"])
    meta["n_critical"] = int(row["n_critical"])
    meta["issue_reported"] = bool(row["issue_reported"])
    for code in SYMPTOMS:
        meta[f"sym_{code}"] = bool(row[f"sym_{code}"])
    for kpi in NUMERIC_COLUMNS:
        meta[kpi] = float(row[kpi])
    return meta


def build_documents(cases: pd.DataFrame) -> tuple[list[str], list[str], list[dict]]:
    ids, texts, metas = [], [], []
    for row in cases.to_dict("records"):
        ids.append(row["case_id"])
        texts.append(build_case_text(row))
        metas.append(build_case_metadata(row))
    return ids, texts, metas


TEMPLATE_VERSION = NARRATIVE_TEMPLATE_VERSION
