"""Load the raw 5G NetOps CSV (full download or committed sample) and validate its schema."""
from pathlib import Path

import pandas as pd

from src.utils.config import PROJECT_ROOT
from src.utils.schema import DATASET_FILENAME, RAW_COLUMNS, SAMPLE_FILENAME

RAW_DIR = PROJECT_ROOT / "data" / "raw"
SAMPLE_PATH = PROJECT_ROOT / "data" / "sample_data" / SAMPLE_FILENAME


class DatasetSchemaError(ValueError):
    pass


def resolve_source(source: str | Path) -> Path:
    if str(source) == "full":
        path = RAW_DIR / DATASET_FILENAME
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run: python -m scripts.download_data")
        return path
    if str(source) == "sample":
        return SAMPLE_PATH
    return Path(source)


def load_raw(source: str | Path = "full") -> pd.DataFrame:
    """Return the raw dataframe with the original 27 columns, validated."""
    path = resolve_source(source)
    df = pd.read_csv(path, encoding="utf-8")  # compression inferred from the .xz suffix
    validate_raw_schema(df)
    return df


def validate_raw_schema(df: pd.DataFrame) -> None:
    missing = [c for c in RAW_COLUMNS if c not in df.columns]
    extra = [c for c in df.columns if c not in RAW_COLUMNS]
    if missing or extra:
        raise DatasetSchemaError(f"unexpected dataset schema; missing={missing}, extra={extra}")
    if df.empty:
        raise DatasetSchemaError("dataset is empty")
