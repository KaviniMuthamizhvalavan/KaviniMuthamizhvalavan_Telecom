"""KPI assessment shared by offline labelling and runtime analysis (plan §6.2, §6.4).

Severity is relative to the dataset (plan C7): for each KPI, "degraded" means worse than p75
(p25 for lower-is-worse KPIs) and "critical" worse than p90 (p10). Percentiles use a mid-rank on a
1001-point quantile table, so ties (e.g. 50% of call-drop rates are 0) are not overstated.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.schema import (ADVERSE_WEATHER, CATEGORIES, KPI_SPECS, NORMAL, NUMERIC_COLUMNS, SEVERITY_KPIS,
                              SYMPTOMS)

QUANTILE_POINTS = np.linspace(0.0, 1.0, 1001)
SUMMARY_QUANTILES = {"p5": 0.05, "p10": 0.10, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p90": 0.90, "p95": 0.95}
BAND_NAMES = {0: "normal", 1: "degraded", 2: "critical"}
CATEGORY_LIST = list(CATEGORIES)
_SYMPTOM_BY_KPI = {s.kpi: s.code for s in SYMPTOMS.values()}


@dataclass
class Baselines:
    n_records: int
    dataset_sha256: str
    quantiles: dict[str, dict[str, float]]  # kpi -> p5..p95 (+ min, max)
    tables: dict[str, list[float]]  # kpi -> 1001-point quantile table
    thresholds: dict[str, dict[str, float]]  # severity kpi -> {"degraded", "critical"} on the bad side
    vocab: dict[str, dict[str, int]]  # state/season/weather -> value counts
    priority: dict = field(default_factory=dict)  # filled in Phase 4 (calibrated thresholds)

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self)), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> "Baselines":
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    def median(self, kpi: str) -> float:
        return self.quantiles[kpi]["p50"]


def compute_baselines(df: pd.DataFrame, dataset_sha256: str = "") -> Baselines:
    quantiles, tables, thresholds = {}, {}, {}
    for kpi in NUMERIC_COLUMNS:
        x = df[kpi].to_numpy(dtype=float)
        q = {name: float(np.quantile(x, p)) for name, p in SUMMARY_QUANTILES.items()}
        q.update(min=float(x.min()), max=float(x.max()))
        quantiles[kpi] = q
        tables[kpi] = np.quantile(x, QUANTILE_POINTS).round(6).tolist()
        direction = KPI_SPECS[kpi].direction
        if direction > 0:
            thresholds[kpi] = {"degraded": q["p75"], "critical": q["p90"]}
        elif direction < 0:
            thresholds[kpi] = {"degraded": q["p25"], "critical": q["p10"]}
    vocab = {col: df[col].value_counts().to_dict() for col in ("state", "season", "weather")}
    return Baselines(len(df), dataset_sha256, quantiles, tables, thresholds, vocab)


def percentile_rank(values: np.ndarray, table: list[float]) -> np.ndarray:
    """Mid-rank position of each value in the quantile table, in [0, 1]."""
    t = np.asarray(table)
    lo = np.searchsorted(t, values, side="left")
    hi = np.searchsorted(t, values, side="right")
    return ((lo + hi) / 2.0) / len(t)


def severity(values: np.ndarray, kpi: str, b: Baselines) -> np.ndarray:
    th, direction = b.thresholds[kpi], KPI_SPECS[kpi].direction
    if direction > 0:
        return np.where(values >= th["critical"], 2, np.where(values >= th["degraded"], 1, 0)).astype(np.int8)
    return np.where(values <= th["critical"], 2, np.where(values <= th["degraded"], 1, 0)).astype(np.int8)


def assess_frame(df: pd.DataFrame, b: Baselines) -> pd.DataFrame:
    """Vectorized assessment. `df` needs the 19 severity KPIs, temperature_c, humidity_pct and weather."""
    out = pd.DataFrame(index=df.index)
    for kpi in SEVERITY_KPIS:
        x = df[kpi].to_numpy(dtype=float)
        pct = percentile_rank(x, b.tables[kpi])
        out[f"pct_{kpi}"] = pct.astype(np.float32)
        out[f"bad_{kpi}"] = (pct if KPI_SPECS[kpi].direction > 0 else 1.0 - pct).astype(np.float32)
        out[f"sev_{kpi}"] = severity(x, kpi, b)
        out[f"sym_{_SYMPTOM_BY_KPI[kpi]}"] = out[f"sev_{kpi}"] > 0

    sev_cols = [f"sev_{k}" for k in SEVERITY_KPIS]
    out["n_anomalies"] = (out[sev_cols] > 0).sum(axis=1).astype(np.int16)
    out["n_critical"] = (out[sev_cols] == 2).sum(axis=1).astype(np.int16)

    temp_q, hum_q = b.quantiles["temperature_c"], b.quantiles["humidity_pct"]
    out["env_adverse_weather"] = df["weather"].isin(ADVERSE_WEATHER).to_numpy()
    out["env_extreme_temperature"] = ((df["temperature_c"] <= temp_q["p5"]) | (df["temperature_c"] >= temp_q["p95"])).to_numpy()
    out["env_high_humidity"] = (df["humidity_pct"] >= hum_q["p90"]).to_numpy()

    # Category scores: sum of severities / sqrt(#signature symptoms) (validated on 100k: 9.5-15% per category).
    sev_by_sym = {_SYMPTOM_BY_KPI[k]: out[f"sev_{k}"].to_numpy(dtype=float) for k in SEVERITY_KPIS}
    bad_by_sym = {_SYMPTOM_BY_KPI[k]: out[f"bad_{k}"].to_numpy(dtype=float) for k in SEVERITY_KPIS}
    scores = np.column_stack([sum(sev_by_sym[s] for s in c.symptoms) / np.sqrt(len(c.symptoms))
                              for c in CATEGORIES.values()])
    tiebreak = np.column_stack([np.max([bad_by_sym[s] for s in c.symptoms], axis=0) for c in CATEGORIES.values()])
    for j, code in enumerate(CATEGORY_LIST):
        out[f"score_{code}"] = scores[:, j].astype(np.float32)

    best = scores.max(axis=1)
    # Rank key: score first, then the most extreme KPI in the category (tie-break).
    key = scores * 10.0 + tiebreak
    order = np.argsort(-key, axis=1)
    cats = np.array(CATEGORY_LIST)
    primary = np.where(best > 0, cats[order[:, 0]], NORMAL)
    sec1 = np.where(scores[np.arange(len(scores)), order[:, 1]] > 0, cats[order[:, 1]], "")
    sec2 = np.where(scores[np.arange(len(scores)), order[:, 2]] > 0, cats[order[:, 2]], "")
    out["primary_category"] = primary
    out["secondary_1"] = np.where(best > 0, sec1, "")
    out["secondary_2"] = np.where(best > 0, sec2, "")
    return out


def assess(kpis: dict, b: Baselines) -> dict:
    """Assess one KPI snapshot (partial allowed). Missing numeric KPIs are imputed with dataset medians."""
    row, imputed = {}, []
    for kpi in NUMERIC_COLUMNS:
        value = kpis.get(kpi)
        if value is None:
            value = b.median(kpi)
            imputed.append(kpi)
        row[kpi] = float(value)
    row["weather"] = kpis.get("weather") or ""
    a = assess_frame(pd.DataFrame([row]), b).iloc[0]

    per_kpi = []
    for kpi in SEVERITY_KPIS:
        spec = KPI_SPECS[kpi]
        per_kpi.append({
            "kpi": kpi, "label": spec.label, "unit": spec.unit, "value": row[kpi],
            "percentile": round(float(a[f"pct_{kpi}"]), 4), "worse_than_pct": round(float(a[f"bad_{kpi}"]) * 100, 1),
            "band": BAND_NAMES[int(a[f"sev_{kpi}"])], "imputed": kpi in imputed,
        })
    anomalies = sorted((p for p in per_kpi if p["band"] != "normal" and not p["imputed"]),
                       key=lambda p: (p["band"] != "critical", -p["worse_than_pct"]))
    return {
        "per_kpi": per_kpi,
        "anomalies": anomalies,
        "symptoms": [_SYMPTOM_BY_KPI[p["kpi"]] for p in anomalies],
        "env_tags": [t for t in ("adverse_weather", "extreme_temperature", "high_humidity") if bool(a[f"env_{t}"])],
        "category_scores": {c: round(float(a[f"score_{c}"]), 3) for c in CATEGORY_LIST},
        "primary_category": a["primary_category"],
        "secondary_categories": [c for c in (a["secondary_1"], a["secondary_2"]) if c],
        "imputed_fields": imputed,
    }


def profile_from_cases(cases: pd.DataFrame) -> dict:
    """Median KPI profile of a set of cases (used when a query has no KPI values)."""
    return {kpi: float(cases[kpi].median()) for kpi in NUMERIC_COLUMNS}
