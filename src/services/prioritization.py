"""Deterministic incident prioritization P1-P4 (plan §6.4c).

score = 0.4 * severity + 0.3 * impact + 0.3 * risk, with escalation overrides (at least P2).
Severity and impact are corpus percentiles; level thresholds are corpus quantiles (P1 top 5%,
P2 next 20%, P3 next 40%, P4 the rest), calibrated once offline and stored in baselines.json so
runtime decisions match the historical labels.
"""
import numpy as np
import pandas as pd

from src.services.kpi_analyzer import Baselines, percentile_rank
from src.utils.schema import KPI_SPECS, SEVERITY_KPIS

WEIGHTS = {"severity": 0.4, "impact": 0.3, "risk": 0.3}
SERVICE_WEIGHT = 1.5
LEVEL_QUANTILES = {"P1": 0.95, "P2": 0.75, "P3": 0.35}
LEVEL_NAMES = {"P1": "Critical", "P2": "High", "P3": "Medium", "P4": "Low"}
OVERRIDES = {
    "critical availability": ["cell_availability_pct"],
    "critical alarms and fault rate": ["critical_alarm_count", "fault_occurrence_rate_pct"],
    "security incidents and authentication failures": ["security_incidents", "auth_failures"],
}


def raw_severity(sev: pd.DataFrame) -> np.ndarray:
    """Weighted band sum. `sev` has columns sev_<kpi> with values 0/1/2."""
    w = np.array([SERVICE_WEIGHT if KPI_SPECS[k].service_affecting else 1.0 for k in SEVERITY_KPIS])
    return sev[[f"sev_{k}" for k in SEVERITY_KPIS]].to_numpy(dtype=float) @ w


TARGET_MIX = {"P1": 0.05, "P2": 0.20, "P3": 0.40}  # P4 = remainder (about 35%)


def override_mask(cases: pd.DataFrame) -> np.ndarray:
    mask = np.zeros(len(cases), dtype=bool)
    for kpis in OVERRIDES.values():
        mask |= np.all([cases[f"sev_{k}"].to_numpy() == 2 for k in kpis], axis=0)
    return mask


def calibrate(cases: pd.DataFrame, risk: np.ndarray, b: Baselines) -> dict:
    """Compute the severity table and level thresholds from the corpus (offline, once).

    Thresholds are chosen *after* accounting for escalation overrides, so the final mix matches
    TARGET_MIX (overrides alone lift about 15% of cases, which plain quantiles would push into P2).
    """
    raw = raw_severity(cases)
    sev_table = np.quantile(raw, np.linspace(0, 1, 1001)).round(6).tolist()
    severity = percentile_rank(raw, sev_table)
    score = WEIGHTS["severity"] * severity + WEIGHTS["impact"] * impact_score(cases, b) + WEIGHTS["risk"] * risk
    ov = override_mask(cases)
    t1 = float(np.quantile(score, 1 - TARGET_MIX["P1"]))
    grid = np.quantile(score, np.linspace(0, 1, 4001))
    p2_share = [np.mean((score < t1) & ((score >= t) | ov)) for t in grid]
    t2 = float(grid[int(np.argmin(np.abs(np.array(p2_share) - TARGET_MIX["P2"])))])
    p3_share = [np.mean((score >= t) & (score < t2) & ~ov) for t in grid]
    t3 = float(grid[int(np.argmin(np.abs(np.array(p3_share) - TARGET_MIX["P3"])))])
    return {"severity_table": sev_table, "level_thresholds": {"P1": t1, "P2": t2, "P3": t3},
            "target_mix": TARGET_MIX, "weights": WEIGHTS, "service_weight": SERVICE_WEIGHT}


def impact_score(df: pd.DataFrame, b: Baselines | None = None, tables: dict | None = None) -> np.ndarray:
    """Mean of the user-count and data-usage percentiles (blast radius)."""
    if b is not None:
        tables = b.tables
    if tables is None:
        return (df["user_count"].rank(pct=True).to_numpy() + df["data_usage_gb"].rank(pct=True).to_numpy()) / 2
    return (percentile_rank(df["user_count"].to_numpy(float), tables["user_count"])
            + percentile_rank(df["data_usage_gb"].to_numpy(float), tables["data_usage_gb"])) / 2


def prioritize_frame(cases: pd.DataFrame, risk: np.ndarray, b: Baselines) -> pd.DataFrame:
    """Vectorized priority for assessed cases (needs sev_* columns, user_count, data_usage_gb)."""
    cfg = b.priority
    severity = percentile_rank(raw_severity(cases), cfg["severity_table"])
    impact = impact_score(cases, b)
    score = WEIGHTS["severity"] * severity + WEIGHTS["impact"] * impact + WEIGHTS["risk"] * risk
    th = cfg["level_thresholds"]
    level = np.where(score >= th["P1"], "P1", np.where(score >= th["P2"], "P2", np.where(score >= th["P3"], "P3", "P4")))
    override_any = override_mask(cases)
    level = np.where(override_any & np.isin(level, ["P3", "P4"]), "P2", level)
    return pd.DataFrame({"priority": level, "priority_score": score.astype(np.float32),
                         "severity_score": severity.astype(np.float32), "impact_score": impact.astype(np.float32),
                         "priority_override": override_any}, index=cases.index)


def finalize_cases(artifacts_dir) -> pd.DataFrame:
    """Offline step (Phase 4): merge out-of-fold risk, calibrate thresholds, label every case with priority.

    Rewrites artifacts/processed/cases.parquet and stores the calibration in baselines.json.
    """
    cases_path = artifacts_dir / "processed" / "cases.parquet"
    cases = pd.read_parquet(cases_path)
    for col in ("fault_risk_prob", "fault_risk_band", "priority", "priority_score", "severity_score",
                "impact_score", "priority_override"):
        cases = cases.drop(columns=col, errors="ignore")  # idempotent re-runs
    oof = pd.read_parquet(artifacts_dir / "processed" / "fault_risk_oof.parquet")
    cases = cases.merge(oof, on="case_id", how="left", validate="one_to_one")
    if cases["fault_risk_prob"].isna().any():
        raise ValueError("missing out-of-fold risk for some cases; re-run python -m src.services.ml.train")
    b = Baselines.from_json(artifacts_dir / "baselines.json")
    risk = cases["fault_risk_prob"].to_numpy(dtype=float)
    b.priority = calibrate(cases, risk, b)
    cases = pd.concat([cases, prioritize_frame(cases, risk, b)], axis=1)
    cases.to_parquet(cases_path, index=False)
    b.to_json(artifacts_dir / "baselines.json")
    return cases


BAND_TO_SEV = {"normal": 0, "degraded": 1, "critical": 2}


def prioritize(assessment: dict, risk_prob: float, b: Baselines) -> dict:
    """Priority for one assessed snapshot (output of kpi_analyzer.assess, which already imputes medians)."""
    sev_row = {f"sev_{p['kpi']}": BAND_TO_SEV[p["band"]] for p in assessment["per_kpi"]}
    kpis = {p["kpi"]: p["value"] for p in assessment["per_kpi"]}
    row = pd.DataFrame([{**sev_row, "user_count": kpis["user_count"], "data_usage_gb": kpis["data_usage_gb"]}])
    r = prioritize_frame(row, np.array([risk_prob]), b).iloc[0]
    overrides = [name for name, ks in OVERRIDES.items() if all(sev_row[f"sev_{k}"] == 2 for k in ks)]
    reasons = []
    for a in assessment["anomalies"][:3]:
        reasons.append(f"{a['band'].capitalize()} {a['label'].lower()}: {a['value']:g} {a['unit']} "
                       f"(worse than {a['worse_than_pct']:.0f}% of records)")
    users_pct = percentile_rank(np.array([kpis["user_count"]]), b.tables["user_count"])[0] * 100
    reasons.append(f"Serves {kpis['user_count']:,.0f} users (more than {users_pct:.0f}% of records)")
    reasons.append(f"Fault risk {risk_prob:.0%}")
    reasons += [f"Escalated to at least P2: {o}" for o in overrides]
    return {"level": r["priority"], "label": LEVEL_NAMES[r["priority"]], "score": round(float(r["priority_score"]), 3),
            "components": {"severity": round(float(r["severity_score"]), 3), "impact": round(float(r["impact_score"]), 3),
                           "risk": round(float(risk_prob), 3)},
            "overrides": overrides, "reasons": reasons}


def main() -> None:
    from src.utils.config import get_settings
    cases = finalize_cases(get_settings().artifacts_dir)
    mix = cases["priority"].value_counts(normalize=True).reindex(["P1", "P2", "P3", "P4"]).mul(100).round(1)
    print(f"cases={len(cases)} overrides={int(cases['priority_override'].sum())}")
    print("priority %: " + ", ".join(f"{k} {v}" for k, v in mix.items()))


if __name__ == "__main__":
    main()
