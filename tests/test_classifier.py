"""Classification agent: LLM post-processing, rule fallback, KPI reconciliation, clarification routing."""
from src.agents.classifier_agent import build_prompt, classify, rule_classify
from src.services.kpi_analyzer import Baselines, assess
from src.utils.config import get_settings
from tests.fakes import FakeLLM, openai_error

LLM_REPLY = {"primary_category": "MOBILITY_HANDOVER", "secondary_categories": ["RADIO_COVERAGE", "MOBILITY_HANDOVER"],
             "symptoms": ["low_handover_success", "high_call_drop", "made_up_symptom"],
             "filters": {"state": ["Ohio", "Atlantis"], "season": ["autumn"], "weather": ["Fog"]},
             "severity_hint": "high", "in_scope": True, "needs_clarification": False, "confidence": 0.9,
             "rationale": "Handover failures and dropped calls."}


def test_llm_output_is_cleaned():
    c, warnings, degraded = classify(FakeLLM([LLM_REPLY]), "Calls drop during handover in Ohio this autumn")
    assert not degraded and c.source == "llm"
    assert c.symptoms == ["low_handover_success", "high_call_drop"]
    assert c.secondary_categories == ["RADIO_COVERAGE"]
    assert c.filters.state == ["OH"] and c.filters.season == ["Fall"] and c.filters.weather == []
    assert any("made_up_symptom" in w for w in warnings) and any("Atlantis" in w for w in warnings)


def test_llm_failure_falls_back_to_rules():
    llm = FakeLLM([openai_error("InternalServerError", 500)])
    c, warnings, degraded = classify(llm, "Handover success rate is low on a highway site in Ohio")
    assert degraded and c.source == "rules" and c.primary_category == "MOBILITY_HANDOVER"
    assert c.filters.state == ["OH"] and warnings


def test_no_llm_uses_rules_and_vague_query_needs_clarification():
    c, _, degraded = classify(None, "Something is wrong with the network")
    assert degraded and c.needs_clarification and c.clarification_question


def test_low_confidence_llm_without_symptoms_asks_for_clarification():
    reply = {**LLM_REPLY, "symptoms": [], "confidence": 0.2, "primary_category": "NORMAL", "secondary_categories": []}
    c, _, _ = classify(FakeLLM([reply]), "Something is wrong with the network")
    assert c.needs_clarification and c.clarification_question


def test_kpi_evidence_wins_on_symptoms():
    b = Baselines.from_json(get_settings().artifacts_dir / "baselines.json")
    a = assess({"latency_ms": 180, "jitter_ms": 40, "packet_loss_pct": 14, "handover_success_pct": 99.9}, b)
    reply = {**LLM_REPLY, "symptoms": ["low_handover_success", "high_alarms"]}
    c, _, _ = classify(FakeLLM([reply]), "Handover problems and alarms", a)
    assert c.source == "merged"
    assert "low_handover_success" not in c.symptoms  # KPI says handover is fine
    assert "high_alarms" in c.symptoms  # alarm KPI not provided: the text symptom stays
    assert {"high_latency", "high_packet_loss"} <= set(c.symptoms)
    assert c.primary_category == a["primary_category"]


def test_rule_classify_and_prompt():
    r = rule_classify("Alarm storm with many critical alarms and frequent faults")
    assert r.primary_category == "FAULT_ALARM" and r.source == "rules" and not r.needs_clarification
    prompt = build_prompt(None)
    assert "TRANSPORT_QOS" in prompt and "high_packet_loss" in prompt and "{{" not in prompt


def test_llm_clarification_flag_is_overridden_when_a_symptom_is_present():
    """Plan §8.2: clarify only if confidence < 0.4 AND no symptoms (Phase 8 defect: PRD query 2 stopped)."""
    reply = {**LLM_REPLY, "primary_category": "FAULT_ALARM", "secondary_categories": [], "symptoms": ["high_alarms"],
             "confidence": 0.55, "needs_clarification": True,
             "clarification_question": "Which specific KPIs are affected besides alarm counts?"}
    c, _, _ = classify(FakeLLM([reply]), "Multiple cells have poor service quality and increasing alarm counts")
    assert not c.needs_clarification and c.clarification_question is None and c.symptoms == ["high_alarms"]
