"""DeepEval telemetry stays off (2026-10-09): importing the evaluation package before DeepEval sets the opt-out, so no
telemetry client is created and no connection is attempted. Runs in a fresh interpreter because DeepEval decides at
import time."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = """
import socket, sys
attempts = []
def blocked(self, addr):
    attempts.append(addr)
    raise OSError("blocked")
socket.socket.connect = blocked
import evaluation.deepeval_judge
import deepeval.telemetry as t
print(t.telemetry_opt_out(), "span_processor" in vars(t), "posthog" in vars(t), len(attempts))
"""


def run_check(**env_overrides) -> str:
    env = {k: v for k, v in os.environ.items() if k != "DEEPEVAL_TELEMETRY_OPT_OUT"} | env_overrides
    out = subprocess.run([sys.executable, "-c", CHECK], cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip().splitlines()[-1]


def test_evaluation_import_turns_deepeval_telemetry_off():
    assert run_check() == "True False False 0"  # opted out, no exporter, no PostHog client, no connection


def test_an_explicitly_exported_value_is_respected():
    assert os.environ.get("DEEPEVAL_TELEMETRY_OPT_OUT") in (None, "YES")  # the test process itself stays opted out
    assert run_check(DEEPEVAL_TELEMETRY_OPT_OUT="YES").startswith("True")
