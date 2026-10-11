"""Typed application settings loaded from environment variables and `.env` (plan §6.3)."""
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # Runtime LLM provider: "aicredits" (default since 2026-10-10: Claude Haiku 5.5 through the AICredits gateway, for
    # development and testing) | "anthropic" (Claude direct, e.g. for the demo: LLM_PROVIDER=anthropic) |
    # "openai_compatible" (NVIDIA API catalog rollback) | "none" (zero-key reduced mode).
    llm_provider: str = "aicredits"
    # AICredits (aicredits.in): OpenAI-compatible gateway, prepaid INR credits (the balance is a hard spending cap).
    # No thinking control is exposed, so the per-agent reasoning switches do not apply to this provider.
    aicredits_api_key: str = Field(default="", validation_alias=AliasChoices("AICREDITS_API_KEY"))
    aicredits_base_url: str = "https://api.aicredits.in/v1"
    aicredits_model: str = "anthropic/claude-haiku-5.5"
    # Claude: one model for every agent. Reasoning ON -> adaptive thinking at anthropic_effort_reasoning; reasoning
    # OFF -> thinking {"type": "between_tools"} (Sonnet 5.5 cannot disable thinking; this is its lowest setting).
    anthropic_api_key: str = Field(default="", validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
    # 2026-10-09 cost decision: Haiku 5.5 ($0.10/$0.50 per MTok) for every runtime agent; Sonnet 5.5 was $2/$10.
    anthropic_model: str = "claude-haiku-5-5"
    anthropic_effort_reasoning: str = "medium"  # analyst, judge (and basic RAG when LLM_REASONING=true)
    anthropic_effort: str = "low"  # classifier, recommender (between_tools needs effort high or below)
    # Server-side refusal fallback (beta): a declined request is retried on another model inside the same call.
    anthropic_refusal_fallback: bool = True
    # OpenAI-compatible (NVIDIA) settings: only used when LLM_PROVIDER / EVAL_LLM_PROVIDER = openai_compatible
    llm_base_url: str = "https://integrate.api.nvidia.com/v1"
    # NVIDIA_API_KEY is accepted as an alias so the key can keep its provider-specific name.
    llm_api_key: str = Field(default="", validation_alias=AliasChoices("LLM_API_KEY", "NVIDIA_API_KEY"))
    # meta/llama-3.3-70b-instruct was retired by NVIDIA on 2026-08-26; replacement verified in Phase 0.
    # Nemotron 3 Super is a reasoning model: give it generous max_tokens or replies can be empty.
    llm_model: str = "nvidia/nemotron-3-super-120b-a12b"
    judge_llm_model: str = ""  # empty -> llm_model
    llm_temperature: float = 0.1
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2  # SDK retries on 429/5xx/timeouts; kept low so a failing provider degrades quickly
    llm_json_mode: bool = True
    # Reasoning (thinking) on/off for reasoning models; the allowance is added to every max_tokens budget so the
    # hidden reasoning cannot consume the answer (Nemotron returns an empty reply otherwise).
    llm_reasoning: bool = True
    # Per-agent reasoning (approved option B, Phase 8): off for the classifier and recommender, on for the
    # analyst and judge. Basic RAG (/recommend) keeps the LLM_REASONING default.
    classifier_reasoning: bool = False
    analyst_reasoning: bool = True
    recommender_reasoning: bool = False
    judge_reasoning: bool = True
    # Analyst and judge (reasoning ON): 2048 truncated their JSON mid-output in the Phase 8 run.
    agent_reasoning_allowance: int = 4096
    llm_reasoning_allowance: int = 2048  # measured: basic RAG needs ~1.4-1.9k tokens incl. reasoning
    llm_cache_enabled: bool = True
    llm_rpm_limit: int = 35
    # P1 (2026-10-09): 4 agents + 3 revision calls + up to 4 analyst/agent repair calls = 11, plus headroom.
    # 8 refused G05's final judge call in Phase 11 (repairs count against the cap). Tokens remain capped at 50K.
    max_llm_calls_per_run: int = 12
    max_tokens_per_run: int = 50000  # reasoning tokens count; 30K stopped valid runs
    # Daily cap on estimated Claude API spend (list prices, UTC day, shared by the app and the evaluation scripts via
    # artifacts/llm_spend.db). Once reached, requests take the reduced (no-LLM) path until the next UTC day.
    llm_daily_budget_usd: float = 1.0

    # Independent evaluation judge (DeepEval, troubleshoot re-score); never used by the running application.
    # Default (2026-10-09, cost decision): Claude Haiku 5.5, the cheapest model. It is the same model as the runtime
    # agents, so it is no longer an independent judge (documented in EVALUATION_REPORT.md). The Phase 11 run used
    # claude-opus-5-5 (EVAL_LLM_MODEL=claude-opus-5-5 to repeat it). NVIDIA rollback:
    # EVAL_LLM_PROVIDER=openai_compatible, EVAL_LLM_MODEL=openai/gpt-oss-20b (the Phase 8/11 NVIDIA-era judge).
    # 2026-10-10: openai/gpt-oss-120b through AICredits, a different model family from the runtime agents (Claude),
    # so the evaluation judge is independent again. Phase 11 used claude-opus-5-5 via EVAL_LLM_PROVIDER=anthropic.
    eval_llm_provider: str = "aicredits"  # "aicredits" | "anthropic" | "openai_compatible"
    eval_llm_model: str = "openai/gpt-oss-120b"
    eval_llm_effort: str = "medium"  # Claude effort for the evaluation judge (reasoning on)
    eval_llm_base_url: str = ""  # openai_compatible only; empty -> llm_base_url
    eval_llm_api_key: str = ""  # empty -> the evaluation provider's key (AICREDITS_, ANTHROPIC_ or NVIDIA_API_KEY)

    # Retrieval
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    data_source: str = "full"  # "sample" | "full"
    artifacts_dir: Path = PROJECT_ROOT / "artifacts"
    top_k: int = 5
    candidate_k: int = 50
    rrf_k: int = 60
    w_dense: float = 1.0
    w_sparse: float = 1.0
    rerank_symptom_weight: float = 0.3
    rerank_feedback_weight: float = 0.1
    max_revisions: int = 1

    log_level: str = "INFO"

    @property
    def runtime_model(self) -> str:
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        if self.llm_provider == "aicredits":
            return self.aicredits_model
        return self.llm_model if self.llm_provider == "openai_compatible" else "none"  # "none": zero-key mode

    @property
    def runtime_base_url(self) -> str:
        """Endpoint of the OpenAI-compatible providers (AICredits or NVIDIA)."""
        return self.aicredits_base_url if self.llm_provider == "aicredits" else self.llm_base_url

    @property
    def runtime_api_key(self) -> str:
        return {"anthropic": self.anthropic_api_key, "aicredits": self.aicredits_api_key}.get(self.llm_provider,
                                                                                            self.llm_api_key)

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider != "none" and bool(self.runtime_api_key)

    @property
    def eval_model(self) -> str:
        return self.eval_llm_model or self.runtime_model

    def eval_settings(self, **overrides) -> "Settings":
        """Settings for an LLMClient acting as the independent evaluation judge (EVAL_LLM_*), separate from the
        runtime agents and the runtime judge."""
        if self.eval_llm_provider == "anthropic":
            update = {"llm_provider": "anthropic", "anthropic_model": self.eval_model,
                      "anthropic_api_key": self.eval_llm_api_key or self.anthropic_api_key,
                      "anthropic_effort_reasoning": self.eval_llm_effort}
        elif self.eval_llm_provider == "aicredits":
            update = {"llm_provider": "aicredits", "aicredits_model": self.eval_model,
                      "aicredits_api_key": self.eval_llm_api_key or self.aicredits_api_key,
                      "aicredits_base_url": self.eval_llm_base_url or self.aicredits_base_url}
        else:
            update = {"llm_provider": "openai_compatible", "llm_model": self.eval_model,
                      "llm_base_url": self.eval_llm_base_url or self.llm_base_url,
                      "llm_api_key": self.eval_llm_api_key or self.llm_api_key}
        return self.model_copy(update={**update, **overrides})


@lru_cache
def get_settings() -> Settings:
    return Settings()
