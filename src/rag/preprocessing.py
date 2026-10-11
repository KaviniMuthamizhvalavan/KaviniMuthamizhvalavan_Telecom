"""Raw CSV -> normalized, labelled cases + baselines (plan Phase 1, §7.2).

CLI (repo root):  python -m src.rag.preprocessing --source full|sample
Writes artifacts/processed/cases.parquet and artifacts/baselines.json.
"""
import argparse
import hashlib
import logging
import time

import numpy as np
import pandas as pd

from src.rag.data_loader import load_raw, resolve_source
from src.services.kpi_analyzer import Baselines, assess_frame, compute_baselines
from src.utils.config import get_settings
from src.utils.schema import COLUMN_MAP, KPI_SPECS, NUMERIC_COLUMNS

log = logging.getLogger(__name__)


def normalize(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Rename to snake_case, coerce types, add case_id and a case-folded city for filtering."""
    df = df_raw.rename(columns=COLUMN_MAP).copy()
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="raise").astype(float)
    df["zip_code"] = df["zip_code"].astype(int)
    for col in ("season", "weather", "state", "city"):
        df[col] = df[col].astype(str).str.strip()
    df["issue_reported"] = df["issue_reported"].astype(str).str.strip().str.lower().eq("yes")
    df["city_lc"] = df["city"].str.lower()
    df.insert(0, "case_id", [f"CASE-{i:06d}" for i in range(1, len(df) + 1)])
    return df


def range_violations(df: pd.DataFrame) -> dict[str, int]:
    """Count values outside each KPI's plausible range (expected: none)."""
    out = {}
    for kpi, spec in KPI_SPECS.items():
        n = int(((df[kpi] < spec.plausible_min) | (df[kpi] > spec.plausible_max)).sum())
        if n:
            out[kpi] = n
    return out


def label_cases(df: pd.DataFrame, baselines: Baselines) -> pd.DataFrame:
    return pd.concat([df, assess_frame(df, baselines)], axis=1)


def file_sha256(path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def build(source: str = "full") -> tuple[pd.DataFrame, Baselines]:
    s = get_settings()
    t0 = time.perf_counter()
    df = normalize(load_raw(source))
    bad = range_violations(df)
    if bad:
        log.warning("values outside plausible ranges: %s", bad)
    baselines = compute_baselines(df, file_sha256(resolve_source(source)))
    cases = label_cases(df, baselines)
    out_dir = s.artifacts_dir / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    cases.to_parquet(out_dir / "cases.parquet", index=False)
    baselines.to_json(s.artifacts_dir / "baselines.json")
    log.info("processed %d cases in %.1fs", len(cases), time.perf_counter() - t0)
    return cases, baselines


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=get_settings().data_source)
    args = parser.parse_args()
    cases, b = build(args.source)
    dist = (cases["primary_category"].value_counts(normalize=True) * 100).round(1)
    print(f"cases={len(cases)} columns={cases.shape[1]} sha256={b.dataset_sha256[:12]}")
    print(f"range violations: {range_violations(cases) or 'none'}")
    print(f"mean anomalies/row={cases['n_anomalies'].mean():.2f}, rows with none={np.mean(cases['n_anomalies'] == 0):.3f}")
    print("primary category %:\n" + dist.to_string())


if __name__ == "__main__":
    main()
