"""Serve the fault-risk and throughput models (plan §6.2, API §9.3 #9-10).

Accepts partial KPI snapshots: missing leading features are imputed with dataset medians (or the
most common season/weather) and reported in `imputed_fields`.
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.services.kpi_analyzer import Baselines, assess
from src.services.ml.features import CATEGORY_LEVELS, LEADING_CATEGORICAL, LEADING_NUMERIC, to_feature_frame
from src.utils.schema import KPI_SPECS

DEFICIT_TOLERANCE_PCT = 20.0  # |observed - expected| / expected within this is "as expected"


class InvalidKPIError(ValueError):
    pass


class Predictor:
    def __init__(self, model_dir: Path, baselines: Baselines):
        self.fault_model = joblib.load(model_dir / "fault_risk.joblib")
        self.perf_model = joblib.load(model_dir / "performance.joblib")
        self.cards = json.loads((model_dir / "model_cards.json").read_text(encoding="utf-8"))
        self.baselines = baselines
        fr = self.cards["fault_risk"]
        self.bands = fr["risk_bands"]
        self.drivers = {"fault_risk": fr["metrics"]["top_drivers"],
                        "performance": self.cards["performance"]["metrics"]["top_drivers"]}
        mode = {c: max(baselines.vocab[c], key=baselines.vocab[c].get) for c in LEADING_CATEGORICAL}
        self.defaults = {**{k: baselines.median(k) for k in LEADING_NUMERIC}, **mode}

    # ------------------------------------------------------------------ helpers
    def _validate(self, kpis: dict) -> None:
        for key, value in kpis.items():
            if value is None:
                continue
            if key in KPI_SPECS:
                spec = KPI_SPECS[key]
                if not spec.plausible_min <= float(value) <= spec.plausible_max:
                    raise InvalidKPIError(f"{key}={value} outside plausible range "
                                          f"[{spec.plausible_min}, {spec.plausible_max}] {spec.unit}")
            elif key in CATEGORY_LEVELS and value not in CATEGORY_LEVELS[key]:
                raise InvalidKPIError(f"{key}={value!r} must be one of {CATEGORY_LEVELS[key]}")

    def _frame(self, kpis: dict) -> tuple[pd.DataFrame, list[str]]:
        self._validate(kpis)
        row, imputed = {}, []
        for feat in LEADING_NUMERIC + LEADING_CATEGORICAL:
            value = kpis.get(feat)
            if value is None:
                value, _ = self.defaults[feat], imputed.append(feat)
            row[feat] = value
        return to_feature_frame(pd.DataFrame([row])), imputed

    def band(self, p: float) -> str:
        return "Low" if p < self.bands["low_below"] else ("High" if p >= self.bands["high_from"] else "Medium")

    # ------------------------------------------------------------------ public API
    def predict_fault_risk(self, kpis: dict) -> dict:
        X, imputed = self._frame(kpis)
        p = float(self.fault_model.predict_proba(X)[0, 1])
        bands = {a["kpi"]: a["band"] for a in assess(kpis, self.baselines)["per_kpi"]}
        drivers = []
        for d in self.drivers["fault_risk"][:5]:
            feat = d["feature"]
            value = X.iloc[0][feat] if feat not in CATEGORY_LEVELS else CATEGORY_LEVELS[feat][int(X.iloc[0][feat])]
            drivers.append({"feature": feat, "importance": d["importance"],
                            "value": value.item() if isinstance(value, np.generic) else value,
                            "band": bands.get(feat), "imputed": feat in imputed})
        card = self.cards["fault_risk"]
        return {"probability": round(p, 4), "band": self.band(p), "definition": card["definition"],
                "top_drivers": drivers, "imputed_fields": imputed,
                "model": {"version": card["version"], "roc_auc": card["metrics"]["roc_auc"]}}

    def predict_fault_risk_frame(self, df: pd.DataFrame) -> np.ndarray:
        return self.fault_model.predict_proba(to_feature_frame(df))[:, 1]

    def predict_performance(self, kpis: dict) -> dict:
        X, imputed = self._frame(kpis)
        expected = float(self.perf_model.predict(X)[0])
        observed = kpis.get("throughput_mbps")
        deficit = assessment = None
        if observed is not None:
            deficit = round((float(observed) - expected) / expected * 100, 1)
            assessment = ("below_expected" if deficit <= -DEFICIT_TOLERANCE_PCT
                          else "above_expected" if deficit >= DEFICIT_TOLERANCE_PCT else "as_expected")
        card = self.cards["performance"]
        return {"expected_throughput_mbps": round(expected, 1),
                "observed_throughput_mbps": None if observed is None else float(observed),
                "deficit_pct": deficit, "assessment": assessment, "imputed_fields": imputed,
                "model": {"version": card["version"], "r2": card["metrics"]["r2"], "mae": card["metrics"]["mae"]}}
