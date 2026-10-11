import pytest

from src.services.kpi_analyzer import Baselines
from src.services.ml.features import EXCLUDED, LEADING_FEATURES
from src.services.ml.predictor import InvalidKPIError, Predictor
from src.utils.config import get_settings

ART = get_settings().artifacts_dir


@pytest.fixture(scope="module")
def predictor():
    if not (ART / "models" / "fault_risk.joblib").exists():
        pytest.skip("models missing; run python -m src.services.ml.train")
    return Predictor(ART / "models", Baselines.from_json(ART / "baselines.json"))


def test_no_excluded_column_is_a_feature():
    assert not set(EXCLUDED) & set(LEADING_FEATURES)


def test_empty_snapshot_is_fully_imputed(predictor):
    r = predictor.predict_fault_risk({})
    assert 0 <= r["probability"] <= 1 and r["band"] in {"Low", "Medium", "High"}
    assert len(r["imputed_fields"]) == len(LEADING_FEATURES)


def test_snow_and_bad_kpis_raise_risk_and_cut_throughput(predictor):
    clear = {"weather": "Clear", "season": "Summer"}
    stormy = {"weather": "Snow", "season": "Winter", "packet_loss_pct": 15, "latency_ms": 160,
              "alarm_count": 18, "security_incidents": 18}
    assert predictor.predict_fault_risk(stormy)["probability"] > predictor.predict_fault_risk(clear)["probability"]
    assert (predictor.predict_performance(stormy)["expected_throughput_mbps"]
            < predictor.predict_performance(clear)["expected_throughput_mbps"])


def test_deficit_uses_observed_throughput(predictor):
    r = predictor.predict_performance({"throughput_mbps": 1.0})
    assert r["assessment"] == "below_expected" and r["deficit_pct"] < -20


def test_predictions_are_deterministic(predictor):
    kpis = {"latency_ms": 120, "weather": "Rain"}
    assert predictor.predict_fault_risk(kpis) == predictor.predict_fault_risk(kpis)


@pytest.mark.parametrize("bad", [{"latency_ms": -5}, {"packet_loss_pct": 140}, {"weather": "Hail"}])
def test_out_of_range_inputs_rejected(predictor, bad):
    with pytest.raises(InvalidKPIError):
        predictor.predict_fault_risk(bad)
