"""Reproduce the dataset reality check (plan §1.6) and the ML leakage audit (plan §6.4d).

Run from the repo root:  python -m scripts.eda_report [--fast]
Writes docs/assets/eda/{eda_summary.json, leakage_audit.csv, quantiles.csv, category_distribution.csv}.
"""
import argparse
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score

from src.rag.data_loader import load_raw
from src.rag.preprocessing import normalize
from src.utils.config import PROJECT_ROOT, get_settings
from src.utils.schema import NUMERIC_COLUMNS

OUT_DIR = PROJECT_ROOT / "docs" / "assets" / "eda"
CAT_FEATURES = ["season", "weather"]


def feature_frame(df: pd.DataFrame, exclude: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    cols = [c for c in NUMERIC_COLUMNS if c not in exclude]
    X = df[cols].copy()
    for c in CAT_FEATURES:
        X[c] = df[c].astype("category").cat.codes
    return X, np.array([c in CAT_FEATURES for c in X.columns])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="use a 30k-row sample for the model-based checks")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = normalize(load_raw("full"))
    model_df = df.sample(30_000, random_state=0) if args.fast else df
    city_counts = df["city"].value_counts()
    summary = {
        "rows": len(df), "columns_raw": 27, "nulls": int(df.isna().sum().sum()),
        "duplicate_rows": int(df.drop(columns=["case_id"]).duplicated().sum()),
        "issue_reported_counts": df["issue_reported"].value_counts().to_dict(),
        "unique_cities": int(city_counts.size), "cities_with_one_row": int((city_counts == 1).sum()),
        "unique_city_state_pairs": int(df.groupby(["city", "state"]).ngroups),
        "unique_states": int(df["state"].nunique()),
        "weather_counts": df["weather"].value_counts().to_dict(),
        "snow_outside_winter": int(((df["weather"] == "Snow") & (df["season"] != "Winter")).sum()),
        "call_drop_zero_share": round(float((df["call_drop_rate_pct"] == 0).mean()), 3),
    }

    # Leakage audit: how well can each numeric column be predicted from the others?
    # Pass A uses all other columns. Pass B drops fault_occurrence_rate_pct (the fault-risk target, an exact
    # formula of other columns): with it present, the formula's own inputs look "derived" (they can be
    # solved back out of it) although they were generated independently.
    rows = []
    kf = KFold(3, shuffle=True, random_state=0)
    target_formula = "fault_occurrence_rate_pct"

    def r2_pair(target: str, exclude: list[str]) -> tuple[float, float]:
        X, mask = feature_frame(model_df, exclude=[target, *exclude])
        y = model_df[target]
        lin = cross_val_score(LinearRegression(), X, y, cv=kf, scoring="r2").mean()
        hgb = cross_val_score(HistGradientBoostingRegressor(max_iter=200, categorical_features=mask, random_state=0),
                              X, y, cv=kf, scoring="r2").mean()
        return round(lin, 4), round(hgb, 4)

    # Pass C: predict each column from the independently generated ("root") columns only, i.e. the
    # planned leading-indicator set minus the column itself. Root KPIs should score ~0 here; columns
    # generated from other columns score clearly above 0.
    from src.services.ml.features import LEADING_NUMERIC
    for target in NUMERIC_COLUMNS:
        a_lin, a_hgb = r2_pair(target, [])
        b_lin, b_hgb = (a_lin, a_hgb) if target == target_formula else r2_pair(target, [target_formula])
        roots_excl = [c for c in NUMERIC_COLUMNS if c not in LEADING_NUMERIC]
        c_lin, c_hgb = r2_pair(target, roots_excl)
        rows.append({"column": target, "in_leading_set": target in LEADING_NUMERIC,
                     "r2_hgb_all_others": a_hgb, "r2_hgb_without_target": b_hgb, "r2_hgb_from_roots": c_hgb,
                     "r2_linear_all_others": a_lin, "r2_linear_without_target": b_lin, "r2_linear_from_roots": c_lin})
        print(f"{target:28s} all={a_hgb:+.3f}  without FOR={b_hgb:+.3f}  from roots={c_hgb:+.3f}  "
              f"{'LEADING' if target in LEADING_NUMERIC else 'excluded'}")
    audit = pd.DataFrame(rows)
    # Leakage rule (plan §6.4d ii): generated from the root columns if R2 from roots >= 0.15.
    # Temperature/humidity are environmental context derived from season by design and are kept.
    context = {"temperature_c", "humidity_pct"}
    audit["derived_from_others"] = (audit["r2_hgb_from_roots"] >= 0.15) & ~audit["column"].isin(context)
    audit.to_csv(OUT_DIR / "leakage_audit.csv", index=False)

    X, mask = feature_frame(model_df, exclude=[])
    auc = cross_val_score(HistGradientBoostingClassifier(max_iter=200, categorical_features=mask, random_state=0),
                          X, model_df["issue_reported"].astype(int), cv=StratifiedKFold(3, shuffle=True, random_state=0),
                          scoring="roc_auc").mean()
    summary["issue_reported_auc_from_all_columns"] = round(float(auc), 3)
    summary["derived_columns"] = audit.loc[audit["derived_from_others"], "column"].tolist()
    print(f"issue_reported ROC-AUC from all columns: {auc:.3f}")

    df[NUMERIC_COLUMNS].quantile([0.05, 0.10, 0.25, 0.5, 0.75, 0.9, 0.95]).T.round(3).to_csv(OUT_DIR / "quantiles.csv")
    (df.merge(pd.read_parquet(get_settings().artifacts_dir / "processed" / "cases.parquet", columns=["case_id", "primary_category"]),
              on="case_id")["primary_category"].value_counts(normalize=True).mul(100).round(1)
     .to_csv(OUT_DIR / "category_distribution.csv"))
    (OUT_DIR / "eda_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
