"""Build the committed 10k sample (raw CSV format) stratified by primary category x season.

Run from the repo root after preprocessing the full dataset:  python -m scripts.make_sample
"""
import pandas as pd

from src.rag.data_loader import SAMPLE_PATH, load_raw, validate_raw_schema
from src.utils.config import get_settings

SAMPLE_SIZE = 10_000
SEED = 42


def main() -> None:
    raw = load_raw("full")
    labels = pd.read_parquet(get_settings().artifacts_dir / "processed" / "cases.parquet",
                             columns=["primary_category", "season"])
    strata = labels["primary_category"] + "|" + labels["season"]
    frac = SAMPLE_SIZE / len(raw)
    idx = (strata.groupby(strata, group_keys=False)
           .apply(lambda g: g.sample(frac=frac, random_state=SEED)).index)
    sample = raw.loc[sorted(idx)]
    validate_raw_schema(sample)
    SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(SAMPLE_PATH, index=False, encoding="utf-8")
    full_dist = labels["primary_category"].value_counts(normalize=True)
    sample_dist = labels.loc[idx, "primary_category"].value_counts(normalize=True)
    print(f"wrote {SAMPLE_PATH} rows={len(sample)} bytes={SAMPLE_PATH.stat().st_size:,}")
    print("max category share difference vs full: "
          f"{(full_dist - sample_dist).abs().max() * 100:.2f} percentage points")


if __name__ == "__main__":
    main()
