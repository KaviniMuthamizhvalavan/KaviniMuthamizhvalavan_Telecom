"""Model feature sets and the leakage rationale (plan §6.4d, Phase 3).

Only independently generated ("root") operating conditions are used as features. Columns that the
synthetic generator computes from other columns are co-outcomes and are excluded; evidence is in
docs/assets/eda/leakage_audit.csv (scripts/eda_report.py).
"""
import pandas as pd

LEADING_NUMERIC = [
    "cell_availability_pct", "mttr_hours", "latency_ms", "packet_loss_pct", "handover_success_pct",
    "alarm_count", "parameter_changes", "config_change_success_pct", "data_usage_gb", "user_count",
    "signal_strength_dbm", "jitter_ms", "cssr_pct", "security_incidents", "temperature_c", "humidity_pct",
]
LEADING_CATEGORICAL = ["season", "weather"]
LEADING_FEATURES = LEADING_NUMERIC + LEADING_CATEGORICAL

EXCLUDED = {
    "throughput_mbps": "co-outcome: near-exact function of other columns (also the performance-model target)",
    "critical_alarm_count": "co-outcome: near-exact function of other columns",
    "auth_failures": "co-outcome: generated from root columns plus noise; direct input of the fault-rate formula",
    "call_drop_rate_pct": "co-outcome: generated from other columns (zero-clipped)",
    "fault_occurrence_rate_pct": "fault-risk target: exact linear formula of other columns",
    "issue_reported": "label noise (ROC-AUC 0.50 from all columns)",
    "state": "identifier (synthetic location)",
    "city": "identifier (synthetic, near-unique)",
    "zip_code": "identifier (synthetic)",
}

CATEGORY_LEVELS = {"season": ["Spring", "Summer", "Fall", "Winter"], "weather": ["Clear", "Clouds", "Rain", "Snow"]}


def to_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Leading-indicator feature frame with categoricals as fixed integer codes (stable across runs)."""
    X = df[LEADING_NUMERIC].astype(float).copy()
    for col, levels in CATEGORY_LEVELS.items():
        X[col] = pd.Categorical(df[col], categories=levels).codes.astype(int)
    return X
