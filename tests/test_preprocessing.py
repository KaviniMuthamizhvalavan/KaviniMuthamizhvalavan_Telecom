import hashlib

import pandas as pd
import pytest

from src.rag.data_loader import DatasetSchemaError, load_raw, validate_raw_schema
from src.rag.preprocessing import label_cases, normalize, range_violations
from src.utils.schema import COLUMN_MAP, NUMERIC_COLUMNS


def test_column_map_covers_27_raw_columns_and_is_injective():
    assert len(COLUMN_MAP) == 27
    assert len(set(COLUMN_MAP.values())) == 27


def test_schema_validation_rejects_missing_column():
    df = load_raw("sample").drop(columns=["Weather"])
    with pytest.raises(DatasetSchemaError):
        validate_raw_schema(df)


def test_normalize_types_ids_and_flags(sample_cases):
    df = sample_cases
    assert df["case_id"].is_unique and df["case_id"].iloc[0] == "CASE-000001"
    assert df["issue_reported"].dtype == bool
    assert all(pd.api.types.is_float_dtype(df[c]) for c in NUMERIC_COLUMNS)
    assert (df["city_lc"] == df["city"].str.lower()).all()
    assert range_violations(df) == {}


def test_labelling_is_deterministic(sample_cases, sample_baselines):
    def digest(frame: pd.DataFrame) -> str:
        return hashlib.sha256(pd.util.hash_pandas_object(frame, index=False).values.tobytes()).hexdigest()

    a = label_cases(sample_cases, sample_baselines)
    b = label_cases(normalize(load_raw("sample")), sample_baselines)
    assert digest(a) == digest(b)
