"""Run the evaluation suites with every output redirected to a separate results folder (2026-10-11).

Used to measure another model configuration next to evaluation/results/final/ without touching it, for example the
demo setup (Claude Haiku 5.5 via AICredits, gpt-oss-120b judge):

  python -m evaluation.run_variant --out evaluation/results/runs/aicredits_haiku_demo --suite all

Each suite runs in its own process, as in run_all, with its module-level output path pointed at the new folder.
The models come from .env as usual (LLM_PROVIDER, AICREDITS_MODEL, EVAL_LLM_PROVIDER, EVAL_LLM_MODEL). The folder
may never be evaluation/results/final/. The Quality page lists any folder in
src/services/evaluation_results.ALTERNATIVE_DIRS that has a summary.json.
"""
import argparse
import importlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

from src.utils.config import PROJECT_ROOT

FINAL = PROJECT_ROOT / "evaluation" / "results" / "final"
# module -> (path constant, subfolder of the results folder)
REDIRECT = {"evaluation.run_retrieval_eval": ("DEFAULT_OUT", "retrieval"),
            "evaluation.run_component_eval": ("OUT", "components"),
            "evaluation.run_guardrail_eval": ("OUT", "guardrails"),
            "evaluation.run_feedback_sim": ("OUT", "feedback"),
            "evaluation.run_classification_eval": ("OUT", "classification"),
            "evaluation.run_e2e_generate": ("OUT", "deepeval"),
            "evaluation.run_deepeval": ("DIR", "deepeval"),
            "evaluation.run_judge_meta_eval": ("DIR", ""),
            "evaluation.make_summary": ("F", "")}
QUICK = ["evaluation.run_retrieval_eval", "evaluation.run_component_eval", "evaluation.run_guardrail_eval",
         "evaluation.run_feedback_sim"]
LLM = ["evaluation.run_classification_eval --no-cache", "evaluation.run_e2e_generate", "evaluation.run_deepeval",
       "evaluation.run_judge_meta_eval"]
SUITES = {"quick": QUICK, "llm": LLM, "all": QUICK + LLM, "summary": []}


def results_dir(path: str) -> Path:
    out = (PROJECT_ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if out == FINAL.resolve() or FINAL.resolve() in out.parents:
        raise SystemExit("refusing to write into evaluation/results/final/: choose another folder")
    return out


def run_one(out: Path, module: str, args: list[str]) -> None:
    """In-process: point the module's output constant at the new folder, then call its main()."""
    const, sub = REDIRECT[module]
    mod = importlib.import_module(module)
    target = out / sub if sub else out
    target.mkdir(parents=True, exist_ok=True)
    setattr(mod, const, target)
    print(f"[redirect] {module}.{const} -> {target}", flush=True)
    sys.argv = [module, *args]
    mod.main()


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--one":  # child process: --one <out> <module> [args]
        run_one(results_dir(sys.argv[2]), sys.argv[3], sys.argv[4:])
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--suite", choices=list(SUITES), default="all")
    args = parser.parse_args()
    out = results_dir(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # The ML holdout metrics come from training (Phase 3), not from an evaluation script, and the models are
    # unchanged, so they are copied for the summary and marked as copied.
    if (FINAL / "ml").is_dir() and not (out / "ml").exists():
        shutil.copytree(FINAL / "ml", out / "ml")
        (out / "ml" / "COPIED_FROM_FINAL.txt").write_text(
            "Copied from evaluation/results/final/ml/: holdout metrics of the unchanged scikit-learn models (no LLM).\n",
            encoding="utf-8")
    results = []
    for cmd in SUITES[args.suite] + ["evaluation.make_summary"]:
        t0 = time.perf_counter()
        code = subprocess.call([sys.executable, "-m", "evaluation.run_variant", "--one", str(out), *cmd.split()])
        results.append((cmd, code, round(time.perf_counter() - t0)))
        print(f"== {cmd}: exit {code} in {results[-1][2]} s", flush=True)
    failed = [c for c, code, _ in results if code != 0]
    print("all suites succeeded" if not failed else f"FAILED suites: {failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
