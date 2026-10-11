"""Feedback loop (plan §8.6, Phase 9 verify): capture, validation, smoothed priors, rerank effect, summary, export."""
import json

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.rag.filters import SearchFilters
from src.services.container import ServiceContainer
from src.services.feedback_service import RunStore, export_regressions
from src.services.guardrails import Guardrails
from src.services.kpi_analyzer import Baselines
from src.services.llm_client import LLMClient
from src.services.ml.predictor import Predictor
from src.utils.config import Settings, get_settings

QUERY = "high latency and packet loss"
API = "/api/v1"


@pytest.fixture()
def store(tmp_path):
    return RunStore(tmp_path / "app.db")


def _run(store, run_id="run-1", category="TRANSPORT_QOS"):
    store.save_run(run_id=run_id, endpoint="troubleshoot", query=QUERY, request={}, response={}, status="ok",
                   primary_category=category, priority="P3", judge_verdict="pass", model="m", prompt_version="v1",
                   latency_ms=1.0, tokens_in=1, tokens_out=1)


def test_priors_are_smoothed_and_category_scoped(store):
    _run(store)
    store.add_feedback("run-1", None, None, None, None, [{"case_id": "CASE-000001", "relevant": False},
                                                         {"case_id": "CASE-000002", "relevant": True}])
    store.add_feedback("run-1", None, None, None, None, [{"case_id": "CASE-000001", "relevant": False}])
    p = store.priors("TRANSPORT_QOS")
    assert p["CASE-000001"] == pytest.approx(1 / 4) and p["CASE-000002"] == pytest.approx(2 / 3)
    assert store.priors("RADIO_COVERAGE") == {} and store.priors(None) == {}


def test_downvoted_case_drops_for_same_category_only(small_index, store):
    retriever, _, _ = small_index
    base = retriever.search(QUERY, top_k=10, category="TRANSPORT_QOS")
    res = base["results"]
    # the prior is bounded (weight 0.1 -> at most -0.05), so it reorders near-ties only: pick one within 0.03
    i = next(i for i in range(len(res) - 1) if res[i]["final_score"] - res[i + 1]["final_score"] < 0.03)
    target, start = res[i]["case_id"], res[i]["rank"]
    _run(store)
    for _ in range(3):
        store.add_feedback("run-1", None, None, None, None, [{"case_id": target, "relevant": False}])
    retriever.priors_provider = store.priors
    try:
        same = retriever.search(QUERY, top_k=10, category="TRANSPORT_QOS")
        other = retriever.search(QUERY, top_k=10, category="RADIO_COVERAGE")
    finally:
        retriever.priors_provider = None
    rank = lambda r: next((x["rank"] for x in r["results"] if x["case_id"] == target), 99)  # noqa: E731
    assert rank(same) > rank(base) == start
    assert [x["case_id"] for x in other["results"]] == [x["case_id"] for x in base["results"]]
    downvoted = next((x for x in same["results"] if x["case_id"] == target), None)
    assert downvoted is None or downvoted["score_breakdown"]["feedback_prior"] == pytest.approx(0.2)


def test_summary_and_regression_export(store, tmp_path):
    _run(store, "run-1", "TRANSPORT_QOS")
    _run(store, "run-2", "FAULT_ALARM")
    store.add_feedback("run-1", 2, False, "CONGESTION_CAPACITY", "wrong type", [{"case_id": "CASE-000009",
                                                                                 "relevant": False}])
    store.add_feedback("run-2", 5, True, None, None, [])
    s = store.summary()
    assert s["total_runs"] == 2 and s["total_feedback"] == 2 and s["avg_rating"] == 3.5 and s["helpful_rate"] == 0.5
    assert s["corrections_count"] == 1 and s["most_downvoted_cases"][0]["case_id"] == "CASE-000009"
    assert {c["category"] for c in s["by_category"]} == {"TRANSPORT_QOS", "FAULT_ALARM"} and s["trend"][0]["n"] == 2
    out = tmp_path / "regressions.json"
    assert export_regressions(store, out) == 1
    case = json.loads(out.read_text())[0]
    assert case["run_id"] == "run-1" and case["expected_primary"] == "CONGESTION_CAPACITY" and case["query"] == QUERY


@pytest.fixture()
def client(small_index, store):
    retriever, vstore, cases = small_index
    s = get_settings()
    b = Baselines.from_json(s.artifacts_dir / "baselines.json")
    app.state.container = ServiceContainer(
        settings=s, baselines=b, cases=cases, predictor=Predictor(s.artifacts_dir / "models", b),
        embedder=retriever.embedder, store=vstore, retriever=retriever, runs=store,
        case_index={cid: i for i, cid in enumerate(cases["case_id"])}, guardrails=Guardrails(retriever.embedder),
        llm=LLMClient(Settings(_env_file=None, llm_provider="none")))
    retriever.priors_provider = store.priors
    yield TestClient(app)
    retriever.priors_provider = None


def test_feedback_api_end_to_end(client, store):
    # a real (reduced-mode) run is persisted and can receive feedback that changes the next ranking
    r = client.post(f"{API}/troubleshoot", json={"query": "High latency and packet loss on the transport link"}).json()
    run_id, top = r["run_id"], r["similar_cases"][0]["case_id"]
    assert store.get_run(run_id)["primary_category"] == r["classification"]["primary_category"]
    body = {"run_id": run_id, "rating": 2, "helpful": False, "comment": "mail me at a@b.com",
            "case_feedback": [{"case_id": top, "relevant": False}] * 3}
    fb = client.post(f"{API}/feedback", json=body)
    assert fb.status_code == 200, fb.text
    d = fb.json()
    assert d["accepted"] and d["effects"] == {"priors_updated": 3, "correction_stored": False} and d["warnings"]
    again = client.post(f"{API}/troubleshoot", json={"query": "High latency and packet loss on the transport link"})
    ids = [x["case_id"] for x in again.json()["similar_cases"]]
    assert top not in ids[:1]
    summary = client.get(f"{API}/feedback/summary").json()
    assert summary["total_feedback"] == 1 and summary["most_downvoted_cases"][0]["case_id"] == top
    with store._conn() as con:
        assert con.execute("SELECT comment FROM feedback").fetchone()[0] == "mail me at [EMAIL]"


def test_feedback_api_errors(client, store):
    _run(store, "known-run")
    err = lambda r, s, code: r.status_code == s and r.json()["error"]["code"] == code  # noqa: E731
    assert err(client.post(f"{API}/feedback", json={"run_id": "nope", "rating": 3}), 404, "NOT_FOUND")
    assert err(client.post(f"{API}/feedback", json={"run_id": "known-run"}), 422, "INVALID_INPUT")
    assert err(client.post(f"{API}/feedback", json={"run_id": "known-run", "corrected_category": "BOGUS"}), 422,
               "INVALID_INPUT")
    assert err(client.post(f"{API}/feedback", json={"run_id": "known-run", "rating": 9}), 422, "INVALID_INPUT")
    assert err(client.post(f"{API}/feedback", json={"run_id": "known-run",
                                                    "case_feedback": [{"case_id": "CASE-999999", "relevant": True}]}),
               422, "INVALID_INPUT")


# ---------------------------------------------------------------- /search uses the rule-based category for priors
SEARCH_Q = "High latency and packet loss on the transport link"  # rule category: TRANSPORT_QOS
OTHER_Q = "Handover failures and dropped calls when users move between cells"  # MOBILITY_HANDOVER


def _search(client, q, k=10):
    r = client.post(f"{API}/search", json={"query": q, "top_k": k})
    assert r.status_code == 200, r.text
    return r.json()["results"]


def test_search_unchanged_without_feedback(client, small_index):
    retriever, _, _ = small_index
    with_hook = _search(client, SEARCH_Q)
    retriever.priors_provider = None  # the pre-fix path: no priors at all
    without = _search(client, SEARCH_Q)
    assert [(x["case_id"], x["final_score"]) for x in with_hook] == [(x["case_id"], x["final_score"]) for x in without]
    assert all(x["score_breakdown"]["feedback_prior"] == 0.5 for x in with_hook)


def test_search_downvote_moves_same_category_only(client, store):
    from src.agents.classifier_agent import rule_classify
    assert rule_classify(SEARCH_Q).primary_category == "TRANSPORT_QOS"
    assert rule_classify(OTHER_Q).primary_category == "MOBILITY_HANDOVER"
    base, other_base = _search(client, SEARCH_Q), _search(client, OTHER_Q)
    i = next(i for i in range(len(base) - 1) if base[i]["final_score"] - base[i + 1]["final_score"] < 0.03)
    target = base[i]["case_id"]
    _run(store, "search-run", "TRANSPORT_QOS")
    for _ in range(3):
        store.add_feedback("search-run", None, None, None, None, [{"case_id": target, "relevant": False}])
    after, other_after = _search(client, SEARCH_Q), _search(client, OTHER_Q)
    rank = lambda res: next((x["rank"] for x in res if x["case_id"] == target), 99)  # noqa: E731
    assert rank(after) > rank(base)
    assert [x["case_id"] for x in other_after] == [x["case_id"] for x in other_base]  # unrelated category untouched
