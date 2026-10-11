"""GET /evaluation/latest (2026-10-10): saved evaluation results plus live validation of stored runs. Read-only: no
LLM, no evaluation run. Uses a temporary run database; the saved results are read from evaluation/results/final/."""
import json

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services import evaluation_results
from src.services.container import ServiceContainer
from src.services.feedback_service import RunStore
from src.utils.config import Settings

API = "/api/v1"


def save(store, run_id, verdict, model="anthropic/claude-haiku-5.5", status="ok", scores=None, endpoint="troubleshoot"):
    resp = {"validation": {"verdict": verdict, "scores": scores or {}}} if verdict in ("pass", "fail") else {}
    store.save_run(run_id=run_id, endpoint=endpoint, query=f"query {run_id}", request={}, response=resp, status=status,
                   primary_category="TRANSPORT_QOS", priority="P4", judge_verdict=verdict, model=model,
                   prompt_version="v1", latency_ms=40000.0, tokens_in=20000, tokens_out=10000)


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "app.db")


@pytest.fixture
def client(store):
    app.state.container = ServiceContainer(settings=Settings(_env_file=None), runs=store)
    return TestClient(app)


def test_saved_phase11_results_are_served(client):
    body = client.get(f"{API}/evaluation/latest").json()
    off = body["offline"]
    assert off["totals"]["PASS"] == 26 and off["totals"]["FAIL"] == 2
    assert off["models"]["eval_judge"] == "claude-opus-5-5" and off["dataset"]["cases"] == 100000
    assert {r["system"] for r in off["deepeval"]} == {"A", "C"} and off["judge_meta"]["detection_rate"] == 1.0
    assert off["end_to_end"]["C_latency_s"]["median"] == 31.4
    assert body["live"]["total"] == 0 and body["warnings"] == []


def test_live_validation_counts_verdicts_models_and_scores(client, store):
    save(store, "a", "pass", scores={"groundedness": 0.8, "kpi_consistency": 0.7, "actionability": 0.8,
                                     "completeness": 0.6})
    save(store, "b", "fail", scores={"groundedness": 0.6, "kpi_consistency": 0.5, "actionability": 0.8,
                                     "completeness": 0.6})
    save(store, "c", "unvalidated", model="none", status="degraded")
    save(store, "d", None, status="needs_clarification")
    save(store, "e", None, endpoint="recommend")  # basic RAG is never judged and is not counted
    live = client.get(f"{API}/evaluation/latest", params={"days": 7}).json()["live"]
    assert live["total"] == 4 and live["verdicts"] == {"pass": 1, "fail": 1, "unvalidated": 1, "not_judged": 1}
    assert live["pass_rate"] == 0.5 and live["scored_runs"] == 2
    assert live["avg_scores"] == {"groundedness": 0.7, "kpi_consistency": 0.6, "actionability": 0.8,
                                  "completeness": 0.6}
    haiku = next(m for m in live["by_model"] if m["model"] == "anthropic/claude-haiku-5.5")
    assert (haiku["runs"], haiku["pass"], haiku["fail"], haiku["avg_latency_s"], haiku["avg_tokens"]) == \
        (3, 1, 1, 40.0, 30000)
    assert len(live["recent"]) == 4 and {r["verdict"] for r in live["recent"]} == {"pass", "fail", "unvalidated", None}


def test_missing_results_are_an_empty_state_not_an_error(client, monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation_results, "RESULTS_DIR", tmp_path / "nothing")
    r = client.get(f"{API}/evaluation/latest")
    assert r.status_code == 200 and r.json()["offline"] is None
    assert any("No saved evaluation results" in w for w in r.json()["warnings"])


def test_partial_results_load_what_exists(tmp_path):
    (tmp_path / "summary.json").write_text(json.dumps([{"Component": "Retrieval", "Metric": "Hit@5", "Value": 1.0,
                                                        "Target": ">= 0.90", "Status": "PASS"}]), encoding="utf-8")
    off = evaluation_results.load_offline(tmp_path)
    assert off["totals"] == {"PASS": 1} and "deepeval" not in off and "judge_meta" not in off


def test_no_run_database_still_serves_the_report():
    app.state.container = ServiceContainer(settings=Settings(_env_file=None), runs=None)
    body = TestClient(app).get(f"{API}/evaluation/latest").json()
    assert body["offline"] is not None and body["live"] is None
    assert any("run database is unavailable" in w for w in body["warnings"])


def test_period_is_validated(client):
    assert client.get(f"{API}/evaluation/latest", params={"days": 0}).status_code == 422


def test_no_alternative_run_means_an_empty_list(client, monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation_results, "ALTERNATIVE_DIRS", (tmp_path / "not_run_yet",))
    body = client.get(f"{API}/evaluation/latest").json()
    assert body["offline_alternatives"] == [] and body["offline"]["models"]["runtime"] == "claude-sonnet-5-5"


def test_alternative_run_is_served_next_to_final_unchanged(client, monkeypatch, tmp_path):
    alt = tmp_path / "aicredits_haiku_demo"
    alt.mkdir()
    (alt / "summary.json").write_text(json.dumps([{"Component": "Retrieval", "Metric": "Hit@5", "Value": 1.0,
                                                   "Target": ">= 0.90", "Status": "PASS"}]), encoding="utf-8")
    (alt / "run_config.json").write_text(json.dumps({"models": {"runtime": "anthropic/claude-haiku-5.5",
                                                                "runtime_provider": "aicredits",
                                                                "eval_judge": "openai/gpt-oss-120b"}}), encoding="utf-8")
    monkeypatch.setattr(evaluation_results, "ALTERNATIVE_DIRS", (alt,))
    body = client.get(f"{API}/evaluation/latest").json()
    assert body["offline"]["models"]["eval_judge"] == "claude-opus-5-5" and body["offline"]["totals"]["PASS"] == 26
    [run] = body["offline_alternatives"]
    assert run["id"] == "aicredits_haiku_demo" and run["models"]["runtime"] == "anthropic/claude-haiku-5.5"
    assert run["totals"] == {"PASS": 1} and run["report_files"] == []
