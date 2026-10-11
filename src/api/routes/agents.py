"""LLM-backed Requirement 1 endpoints: classification agent and basic single-pass RAG (plan §9.3 #5, #6).

Both degrade instead of failing when the LLM is missing or down: rule classification / runbook actions.
"""
from fastapi import APIRouter, Depends

from src.api.dependencies import request_id, require_ready
from src.api.schemas import ClassifyRequest, ClassifyResponse, ErrorResponse, RecommendRequest, RecommendResponse
from src.services import troubleshooting_service as service
from src.services.container import ServiceContainer

router = APIRouter(tags=["incident analysis"])
ERRORS = {400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}


def _kpis(snapshot) -> dict | None:
    kpis = snapshot.model_dump(exclude_none=True) if snapshot is not None else {}
    return kpis or None


@router.post("/classify", response_model=ClassifyResponse, responses=ERRORS,
             summary="Classify an incident description (LLM agent; rule-based when the LLM is unavailable)")
def classify(req: ClassifyRequest, c: ServiceContainer = Depends(require_ready),
             rid: str = Depends(request_id)) -> ClassifyResponse:
    return ClassifyResponse(request_id=rid, **service.classify(c, req.query, _kpis(req.kpis)))


@router.post("/recommend", response_model=RecommendResponse, responses=ERRORS,
             summary="Basic RAG: similar cases, likely causes and cited recommendations in one LLM call")
def recommend(req: RecommendRequest, c: ServiceContainer = Depends(require_ready),
              rid: str = Depends(request_id)) -> RecommendResponse:
    return RecommendResponse(request_id=rid,
                             **service.basic_recommend(c, req.query, req.filters, _kpis(req.kpis), req.top_k))
