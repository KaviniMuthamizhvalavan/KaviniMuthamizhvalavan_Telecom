"""Evaluation package.

DeepEval telemetry (2026-10-09): DeepEval decides at import time, from os.environ only, whether to send telemetry
(PostHog events, Sentry, an OpenTelemetry exporter to New Relic). It does not read `.env`. Every evaluation entry
point imports this package before DeepEval, so the opt-out is set here: an explicitly exported value wins, then the
DEEPEVAL_TELEMETRY_OPT_OUT line in `.env`, and the default is opted out.
"""
import os

if "DEEPEVAL_TELEMETRY_OPT_OUT" not in os.environ:
    from dotenv import dotenv_values

    from src.utils.config import PROJECT_ROOT

    os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = (
        dotenv_values(PROJECT_ROOT / ".env").get("DEEPEVAL_TELEMETRY_OPT_OUT") or "YES")
