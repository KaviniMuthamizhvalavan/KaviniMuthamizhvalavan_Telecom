"""Deterministic network-impact estimate (plan §6.4c): affected services, blast radius, impact level."""
import numpy as np

from src.services.kpi_analyzer import Baselines, percentile_rank

SERVICE_MAP = {
    "voice": ["call_drop_rate_pct", "cssr_pct", "handover_success_pct"],
    "data": ["throughput_mbps", "packet_loss_pct"],
    "real-time and video": ["latency_ms", "jitter_ms", "packet_loss_pct"],
    "network access": ["cssr_pct", "cell_availability_pct", "auth_failures"],
}
SERVICE_AFFECTING = sorted({k for ks in SERVICE_MAP.values() for k in ks})


def estimate_impact(assessment: dict, b: Baselines) -> dict:
    """Impact from one assessed snapshot (kpi_analyzer.assess output; missing values are imputed medians)."""
    bands = {p["kpi"]: p["band"] for p in assessment["per_kpi"] if not p["imputed"]}
    kpis = {p["kpi"]: p["value"] for p in assessment["per_kpi"]}
    affected = [svc for svc, ks in SERVICE_MAP.items() if any(bands.get(k, "normal") != "normal" for k in ks)]
    if bands.get("cell_availability_pct") == "critical":
        affected = ["all services"]
    users = float(kpis["user_count"])
    users_pct = float(percentile_rank(np.array([users]), b.tables["user_count"])[0])
    critical = any(bands.get(k) == "critical" for k in SERVICE_AFFECTING)
    degraded = any(bands.get(k, "normal") != "normal" for k in SERVICE_AFFECTING)
    high_load = users_pct >= 0.90
    if high_load and critical:
        level = "Severe"
    elif high_load or critical:
        level = "High"
    elif degraded:
        level = "Moderate"
    else:
        level = "Low"
    return {"level": level, "affected_services": affected, "users_served": int(users),
            "users_percentile": round(users_pct, 3), "data_gb": float(kpis["data_usage_gb"]),
            "critical_service_kpis": [k for k in SERVICE_AFFECTING if bands.get(k) == "critical"]}
