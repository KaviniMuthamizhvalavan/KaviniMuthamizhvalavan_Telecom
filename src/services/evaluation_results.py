"""Read-only view of the saved evaluation results for GET /evaluation/latest (2026-10-10).

Reads the files written by `python -m evaluation.run_all` into evaluation/results/final/. It never runs an
evaluation and never calls an LLM; a missing file just leaves its section empty.

2026-10-11: also reads optional additional runs (ALTERNATIVE_DIRS), each a complete results folder for another model
configuration. They are served next to the final results, never merged into them; a folder that does not exist yet
is skipped.
"""
import csv
import json
import logging
from collections import Counter
from pathlib import Path

from src.utils.config import PROJECT_ROOT

log = logging.getLogger(__name__)

RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results" / "final"
# Additional configurations, by folder id. The demo setup (Claude Haiku 5.5 via AICredits, gpt-oss-120b judge) is
# written here by its own run so that final/ (Sonnet 5.5 agents, Opus 5.5 judge) stays unchanged.
ALTERNATIVE_DIRS = (PROJECT_ROOT / "evaluation" / "results" / "runs" / "aicredits_haiku_demo",)
METRIC_LABELS = {"faithfulness": "Faithfulness", "answer_relevancy": "Answer relevancy",
                 "contextual_relevancy": "Contextual relevancy", "contextual_precision": "Contextual precision",
                 "contextual_recall": "Contextual recall", "actionability_geval": "Recommendation actionability",
                 "diagnosis_validity_geval": "Diagnosis validity"}
E2E_KEYS = ("n", "C_latency_s", "A_latency_s", "C_llm_calls", "C_tokens", "A_tokens_mean", "C_repair_calls",
            "C_fallback_events", "C_runs_final_degraded", "C_json_failure_rate", "C_verdicts", "C_revision_rate")


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("evaluation results: cannot read %s (%s)", path.name, exc)
        return None


def _opt(path: Path):
    return _json(path) if path.exists() else None


def _num(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def load_offline(results_dir: Path | None = None) -> dict | None:
    """The latest saved evaluation, or None when no summary has been generated yet."""
    d = Path(results_dir or RESULTS_DIR)
    headline = _opt(d / "summary.json")
    if headline is None:
        return None
    rows = [{"component": r.get("Component"), "metric": r.get("Metric"), "value": r.get("Value"),
             "target": r.get("Target"), "status": r.get("Status")} for r in headline]
    out = {"headline": rows, "totals": dict(Counter(r["status"] for r in rows))}
    cfg = _opt(d / "run_config.json")
    if cfg:
        out.update(generated_utc=cfg.get("generated_utc"), models=cfg.get("models"),
                   dataset={k: (cfg.get("dataset") or {}).get(k) for k in ("source", "cases")})
    deepeval = d / "deepeval" / "deepeval_summary.csv"
    if deepeval.exists():
        with deepeval.open(encoding="utf-8", newline="") as fh:
            out["deepeval"] = [{"system": r["system"], "metric": r["metric"],
                                "label": METRIC_LABELS.get(r["metric"], r["metric"]),
                                **{k: _num(r[k]) for k in ("n", "scored", "mean", "pass_rate", "errors")}}
                               for r in csv.DictReader(fh)]
    e2e = _opt(d / "e2e" / "e2e_summary.json")
    if e2e:
        out["end_to_end"] = {k: e2e.get(k) for k in E2E_KEYS}
    meta = _opt(d / "judge_meta" / "judge_meta_summary.json")
    if meta:
        out["judge_meta"] = {k: meta.get(k) for k in ("n_seeded", "detection_rate", "detected_and_matched_rate",
                                                      "controls", "control_false_alarms", "by_error")}
    usage = _opt(d / "deepeval" / "deepeval_judge_usage.json")
    if usage:
        out["judge_usage"] = usage
    if d.resolve() == Path(RESULTS_DIR).resolve():
        files = ("evaluation/results/final/EVALUATION_REPORT.md", "docs/Evaluation_Report.pdf")
    else:
        files = tuple(p.relative_to(PROJECT_ROOT).as_posix() for p in sorted(d.glob("*.md")) if _inside_project(p))
    out["report_files"] = [p for p in files if (PROJECT_ROOT / p).exists()]
    return out


def _inside_project(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
        return True
    except ValueError:
        return False


def load_alternatives(dirs=None) -> list[dict]:
    """Every additional configuration that has results, each tagged with its folder id. Empty when none exist."""
    out = []
    for d in (ALTERNATIVE_DIRS if dirs is None else dirs):
        d = Path(d)
        off = load_offline(d) if d.is_dir() else None
        if off is not None:
            out.append({"id": d.name, **off})
    return out
