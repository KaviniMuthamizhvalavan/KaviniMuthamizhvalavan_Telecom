"""Build tests/test_cases/rag_golden.json (plan §11.2) from the golden queries and the authored runbooks.

Reference answers are assembled verbatim from the expected category's runbook sections (likely root causes,
corrective actions, verification), so no "correct answer" is invented here. Single labeller (3-day scope).
Run from the repo root:  python -m evaluation.build_rag_golden
"""
import json
import re

from src.rag.chunking import chunk_all
from src.utils.config import PROJECT_ROOT

GOLDEN = PROJECT_ROOT / "tests" / "test_cases" / "golden_queries.json"
OUT = PROJECT_ROOT / "tests" / "test_cases" / "rag_golden.json"
# one query per incident type + the three PRD queries (G18, G19 share FAULT_ALARM with G11)
IDS = ["G01", "G03", "G05", "G07", "G09", "G11", "G13", "G15", "G17", "G18", "G19"]
SECTIONS = ("likely-root-causes", "corrective-actions", "verification")


def items(text: str) -> list[str]:
    return [re.sub(r"^(-|\d+\.)\s+", "", line.strip()).rstrip(".") for line in text.splitlines()
            if re.match(r"^\s*(-|\d+\.)\s+", line)]


def main() -> None:
    golden = {q["id"]: q for q in json.loads(GOLDEN.read_text(encoding="utf-8"))}
    chunks = {(c.category, c.section): c for c in chunk_all()}
    cases = []
    for qid in IDS:
        q = golden[qid]
        cat = q["expected_primary"]
        parts = {sec: items(chunks[(cat, sec)].text) for sec in SECTIONS}
        reference = ("Likely causes: " + "; ".join(parts["likely-root-causes"]) + ". "
                     "Recommended actions: " + "; ".join(parts["corrective-actions"]) + ". "
                     "Verification: " + "; ".join(parts["verification"]) + ".")
        cases.append({"id": qid, "query": q["query"], "expected_primary": cat,
                      "acceptable_primary": q["acceptable_primary"], "expected_symptoms": q["expected_symptoms"],
                      "expected_kb_ids": [chunks[(cat, sec)].kb_id for sec in
                                          ("likely-root-causes", "corrective-actions", "diagnostic-checks")],
                      "reference_answer": reference,
                      "reference_source": f"verbatim runbook sections of {cat}: " + ", ".join(SECTIONS)})
    OUT.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(f"wrote {len(cases)} cases to {OUT}")


if __name__ == "__main__":
    main()
