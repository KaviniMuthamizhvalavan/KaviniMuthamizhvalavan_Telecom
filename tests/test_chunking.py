from src.rag.chunking import approx_tokens, chunk_all, load_kb
from src.utils.schema import CATEGORIES, NORMAL

REQUIRED_SECTIONS = {"overview", "kpi-signature", "likely-root-causes", "diagnostic-checks", "corrective-actions",
                     "verification", "escalation-criteria"}


def test_one_runbook_per_category():
    cats = {d.category for d in load_kb()}
    assert cats == set(CATEGORIES) | {NORMAL}


def test_chunks_unique_bounded_and_complete():
    chunks = chunk_all()
    ids = [c.kb_id for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(approx_tokens(c.text) <= 400 + 60 for c in chunks)  # max + header + overlap
    for cat in [*CATEGORIES, NORMAL]:
        sections = {c.section for c in chunks if c.category == cat}
        assert REQUIRED_SECTIONS <= sections, (cat, REQUIRED_SECTIONS - sections)


def test_chunk_text_carries_context_header():
    c = chunk_all()[0]
    assert c.text.startswith("Runbook: ") and " > " in c.text.splitlines()[0]
