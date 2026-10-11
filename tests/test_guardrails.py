"""Guardrails: every case in guardrail_cases.json, golden queries never blocked, normalization and PII."""
import json
from pathlib import Path

import pytest

from src.services.guardrails import GuardrailError, Guardrails, normalize, redact_pii

CASES = json.loads((Path(__file__).parent / "test_cases" / "guardrail_cases.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((Path(__file__).parent / "test_cases" / "golden_queries.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def guard(small_index):
    return Guardrails(small_index[0].embedder)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_guardrail_cases(guard, case):
    if case["expect"] == "ALLOW":
        r = guard.check(case["query"])
        assert r.band in ("in_scope", "uncertain")
        for token in case.get("expect_redactions", []):
            assert token in r.text and token in r.redactions
    else:
        with pytest.raises(GuardrailError) as exc:
            guard.check(case["query"])
        assert exc.value.code == case["expect"]


def test_golden_in_scope_queries_are_never_blocked(guard):
    blocked = []
    for q in GOLDEN:
        try:
            guard.check(q["query"])
            ok = q["in_scope"]
        except GuardrailError:
            ok = not q["in_scope"]
        if not ok:
            blocked.append(q["id"])
    assert blocked == []


def test_normalize_and_redact():
    assert normalize("  high\u0000 latency ​\n\n in  TX ") == "high latency in TX"
    text, found = redact_pii("call me at (555) 123-4567 or a@b.com, IMSI 310150123456789")
    assert text == "call me at [PHONE] or [EMAIL], IMSI [NUMBER]" and set(found) == {"[PHONE]", "[EMAIL]", "[NUMBER]"}
