"""Regenerate every Phase 11 result (plan Phase 11 verify).

Run from the repo root:
  python -m evaluation.run_all --suite all     # everything (Claude API: about 1 hour, never during a demo)
  python -m evaluation.run_all --suite quick   # no-LLM suites + summary (minutes)
  python -m evaluation.run_all --suite summary # rebuild summary.md only
Each suite runs as its own process so one failure is reported without stopping the others.
"""
import argparse
import subprocess
import sys
import time

QUICK = ["evaluation.run_retrieval_eval", "evaluation.run_component_eval", "evaluation.run_guardrail_eval",
         "evaluation.run_feedback_sim"]
LLM = ["evaluation.run_classification_eval --no-cache", "evaluation.run_e2e_generate", "evaluation.run_deepeval",
       "evaluation.run_judge_meta_eval"]
SUITES = {"quick": QUICK, "llm": LLM, "all": QUICK + LLM, "summary": []}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=list(SUITES), default="quick")
    args = parser.parse_args()
    results = []
    for cmd in SUITES[args.suite] + ["evaluation.make_summary"]:
        t0 = time.perf_counter()
        code = subprocess.call([sys.executable, "-m", *cmd.split()])
        results.append((cmd, code, round(time.perf_counter() - t0)))
        print(f"== {cmd}: exit {code} in {results[-1][2]} s", flush=True)
    failed = [c for c, code, _ in results if code != 0]
    print("all suites succeeded" if not failed else f"FAILED suites: {failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
