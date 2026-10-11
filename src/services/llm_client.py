"""LLM client (Anthropic Claude or OpenAI-compatible/NVIDIA): JSON outputs with one repair, rate limiter, LLM gate, cache, accounting (plan §6.4a).

Every agent talks to the LLM only through this module. Failures surface as typed errors so callers can
fall back deterministically; nothing here raises to the API layer as a 5xx.

LLM gate (circuit breaker): available = key configured AND circuit closed. 401/403 opens the circuit until
restart; 3 consecutive 429s/timeouts/connection errors open it for 5 minutes. While open, calls fail fast
with LLMUnavailable so requests take the reduced path immediately.

Providers (2026-10-09): "anthropic" uses the Messages API (top-level system prompt, adaptive / between_tools
thinking with an effort level, text content blocks, stop_reason, input/output token usage); "openai_compatible"
is the unchanged NVIDIA path, kept as the rollback. Both SDKs share exception class names.

The analyst's tool-calling round is deferred (plan §5.0) and not implemented here yet.
"""
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from src.utils.config import Settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

CIRCUIT_COOLDOWN_S = 300
CONSECUTIVE_FAILURES_TO_OPEN = 3
THINK_RE = re.compile(r"<think>.*?</think>", re.S)
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Thinking setting for reasoning OFF, per model (each model's lowest accepted setting, checked with the Models API):
# Sonnet 5.5 rejects "disabled" and takes "between_tools"; Haiku 5.5 accepts "disabled". Others (e.g. claude-opus-5-5,
# whose thinking cannot be disabled) get no thinking field and run adaptive at the low effort level.
THINKING_OFF = {"claude-sonnet-5-5": {"type": "between_tools"}, "claude-haiku-5-5": {"type": "disabled"}}
# USD per million tokens: (input, 5-minute cache write, cache read, output). Anthropic list prices, read from
# platform.claude.com/docs/en/about-claude/pricing on 2026-10-09. Used only for the daily spend cap.
PRICES = {"claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50),  # prompts up to 100K tokens (see HAIKU_LONG_PROMPT)
          "claude-sonnet-5-5": (2.0, 2.5, 0.10, 10.0), "claude-sonnet-5": (2.0, 2.5, 0.20, 10.0),
          "claude-opus-5-5": (4.0, 5.0, 0.20, 20.0), "claude-haiku-4-5": (1.0, 1.25, 0.10, 5.0)}
HAIKU_LONG_PROMPT = (100_000, (0.50, 0.625, 0.05, 2.50))  # Haiku 5.5 prompts over 100K tokens
UNKNOWN_MODEL_PRICE = (10.0, 12.5, 0.25, 50.0)  # most expensive current tier: never under-count an unlisted model
# AICredits gateway prices in INR per million tokens (input, output), read from aicredits.in/models on 2026-10-10;
# they include the gateway's forex and platform fees. Converted to USD for the shared daily cap at the rate implied
# by its Claude Haiku 5.5 price (INR 10.17 for Anthropic's $0.10).
AICREDITS_PRICES_INR = {"anthropic/claude-haiku-5.5": (10.17, 50.86), "openai/gpt-oss-120b": (3.76, 17.29),
                        "openai/gpt-4o-mini": (15.26, 61.03), "anthropic/claude-sonnet-5": (203.42, 1017.11),
                        "anthropic/claude-opus-5.5": (406.84, 2034.21)}
AICREDITS_UNKNOWN_PRICE_INR = (1525.66, 7628.29)  # the most expensive model listed: never under-count
AICREDITS_INR_PER_USD = 101.7


class LLMError(Exception):
    """Base class: any LLM problem the caller should handle with a fallback."""


class LLMUnavailable(LLMError):
    """No key, provider disabled, or circuit open."""


class LLMBudgetExceeded(LLMError):
    """The per-run call or token budget is used up."""


class StructuredOutputError(LLMError):
    """The reply was not valid JSON for the schema, even after one repair attempt."""


# ---------------------------------------------------------------------------- accounting
@dataclass
class RunUsage:
    """Per-run accounting and budget guard (MAX_LLM_CALLS_PER_RUN, MAX_TOKENS_PER_RUN)."""
    max_calls: int = 12  # defaults mirror Settings.max_llm_calls_per_run / max_tokens_per_run
    max_tokens: int = 50000
    llm_calls: int = 0
    cached_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    calls: list[dict] = field(default_factory=list)

    def check(self) -> None:
        if self.llm_calls >= self.max_calls or self.tokens_in + self.tokens_out >= self.max_tokens:
            raise LLMBudgetExceeded(f"run budget used: {self.llm_calls} calls, {self.tokens_in + self.tokens_out} tokens")

    def record(self, purpose: str, tokens_in: int, tokens_out: int, latency_ms: float, cached: bool) -> None:
        if cached:
            self.cached_calls += 1
        else:
            self.llm_calls += 1
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out
        self.latency_ms += latency_ms
        self.calls.append({"purpose": purpose, "tokens_in": tokens_in, "tokens_out": tokens_out,
                           "latency_ms": round(latency_ms, 1), "cached": cached})

    def summary(self) -> dict:
        return {"llm_calls": self.llm_calls, "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "cached_calls": self.cached_calls}


# ---------------------------------------------------------------------------- limiter and gate
class RateLimiter:
    """Process-wide sliding-window limiter: at most `rpm` request starts in any 60 s window."""

    def __init__(self, rpm: int):
        self.rpm, self._starts, self._lock = max(1, rpm), deque(), threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._starts and now - self._starts[0] >= 60:
                    self._starts.popleft()
                if len(self._starts) < self.rpm:
                    self._starts.append(now)
                    return
                wait = 60 - (now - self._starts[0])
            time.sleep(min(max(wait, 0.05), 5))


class CircuitBreaker:
    def __init__(self, cooldown_s: float = CIRCUIT_COOLDOWN_S, threshold: int = CONSECUTIVE_FAILURES_TO_OPEN):
        self.cooldown_s, self.threshold = cooldown_s, threshold
        self._lock = threading.Lock()
        self.open_until: float | None = None  # inf = until restart
        self.consecutive = 0
        self.reachable: bool | None = None  # None until the first real call
        self.last_error: str | None = None

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self.open_until is None:
                return False
            if time.monotonic() >= self.open_until:
                self.open_until, self.consecutive = None, 0  # half-open: let the next call try
                return False
            return True

    def success(self) -> None:
        with self._lock:
            self.consecutive, self.reachable, self.open_until, self.last_error = 0, True, None, None

    def failure(self, kind: str, message: str) -> None:
        with self._lock:
            self.last_error = f"{kind}: {message[:200]}"
            if kind == "auth":
                self.open_until, self.reachable = float("inf"), False
                log.error("LLM circuit opened until restart (%s)", message[:200])
                return
            self.consecutive += 1
            if self.consecutive >= self.threshold:
                self.open_until, self.reachable = time.monotonic() + self.cooldown_s, False
                log.warning("LLM circuit opened for %ss after %d consecutive %s errors", self.cooldown_s,
                            self.consecutive, kind)


# ---------------------------------------------------------------------------- cache
class LLMCache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as con:
            con.execute("CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, model TEXT, response_text TEXT,"
                        " usage_json TEXT, created_at TEXT)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def get(self, key: str) -> tuple[str, dict] | None:
        with self._lock, self._conn() as con:
            row = con.execute("SELECT response_text, usage_json FROM llm_cache WHERE key = ?", (key,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def delete(self, key: str) -> None:
        with self._lock, self._conn() as con:
            con.execute("DELETE FROM llm_cache WHERE key = ?", (key,))

    def put(self, key: str, model: str, text: str, usage: dict) -> None:
        with self._lock, self._conn() as con:
            con.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?, ?, datetime('now'))",
                        (key, model, text, json.dumps(usage)))


# ---------------------------------------------------------------------------- daily spend cap
def call_cost_usd(model: str, input_tokens: int, cache_write: int, cache_read: int, output_tokens: int) -> float:
    price = PRICES.get(model, UNKNOWN_MODEL_PRICE)
    if model == "claude-haiku-5-5" and input_tokens + cache_write + cache_read > HAIKU_LONG_PROMPT[0]:
        price = HAIKU_LONG_PROMPT[1]
    return (input_tokens * price[0] + cache_write * price[1] + cache_read * price[2] + output_tokens * price[3]) / 1e6


class SpendLedger:
    """Estimated API spend per UTC day and model, shared by every process that uses the same artifacts folder
    (the app and the evaluation scripts). Costs come from list prices, not from the Anthropic bill."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as con:
            con.execute("CREATE TABLE IF NOT EXISTS spend (day TEXT, model TEXT, calls INTEGER, cost_usd REAL,"
                        " PRIMARY KEY (day, model))")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def day() -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def add(self, model: str, cost_usd: float) -> None:
        with self._lock, self._conn() as con:
            con.execute("INSERT INTO spend VALUES (?, ?, 1, ?) ON CONFLICT (day, model) DO UPDATE SET"
                        " calls = calls + 1, cost_usd = cost_usd + excluded.cost_usd", (self.day(), model, cost_usd))

    def today(self) -> float:
        with self._lock, self._conn() as con:
            row = con.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM spend WHERE day = ?", (self.day(),)).fetchone()
        return float(row[0])

    def report(self, days: int = 7) -> list[tuple]:
        with self._lock, self._conn() as con:
            return con.execute("SELECT day, model, calls, ROUND(cost_usd, 4) FROM spend WHERE day >= date('now', ?)"
                               " ORDER BY day DESC, model", (f"-{days} days",)).fetchall()


# ---------------------------------------------------------------------------- JSON helpers
def extract_json(text: str) -> str:
    """Strip <think> blocks and code fences; return the outermost JSON object."""
    text = THINK_RE.sub("", text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def _accepts(validate: Callable[[str], object], text: str) -> bool:
    try:
        validate(text)
        return True
    except (ValidationError, ValueError):
        return False


def schema_hint(model: type[BaseModel]) -> str:
    """Compact JSON schema for the system prompt."""
    return json.dumps(model.model_json_schema(), separators=(",", ":"))


def aicredits_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = AICREDITS_PRICES_INR.get(model, AICREDITS_UNKNOWN_PRICE_INR)
    return (tokens_in * price_in + tokens_out * price_out) / 1e6 / AICREDITS_INR_PER_USD


def _read_anthropic(resp, model: str) -> tuple[str, str, dict, str | None]:
    """(text of the text blocks, stop_reason, token usage incl. estimated cost, refusal category or None). Thinking
    blocks are skipped. Input tokens include cache writes and reads; output tokens include thinking. The cost uses the
    model that served the reply (a refusal fallback can switch it), else the requested model."""
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    u = resp.usage
    fresh, write, read = (getattr(u, f, 0) or 0 for f in ("input_tokens", "cache_creation_input_tokens",
                                                          "cache_read_input_tokens"))
    out = u.output_tokens or 0
    served = getattr(resp, "model", None) if getattr(resp, "model", None) in PRICES else model
    refusal = None
    if resp.stop_reason == "refusal":
        refusal = getattr(getattr(resp, "stop_details", None), "category", None) or "unspecified"
    return text, resp.stop_reason, {"tokens_in": fresh + write + read, "tokens_out": out,
                                    "cost_usd": call_cost_usd(served, fresh, write, read, out)}, refusal


# ---------------------------------------------------------------------------- client
class LLMClient:
    def __init__(self, settings: Settings, cache_path: Path | None = None, model: str | None = None,
                 limiter: RateLimiter | None = None, circuit: CircuitBreaker | None = None,
                 spend_ledger: SpendLedger | None = None):
        self.s = settings
        self.provider = settings.llm_provider
        self.model = model or settings.runtime_model
        self.limiter = limiter or RateLimiter(settings.llm_rpm_limit)
        self.circuit = circuit or CircuitBreaker()
        self.cache = LLMCache(cache_path) if (cache_path and settings.llm_cache_enabled) else None
        self._client = None
        self.spend_ledger = spend_ledger  # Claude and AICredits (set below); NVIDIA is the free tier
        if settings.llm_configured and self.provider == "anthropic":
            from anthropic import Anthropic
            self._client = Anthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_s,
                                     max_retries=settings.llm_max_retries)
            self.spend_ledger = spend_ledger or SpendLedger(settings.artifacts_dir / "llm_spend.db")
        elif settings.llm_configured:  # OpenAI-compatible: AICredits gateway or NVIDIA
            from openai import OpenAI
            self._client = OpenAI(base_url=settings.runtime_base_url, api_key=settings.runtime_api_key,
                                  timeout=settings.llm_timeout_s, max_retries=settings.llm_max_retries)
            if self.provider == "aicredits":
                self.spend_ledger = spend_ledger or SpendLedger(settings.artifacts_dir / "llm_spend.db")

    @property
    def configured(self) -> bool:
        return self._client is not None

    @property
    def spend_cap_reached(self) -> bool:
        """Today's estimated Claude spend (all processes sharing the ledger) has reached LLM_DAILY_BUDGET_USD."""
        return self.spend_ledger is not None and self.spend_ledger.today() >= self.s.llm_daily_budget_usd

    @property
    def available(self) -> bool:
        """The LLM gate: key configured, circuit closed and the daily spend cap not reached. While it is closed,
        requests take the reduced (no-LLM) path."""
        return self.configured and not self.circuit.is_open and not self.spend_cap_reached

    def new_usage(self) -> RunUsage:
        return RunUsage(max_calls=self.s.max_llm_calls_per_run, max_tokens=self.s.max_tokens_per_run)

    # ------------------------------------------------------------------ plain chat
    def chat(self, messages: list[dict], *, max_tokens: int, usage: RunUsage | None = None, purpose: str = "chat",
             json_mode: bool = False, use_cache: bool = True, prompt_version: str = "",
             reasoning: bool | None = None, reasoning_allowance: int | None = None,
             validate: Callable[[str], object] | None = None) -> str:
        """reasoning: per-call thinking switch for reasoning models; None = the LLM_REASONING default.
        validate: if given, only replies it accepts are cached, and a cached reply it rejects is evicted and
        re-requested (a malformed reply must never be replayed from the cache)."""
        if not self.available:
            if not self.configured:
                raise LLMUnavailable("LLM not configured")
            if self.spend_cap_reached:
                log.warning("llm %s refused: daily spend cap of $%.2f reached", purpose, self.s.llm_daily_budget_usd)
                raise LLMUnavailable(f"daily API spend cap of ${self.s.llm_daily_budget_usd:.2f} reached")
            raise LLMUnavailable("LLM circuit open")
        if usage is not None:
            usage.check()
        think = self.s.llm_reasoning if reasoning is None else reasoning
        # AICredits cannot switch thinking off, so every call there may think: always reserve the reasoning allowance
        # (2026-10-10: the classifier hit its 400-token cap and needed a repair). A ceiling only; billing is per
        # token actually generated.
        reserve = think or self.provider == "aicredits"
        budget = max_tokens + ((reasoning_allowance or self.s.llm_reasoning_allowance) if reserve else 0)
        if self.provider == "anthropic":
            params = self._anthropic_params(messages, budget, think)
            key_parts = ["anthropic", params, prompt_version]
        elif self.provider == "aicredits":
            # No thinking control is exposed by the gateway (no chat_template_kwargs); Claude models get no
            # temperature (recent Claude models reject non-default sampling); JSON mode is documented.
            params = {"model": self.model, "max_tokens": budget}
            if not self.model.startswith("anthropic/"):
                params["temperature"] = self.s.llm_temperature
            if json_mode and self.s.llm_json_mode:
                params["response_format"] = {"type": "json_object"}
            extra = {}
            key_parts = [self.s.aicredits_base_url, messages, params, prompt_version]
        else:  # unchanged, so the NVIDIA cache entries stay valid for a rollback
            params = {"model": self.model, "temperature": self.s.llm_temperature, "max_tokens": budget}
            if json_mode and self.s.llm_json_mode:
                params["response_format"] = {"type": "json_object"}
            extra = {} if think else {"chat_template_kwargs": {"enable_thinking": False}}
            key_parts = [self.s.llm_base_url, messages, params, extra, prompt_version]
        key = hashlib.sha256(json.dumps(key_parts, sort_keys=True).encode()).hexdigest()
        if use_cache and self.cache:
            hit = self.cache.get(key)
            if hit and validate is not None and not _accepts(validate, hit[0]):
                log.warning("llm %s: evicting a cached reply that fails validation", purpose)
                self.cache.delete(key)
                hit = None
            if hit:
                if usage is not None:
                    usage.record(purpose, hit[1].get("tokens_in", 0), hit[1].get("tokens_out", 0), 0.0, cached=True)
                return hit[0]

        if self.provider == "anthropic":
            from anthropic import (APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError,
                                   PermissionDeniedError, RateLimitError)
        else:
            from openai import (APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError,
                                PermissionDeniedError, RateLimitError)
        self.limiter.acquire()
        t0 = time.perf_counter()
        try:
            if self.provider == "anthropic":
                create = self._client.beta.messages.create if "betas" in params else self._client.messages.create
                text, finish, u, refusal = _read_anthropic(create(**params), self.model)
            else:
                resp = self._client.chat.completions.create(messages=messages, extra_body=extra or None, **params)
                text, finish, refusal = resp.choices[0].message.content or "", resp.choices[0].finish_reason, None
                u = {"tokens_in": getattr(resp.usage, "prompt_tokens", 0) or 0,
                     "tokens_out": getattr(resp.usage, "completion_tokens", 0) or 0}
                if self.provider == "aicredits":
                    u["cost_usd"] = aicredits_cost_usd(self.model, u["tokens_in"], u["tokens_out"])
        except (AuthenticationError, PermissionDeniedError) as exc:
            self.circuit.failure("auth", str(exc))
            raise LLMUnavailable(f"LLM authentication failed: {exc}") from exc
        except RateLimitError as exc:
            self.circuit.failure("rate_limit", str(exc))
            retry_after = exc.response.headers.get("retry-after") if exc.response is not None else None
            raise LLMError(f"LLM rate limited (retry-after={retry_after}): {exc}") from exc
        except (APITimeoutError, APIConnectionError) as exc:
            self.circuit.failure("timeout", str(exc))
            raise LLMError(f"LLM unreachable: {exc}") from exc
        except APIStatusError as exc:
            if exc.status_code == 402:  # prepaid credits used up (AICredits): stop calling until restart
                self.circuit.failure("auth", str(exc))
                raise LLMUnavailable(f"LLM credits exhausted (402): {exc}") from exc
            if exc.status_code >= 500:
                self.circuit.failure("server", str(exc))
            raise LLMError(f"LLM error {exc.status_code}: {exc}") from exc
        latency = (time.perf_counter() - t0) * 1000
        self.circuit.success()
        if self.spend_ledger is not None and "cost_usd" in u:  # billed even when the reply is a refusal
            self.spend_ledger.add(self.model, u["cost_usd"])
        if usage is not None:
            usage.record(purpose, u["tokens_in"], u["tokens_out"], latency, cached=False)
        log.info("llm %s model=%s in=%d out=%d %.0fms finish=%s cost=$%.6f", purpose, self.model, u["tokens_in"],
                 u["tokens_out"], latency, finish, u.get("cost_usd", 0.0))
        if refusal is not None:  # declined (after any server-side fallback): the caller uses its node fallback
            raise LLMError(f"LLM declined the request (category={refusal})")
        if not text.strip():
            raise StructuredOutputError(f"empty reply (finish_reason={finish})")
        if use_cache and self.cache and (validate is None or _accepts(validate, text)):
            self.cache.put(key, self.model, text, u)
        return text

    def _anthropic_params(self, messages: list[dict], max_tokens: int, think: bool) -> dict:
        """Messages API request. System messages become the top-level system prompt (in order). No temperature:
        Claude Sonnet 5.5 rejects non-default sampling. No JSON mode: the schema instruction is in the prompt."""
        params = {"model": self.model, "max_tokens": max_tokens,
                  "system": "\n\n".join(m["content"] for m in messages if m["role"] == "system"),
                  "messages": [m for m in messages if m["role"] != "system"],
                  "output_config": {"effort": self.s.anthropic_effort_reasoning if think else self.s.anthropic_effort}}
        if think:
            params["thinking"] = {"type": "adaptive"}
        elif self.model in THINKING_OFF:
            params["thinking"] = THINKING_OFF[self.model]
        if self.s.anthropic_refusal_fallback:
            params.update(betas=[REFUSAL_FALLBACK_BETA], fallbacks="default")
        return params

    # ------------------------------------------------------------------ JSON with one repair
    def generate_json(self, messages: list[dict], schema: type[T], *, max_tokens: int,
                      usage: RunUsage | None = None, purpose: str = "json", prompt_version: str = "",
                      reasoning: bool | None = None, reasoning_allowance: int | None = None) -> T:
        system = {"role": "system", "content": "Respond with a single JSON object only, no prose, matching this JSON "
                                                f"schema:\n{schema_hint(schema)}"}
        msgs = [system, *messages]
        text = ""
        try:
            text = self.chat(msgs, max_tokens=max_tokens, usage=usage, purpose=purpose, json_mode=True,
                             prompt_version=prompt_version, reasoning=reasoning,
                             reasoning_allowance=reasoning_allowance,
                             validate=lambda t: schema.model_validate_json(extract_json(t)))
            return schema.model_validate_json(extract_json(text))
        except (ValidationError, ValueError, StructuredOutputError) as first:
            error = first
        log.warning("llm %s: invalid JSON, one repair attempt (%s)", purpose, str(error)[:200])
        repair = [*msgs, {"role": "assistant", "content": text or "(empty)"},
                  {"role": "user", "content": f"That reply was invalid: {str(error)[:600]}\n"
                                              "Return only the corrected JSON object."}]
        try:
            text = self.chat(repair, max_tokens=max_tokens, usage=usage, purpose=f"{purpose}_repair",
                             json_mode=True, use_cache=False, prompt_version=prompt_version, reasoning=reasoning,
                             reasoning_allowance=reasoning_allowance)
            return schema.model_validate_json(extract_json(text))
        except (ValidationError, ValueError, StructuredOutputError) as exc:
            raise StructuredOutputError(f"{purpose}: invalid JSON after repair: {str(exc)[:300]}") from exc
