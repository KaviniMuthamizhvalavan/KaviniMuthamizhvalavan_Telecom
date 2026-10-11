"""Section-label citations (2026-10-09): "IMPACT & PRIORITY" is an evidence section of the analyst pack and of the
judge's digest, so citing it is valid. Invented IDs are still removed and still fail the citations_valid rule."""
from src.rag import context_builder
from tests.test_agents_graph import Router, container, run  # noqa: F401 (container is a fixture)


class SectionCitingRouter(Router):
    def __init__(self, extra_citations, **kw):
        super().__init__(**kw)
        self.extra = extra_citations

    def __call__(self, kwargs):
        out = super().__call__(kwargs)
        if self.seen[-1][0] == "analyst":
            hyp = {**out["hypotheses"][0], "citations": out["hypotheses"][0]["citations"] + self.extra}
            out = {**out, "hypotheses": [hyp]}
        return out


def citations_rule(r):
    return next(x for x in r["validation"]["rule_checks"] if x["rule"] == "citations_valid")


def test_impact_and_priority_is_a_citable_section():
    assert "IMPACT & PRIORITY" in context_builder.SECTION_CITATIONS


def test_impact_and_priority_citation_is_kept(container):
    r = run(container, SectionCitingRouter(["IMPACT & PRIORITY"]))
    assert "IMPACT & PRIORITY" in r["root_cause_analysis"]["hypotheses"][0]["citations"]
    assert citations_rule(r)["passed"]


def test_invented_runbook_id_is_still_removed(container):
    r = run(container, SectionCitingRouter(["IMPACT & PRIORITY", "KB-NOT_A_REAL-section"]))
    cites = r["root_cause_analysis"]["hypotheses"][0]["citations"]
    assert "IMPACT & PRIORITY" in cites and "KB-NOT_A_REAL-section" not in cites
    rule = citations_rule(r)
    assert not rule["passed"] and "KB-NOT_A_REAL-section" in rule["detail"] and "IMPACT" not in rule["detail"]
