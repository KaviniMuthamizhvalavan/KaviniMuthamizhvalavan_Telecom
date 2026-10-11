"""DeepEval judge adapter on the project's LLM client (plan §11.5).

Uses the EVAL_LLM_* settings (Settings.eval_settings): default Claude Haiku 5.5 (cost decision, 2026-10-09; the
same model as the runtime agents). The Phase 11 run used Claude Opus 5.5 (EVAL_LLM_MODEL=claude-opus-5-5); the
NVIDIA-era judge openai/gpt-oss-20b remains available via EVAL_LLM_PROVIDER=openai_compatible. The class name is
kept for the existing imports.
Going through LLMClient gives the evaluation the same rate limiter, one JSON-repair
attempt, an on-disk cache (artifacts/llm_cache_eval.db, so reruns are free) and usage accounting. The circuit
breaker is lenient here (10 consecutive failures, 30 s cooldown): an evaluation should wait out a slow provider
rather than fail half of its metrics.

2026-10-11: through the AICredits gateway, gpt-oss-120b returned 429 on bursts of simultaneous calls (DeepEval's
contextual metrics send one call per retrieval context at once), although sequential calls were fine and the
gateway reported 1000 requests per minute remaining. So judge calls are limited to JUDGE_CONCURRENCY at a time, and
a rate-limited call (or one refused while the breaker cools down) is retried with backoff. Evaluation-only: the
runtime LLM client is unchanged.
"""
import asyncio
import re
import threading
import time

from deepeval.models import DeepEvalBaseLLM

from src.services.llm_client import CircuitBreaker, LLMClient, LLMError, LLMUnavailable, RunUsage
from src.utils.config import get_settings

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
MAX_TOKENS = 1500  # visible answer budget; the reasoning allowance below is added by LLMClient
# gpt-oss-20b reasons before answering; on long DeepEval prompts 2048 reasoning tokens truncated the reply
# (finish_reason=length, empty content) in the first Phase 11 run. Evaluation-only setting.
REASONING_ALLOWANCE = 6144
JUDGE_CONCURRENCY = 2
RETRY_WAITS_S = (5, 15, 30, 45)  # then the error is recorded for that metric, as before
_SLOTS = threading.BoundedSemaphore(JUDGE_CONCURRENCY)


def _extract_json(text: str) -> str:
    """Strip reasoning blocks and code fences; return the outermost JSON object (kept for scripts.check_env)."""
    text = _THINK.sub("", text).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


class OpenAICompatibleJudge(DeepEvalBaseLLM):
    def __init__(self, model: str | None = None, base_url: str | None = None, api_key: str | None = None,
                 use_cache: bool = True):
        s = get_settings()
        explicit = {k: v for k, v in (("llm_base_url", base_url), ("llm_api_key", api_key)) if v}  # NVIDIA only
        es = s.eval_settings(llm_timeout_s=120, llm_cache_enabled=use_cache, **explicit)
        self.model_name = model or s.eval_model
        self.llm = LLMClient(es, cache_path=s.artifacts_dir / "llm_cache_eval.db", model=self.model_name,
                             circuit=CircuitBreaker(cooldown_s=30, threshold=10))
        self.usage = RunUsage(max_calls=10**9, max_tokens=10**12)

    def load_model(self):
        return self.llm

    def generate(self, prompt: str, schema=None):
        for wait in (*RETRY_WAITS_S, None):
            try:
                with _SLOTS:
                    return self._generate(prompt, schema)
            except (LLMError, LLMUnavailable) as exc:
                retryable = "rate limited" in str(exc) or "circuit open" in str(exc)
                if wait is None or not retryable:
                    raise
                time.sleep(wait)

    def _generate(self, prompt: str, schema=None):
        messages = [{"role": "user", "content": prompt}]
        if schema is None:
            text = self.llm.chat(messages, max_tokens=MAX_TOKENS, usage=self.usage, purpose="deepeval",
                                 reasoning_allowance=REASONING_ALLOWANCE)
            return _THINK.sub("", text).strip()
        return self.llm.generate_json(messages, schema, max_tokens=MAX_TOKENS, usage=self.usage, purpose="deepeval",
                                      reasoning_allowance=REASONING_ALLOWANCE)

    async def a_generate(self, prompt: str, schema=None):
        return await asyncio.to_thread(self.generate, prompt, schema)

    def get_model_name(self) -> str:
        return self.model_name
