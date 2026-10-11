from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_container
from src.agents.graph import PROMPT_VERSIONS
from src.api.schemas import HealthResponse
from src.rag.documents import TEMPLATE_VERSION
from src.services.container import ServiceContainer

router = APIRouter(tags=["system"])
APP_VERSION = "0.1.0"


def _llm_reachable(c: ServiceContainer) -> bool:
    """Deep check: one lightweight request (model lookup, no tokens) to confirm the key, endpoint and model ID."""
    s = c.settings
    try:
        if s.llm_provider == "anthropic":
            from anthropic import Anthropic
            Anthropic(api_key=s.anthropic_api_key, timeout=15, max_retries=0).models.retrieve(s.runtime_model)
            return True
        from openai import OpenAI
        ids = {m.id for m in OpenAI(base_url=s.runtime_base_url, api_key=s.runtime_api_key, timeout=15,
                                    max_retries=0).models.list().data}
        return s.runtime_model in ids
    except Exception:
        return False


@router.get("/health", response_model=HealthResponse, summary="Liveness, readiness and component status")
def health(deep: bool = Query(False, description="Also make one lightweight LLM API request"),
           c: ServiceContainer = Depends(get_container)) -> HealthResponse:
    s = c.settings
    store_info = {"ok": c.store is not None}
    if c.store is not None:
        from src.rag.vector_store import CASES, KB
        store_info.update(cases_count=c.store.count(CASES), kb_count=c.store.count(KB))
    # Without ?deep: the LLM gate's state (None before the first call, False while the circuit is open).
    if deep and s.llm_configured:
        reachable = _llm_reachable(c)
    else:
        reachable = c.llm.circuit.reachable if c.llm is not None else None
    return HealthResponse(
        status="ok" if c.ready else "not_ready", ready=c.ready, data_source=s.data_source,
        components={"vector_store": store_info,
                    "keyword_index": {"ok": c.retriever is not None},
                    "models": {"fault_risk": c.predictor is not None, "performance": c.predictor is not None},
                    "database": {"ok": c.runs is not None},
                    "llm": {"provider": s.llm_provider, "model": s.runtime_model, "configured": s.llm_configured,
                            "reachable": reachable},
                    "missing": c.missing},
        versions={"app": APP_VERSION, "prompt": ",".join(PROMPT_VERSIONS.values()),
                  "narrative_template": TEMPLATE_VERSION, "embedding_model": s.embedding_model})
