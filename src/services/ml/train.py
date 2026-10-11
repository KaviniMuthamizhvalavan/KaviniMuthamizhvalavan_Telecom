"""Train and evaluate the fault-risk classifier and the throughput regressor (plan Phase 3).

CLI (repo root):  python -m src.services.ml.train
Inputs : artifacts/processed/cases.parquet (Phase 1)
Outputs: artifacts/models/{fault_risk.joblib, performance.joblib, model_cards.json}
         artifacts/processed/fault_risk_oof.parquet (out-of-fold risk for every case, used by priority)
         evaluation/results/final/ml/ (metrics JSON + plots)
"""
import json
from pathlib import Path
import logging
import time
from datetime import date

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import sklearn  # noqa: E402
from sklearn.calibration import calibration_curve  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.dummy import DummyClassifier, DummyRegressor  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import (average_precision_score, brier_score_loss, f1_score, mean_absolute_error,  # noqa: E402
                             precision_recall_curve, r2_score, roc_auc_score, roc_curve, root_mean_squared_error,
                             confusion_matrix)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # noqa: E402

from src.services.ml.features import EXCLUDED, LEADING_CATEGORICAL, LEADING_FEATURES, LEADING_NUMERIC, to_feature_frame  # noqa: E402
from src.utils.config import PROJECT_ROOT, get_settings  # noqa: E402

log = logging.getLogger(__name__)
SEED = 42
RISK_BANDS = {"low_below": 0.30, "high_from": 0.60}
TARGET_FOR = "fault_occurrence_rate_pct"
TARGET_PERF = "throughput_mbps"
FINAL_RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results" / "final" / "ml"
RESULTS_DIR = FINAL_RESULTS_DIR  # set by main() for each run (results_dir)


def results_dir(s) -> Path:
    """Where this run's ML metrics and plots go. Only the full dataset in the project's own artifacts folder writes the
    published results; sample or scratch builds (e.g. ARTIFACTS_DIR=... bootstrap --source sample) write next to their
    artifacts, so they can never overwrite the evaluation baseline."""
    if s.data_source == "full" and Path(s.artifacts_dir).resolve() == (PROJECT_ROOT / "artifacts").resolve():
        return FINAL_RESULTS_DIR
    return Path(s.artifacts_dir) / "ml_results"


def _categorical_mask() -> list[bool]:
    return [c in LEADING_CATEGORICAL for c in LEADING_FEATURES]


def fault_risk_model() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, categorical_features=_categorical_mask(),
                                          random_state=SEED)


def performance_model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, categorical_features=_categorical_mask(),
                                         random_state=SEED)


def logistic_baseline():
    pre = ColumnTransformer([("num", StandardScaler(), LEADING_NUMERIC),
                             ("cat", OneHotEncoder(handle_unknown="ignore"), LEADING_CATEGORICAL)])
    return make_pipeline(pre, LogisticRegression(max_iter=1000))


def band(p: float) -> str:
    return "Low" if p < RISK_BANDS["low_below"] else ("High" if p >= RISK_BANDS["high_from"] else "Medium")


def top_drivers(model, X: pd.DataFrame, y, scoring: str, n: int = 8) -> list[dict]:
    sub = X.sample(min(10_000, len(X)), random_state=SEED)
    imp = permutation_importance(model, sub, np.asarray(y)[X.index.get_indexer(sub.index)], scoring=scoring,
                                 n_repeats=5, random_state=SEED, n_jobs=1)
    order = np.argsort(-imp.importances_mean)[:n]
    return [{"feature": X.columns[i], "importance": round(float(imp.importances_mean[i]), 4)} for i in order]


def train_fault_risk(df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    X = to_feature_frame(df)
    idx_train, idx_test = train_test_split(np.arange(len(df)), test_size=0.2, random_state=SEED,
                                           stratify=(df[TARGET_FOR] >= df[TARGET_FOR].quantile(0.75)))
    threshold = float(df[TARGET_FOR].iloc[idx_train].quantile(0.75))  # target defined on the training split only
    y = (df[TARGET_FOR] >= threshold).astype(int).to_numpy()
    Xtr, Xte, ytr, yte = X.iloc[idx_train], X.iloc[idx_test], y[idx_train], y[idx_test]

    model = fault_risk_model().fit(Xtr, ytr)
    p = model.predict_proba(Xte)[:, 1]
    lr = logistic_baseline().fit(df.iloc[idx_train], ytr)
    p_lr = lr.predict_proba(df.iloc[idx_test])[:, 1]
    p_dummy = DummyClassifier(strategy="prior").fit(Xtr, ytr).predict_proba(Xte)[:, 1]

    prec, rec, thr = precision_recall_curve(yte, p)
    f1s = 2 * prec[:-1] * rec[:-1] / np.clip(prec[:-1] + rec[:-1], 1e-9, None)
    best_t = float(thr[np.argmax(f1s)])
    bands = np.array([band(v) for v in p])
    band_stats = {b: {"share": round(float(np.mean(bands == b)), 3),
                      "actual_high_rate": round(float(yte[bands == b].mean()), 3) if np.any(bands == b) else None}
                  for b in ("Low", "Medium", "High")}
    metrics = {
        "target": f"{TARGET_FOR} >= {threshold:.2f} (p75 of training split)",
        "threshold_value": threshold, "base_rate_test": round(float(yte.mean()), 4),
        "n_train": len(idx_train), "n_test": len(idx_test),
        "roc_auc": round(roc_auc_score(yte, p), 4), "pr_auc": round(average_precision_score(yte, p), 4),
        "brier": round(brier_score_loss(yte, p), 4),
        "f1_at_0_5": round(f1_score(yte, p >= 0.5), 4), "best_f1_threshold": round(best_t, 3),
        "f1_at_best": round(float(f1s.max()), 4),
        "confusion_at_0_5": confusion_matrix(yte, p >= 0.5).tolist(),
        "baselines": {"logistic_regression_roc_auc": round(roc_auc_score(yte, p_lr), 4),
                      "majority_roc_auc": round(roc_auc_score(yte, p_dummy), 4),
                      "logistic_regression_brier": round(brier_score_loss(yte, p_lr), 4),
                      "majority_brier": round(brier_score_loss(yte, p_dummy), 4)},
        "risk_bands": RISK_BANDS, "band_stats_test": band_stats,
        "top_drivers": top_drivers(model, Xte, yte, "roc_auc"),
    }

    # Plots: ROC, PR, calibration.
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
    fpr, tpr, _ = roc_curve(yte, p)
    ax[0].plot(fpr, tpr, label=f"HGB AUC {metrics['roc_auc']:.3f}")
    fpr2, tpr2, _ = roc_curve(yte, p_lr)
    ax[0].plot(fpr2, tpr2, label=f"Logistic AUC {metrics['baselines']['logistic_regression_roc_auc']:.3f}")
    ax[0].plot([0, 1], [0, 1], "k--", lw=0.8)
    ax[0].set(title="ROC (test)", xlabel="False positive rate", ylabel="True positive rate")
    ax[0].legend()
    ax[1].plot(rec, prec)
    ax[1].axhline(yte.mean(), color="k", ls="--", lw=0.8)
    ax[1].set(title=f"Precision-recall (AP {metrics['pr_auc']:.3f})", xlabel="Recall", ylabel="Precision")
    frac, mean_pred = calibration_curve(yte, p, n_bins=10)
    ax[2].plot(mean_pred, frac, "o-")
    ax[2].plot([0, 1], [0, 1], "k--", lw=0.8)
    ax[2].set(title=f"Calibration (Brier {metrics['brier']:.3f})", xlabel="Predicted", ylabel="Observed")
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "fault_risk_curves.png", dpi=120)
    plt.close(fig)

    # Out-of-fold probabilities for every case (no in-sample optimism for historical priority).
    oof = cross_val_predict(fault_risk_model(), X, y, cv=StratifiedKFold(5, shuffle=True, random_state=SEED),
                            method="predict_proba")[:, 1]
    metrics["oof_roc_auc_all_rows"] = round(roc_auc_score(y, oof), 4)
    oof_df = pd.DataFrame({"case_id": df["case_id"], "fault_risk_prob": oof.astype(np.float32),
                           "fault_risk_band": [band(v) for v in oof]})

    final = fault_risk_model().fit(X, y)  # deployed model: all rows
    return {"model": final, "metrics": metrics, "threshold": threshold}, oof_df


def train_performance(df: pd.DataFrame) -> dict:
    X, y = to_feature_frame(df), df[TARGET_PERF].to_numpy()
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=SEED)
    model = performance_model().fit(Xtr, ytr)
    pred = model.predict(Xte)
    base = DummyRegressor().fit(Xtr, ytr).predict(Xte)
    metrics = {
        "target": TARGET_PERF, "n_train": len(Xtr), "n_test": len(Xte),
        "r2": round(r2_score(yte, pred), 4), "mae": round(mean_absolute_error(yte, pred), 2),
        "rmse": round(root_mean_squared_error(yte, pred), 2),
        "baseline_mean": {"r2": round(r2_score(yte, base), 4), "mae": round(mean_absolute_error(yte, base), 2),
                          "rmse": round(root_mean_squared_error(yte, base), 2)},
        "residual_std": round(float(np.std(yte - pred)), 2),
        "top_drivers": top_drivers(model, Xte, yte, "r2"),
    }
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.5))
    idx = np.random.default_rng(SEED).choice(len(yte), min(3000, len(yte)), replace=False)  # sample data: <3000
    ax[0].scatter(yte[idx], pred[idx], s=4, alpha=0.4)
    lims = [min(yte.min(), pred.min()), max(yte.max(), pred.max())]
    ax[0].plot(lims, lims, "k--", lw=0.8)
    ax[0].set(title=f"Throughput: predicted vs actual (R2 {metrics['r2']:.3f})", xlabel="Actual (Mbps)",
              ylabel="Predicted (Mbps)")
    ax[1].hist(yte - pred, bins=60)
    ax[1].set(title=f"Residuals (MAE {metrics['mae']:.0f} Mbps)", xlabel="Actual - predicted (Mbps)")
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "performance_pred_vs_actual.png", dpi=120)
    plt.close(fig)
    final = performance_model().fit(X, y)
    return {"model": final, "metrics": metrics}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    global RESULTS_DIR
    s = get_settings()
    RESULTS_DIR = results_dir(s)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    log.info("ML results -> %s", RESULTS_DIR)
    model_dir = s.artifacts_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    cases_path = s.artifacts_dir / "processed" / "cases.parquet"
    df = pd.read_parquet(cases_path)

    t0 = time.perf_counter()
    fr, oof = train_fault_risk(df)
    t1 = time.perf_counter()
    perf = train_performance(df)
    t2 = time.perf_counter()

    joblib.dump(fr["model"], model_dir / "fault_risk.joblib")
    joblib.dump(perf["model"], model_dir / "performance.joblib")
    oof.to_parquet(s.artifacts_dir / "processed" / "fault_risk_oof.parquet", index=False)
    common = {"features": LEADING_FEATURES, "excluded": EXCLUDED, "trained": date.today().isoformat(),
              "sklearn_version": sklearn.__version__, "n_rows": len(df), "seed": SEED}
    cards = {
        "fault_risk": {**common, "version": "fault_risk-v1", "type": "HistGradientBoostingClassifier",
                       "definition": f"P(fault occurrence rate >= {fr['threshold']:.2f}%, the training-split p75)",
                       "threshold_value": fr["threshold"], "risk_bands": RISK_BANDS, "metrics": fr["metrics"]},
        "performance": {**common, "version": "performance-v1", "type": "HistGradientBoostingRegressor",
                        "target": TARGET_PERF, "metrics": perf["metrics"]},
    }
    (model_dir / "model_cards.json").write_text(json.dumps(cards, indent=2), encoding="utf-8")
    (RESULTS_DIR / "fault_risk_metrics.json").write_text(json.dumps(fr["metrics"], indent=2), encoding="utf-8")
    (RESULTS_DIR / "performance_metrics.json").write_text(json.dumps(perf["metrics"], indent=2), encoding="utf-8")
    print(f"fault risk : {json.dumps({k: fr['metrics'][k] for k in ('roc_auc', 'pr_auc', 'brier', 'f1_at_0_5', 'f1_at_best', 'best_f1_threshold', 'oof_roc_auc_all_rows')})}")
    print(f"  baselines: {fr['metrics']['baselines']}")
    print(f"  bands    : {fr['metrics']['band_stats_test']}")
    print(f"  drivers  : {[d['feature'] for d in fr['metrics']['top_drivers'][:6]]}")
    print(f"performance: r2={perf['metrics']['r2']} mae={perf['metrics']['mae']} rmse={perf['metrics']['rmse']} "
          f"baseline={perf['metrics']['baseline_mean']}")
    print(f"  drivers  : {[d['feature'] for d in perf['metrics']['top_drivers'][:6]]}")
    print(f"timings: fault risk {t1 - t0:.0f}s, performance {t2 - t1:.0f}s")


if __name__ == "__main__":
    main()
