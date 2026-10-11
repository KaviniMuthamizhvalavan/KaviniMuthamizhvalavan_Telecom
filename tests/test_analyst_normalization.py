"""P3 (2026-10-09): analyst-output normalization. Payload shapes are the ones that failed in Phase 11.

Normalization fixes shape only, never invents content; semantically invalid replies are still rejected, so the
repair call and the deterministic fallback keep working. The JSON schema (part of the prompt) must not change.
"""
import hashlib
import json

import pytest
from pydantic import ValidationError

from src.agents import analyst_agent
from src.agents.analyst_agent import AnalystOutput
from tests.fakes import FakeLLM
from tests.test_agents_graph import Router, container, run  # noqa: F401 (container is a fixture)

SCHEMA_SHA256 = "4f95fb781223dee829c0a4b43ec84dcd88fb14a115f3fc7054bd497f462caeae"  # before P3 (prompt + cache key)


def hyp(cause, **kw):
    return {"cause": cause, "likelihood": "high", "evidence_type": "both", "supporting_evidence": ["latency 150 ms"],
            "citations": ["KB-TRANSPORT_QOS-likely-root-causes"], **kw}


def reply(**kw):
    base = {"hypotheses": [hyp("Backhaul congestion"), hyp("Degraded fibre link"), hyp("QoS misconfiguration")],
            "contributing_factors": [{"factor": "weather", "direction": "increases risk", "evidence": "lift 2.1x",
                                      "citation": "SEGMENT STATS"}],
            "impact_narrative": "Real-time services are affected.", "data_limitations": ["No timestamps."]}
    return {**base, **kw}


def test_schema_and_therefore_prompt_unchanged():
    digest = hashlib.sha256(json.dumps(AnalystOutput.model_json_schema(), sort_keys=True).encode()).hexdigest()
    assert digest == SCHEMA_SHA256


def test_valid_reply_is_untouched():
    out = AnalystOutput.model_validate(reply())
    assert out._normalizations == [] and out._raw is None


def test_citation_list_becomes_first_item():  # Phase 11 G05 round 1 / G19
    data = reply(contributing_factors=[{"factor": "weather", "direction": "up", "evidence": "lift",
                                        "citation": ["PREDICTIONS", "SEGMENT STATS"]}])
    out = AnalystOutput.model_validate(data)
    assert out.contributing_factors[0].citation == "PREDICTIONS"
    assert out._normalizations == ["contributing_factors[0].citation: list of 2 -> first item"]
    assert out._raw == data and data["contributing_factors"][0]["citation"] == ["PREDICTIONS", "SEGMENT STATS"]


def test_garbled_items_dropped_when_the_rest_is_complete():  # Phase 11 "7 hypotheses" pattern
    data = reply()
    data["hypotheses"] = data["hypotheses"] + ["contributing_factors': [{", "factor", "direction", "citation"]
    out = AnalystOutput.model_validate(data)
    assert [h.cause for h in out.hypotheses] == ["Backhaul congestion", "Degraded fibre link", "QoS misconfiguration"]
    assert out._normalizations == ["hypotheses: dropped 4 non-object item(s)"]


def test_overlong_lists_keep_model_order():
    data = reply(hypotheses=[hyp(f"Cause {i}") for i in range(5)],
                 contributing_factors=[{"factor": f"f{i}", "direction": "up", "evidence": "e"} for i in range(8)])
    out = AnalystOutput.model_validate(data)
    assert [h.cause for h in out.hypotheses] == ["Cause 0", "Cause 1", "Cause 2"] and len(out.contributing_factors) == 6
    assert "hypotheses: kept the first 3 of 5" in out._normalizations


def test_string_fields_become_lists():
    data = reply(hypotheses=[hyp("A", supporting_evidence="latency 150 ms", citations="KPI ASSESSMENT")],
                 data_limitations="No timestamps.")
    out = AnalystOutput.model_validate(data)
    assert out.hypotheses[0].supporting_evidence == ["latency 150 ms"] and out.data_limitations == ["No timestamps."]
    assert len(out._normalizations) == 3


@pytest.mark.parametrize("bad", [
    {"hypotheses": [hyp("A"), "contributing_factors': [{"]},                          # G17: garbled AND fields missing
    reply(hypotheses=["junk", "more junk"]),                                         # nothing usable left
    reply(hypotheses=[{"likelihood": "high", "evidence_type": "data"}]),             # object missing its cause
    reply(hypotheses=[hyp("   ")]),                                                  # empty cause
    reply(hypotheses=[hyp("Backhaul congestion"), hyp("backhaul congestion ")]),     # duplicate cause
    reply(hypotheses=[hyp("A", likelihood="certain")]),                              # invalid enum
    reply(impact_narrative="  "),                                                    # empty narrative
], ids=["g17-missing-fields", "all-junk", "missing-cause", "empty-cause", "duplicate", "bad-enum", "empty-narrative"])
def test_semantically_invalid_output_is_still_rejected(bad):
    with pytest.raises(ValidationError):
        AnalystOutput.model_validate(bad)


def test_normalized_reply_needs_no_repair_and_raw_text_is_cached(tmp_path):
    data = reply(contributing_factors=[{"factor": "w", "direction": "up", "evidence": "e", "citation": ["PREDICTIONS"]}])
    llm = FakeLLM([data], cache_path=tmp_path / "c.db")
    usage = llm.new_usage()
    out = llm.generate_json([{"role": "user", "content": "x"}], AnalystOutput, max_tokens=10, usage=usage)
    assert usage.llm_calls == 1 and not any(c["purpose"].endswith("_repair") for c in usage.calls)
    assert out.contributing_factors[0].citation == "PREDICTIONS"
    with llm.cache._conn() as con:
        cached = con.execute("SELECT response_text FROM llm_cache").fetchone()[0]
    assert json.loads(cached) == data  # the raw (pre-normalization) reply is what is preserved


def test_invalid_reply_still_goes_to_repair_then_raises(tmp_path):
    from src.services.llm_client import StructuredOutputError
    g17 = {"hypotheses": [hyp("A"), "garbage"]}
    llm = FakeLLM([g17, g17], cache_path=tmp_path / "c.db")
    with pytest.raises(StructuredOutputError):
        llm.generate_json([{"role": "user", "content": "x"}], AnalystOutput, max_tokens=10)
    assert len(llm.calls) == 2  # first attempt + exactly one repair, as before


def test_audit_record_keeps_raw_reply(tmp_path, monkeypatch):
    monkeypatch.setattr(analyst_agent, "normalization_log_path", lambda: tmp_path / "norm.jsonl")
    data = reply(contributing_factors=[{"factor": "w", "direction": "up", "evidence": "e", "citation": ["PREDICTIONS"]}])
    out = AnalystOutput.model_validate(data)
    analyst_agent._audit_normalization(out._normalizations, out._raw)
    rec = json.loads((tmp_path / "norm.jsonl").read_text(encoding="utf-8").strip())
    assert rec["agent"] == "analyst" and rec["normalizations"] == out._normalizations and rec["raw"] == data


def test_graph_normalization_end_to_end(container, monkeypatch, tmp_path):
    monkeypatch.setattr(analyst_agent, "normalization_log_path", lambda: tmp_path / "norm.jsonl")

    class ListCitationRouter(Router):
        def __call__(self, kwargs):
            out = super().__call__(kwargs)
            if self.seen[-1][0] == "analyst":
                out = {**out, "contributing_factors": [{**f, "citation": [f["citation"]]}
                                                       for f in out["contributing_factors"]]}
            return out

    router = ListCitationRouter()
    r = run(container, router)
    assert r["status"] == "ok" and r["meta"]["llm_calls"] == 4  # no repair call was needed
    assert [t["status"] for t in r["trace"] if t["node"] == "analyze"] == ["ok"]
    assert r["root_cause_analysis"]["contributing_factors"][0]["citation"] == "SEGMENT STATS"
    assert "normalizations" not in r["root_cause_analysis"]  # API contract unchanged
    rec = json.loads((tmp_path / "norm.jsonl").read_text(encoding="utf-8").strip())
    assert rec["normalizations"] == ["contributing_factors[0].citation: list of 1 -> first item"]
