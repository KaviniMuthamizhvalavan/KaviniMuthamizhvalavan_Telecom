"""Multi-agent troubleshooting endpoint (plan §9.3 #7, Requirement 2).

Synchronous: classification -> retrieval -> evidence tools -> analyst -> recommender -> judge (one revision).
LLM failures degrade per node and never produce a 5xx.
"""
from fastapi import APIRouter, Depends

from src.api.dependencies import request_id, require_ready
from src.api.schemas import ErrorResponse, TroubleshootRequest, TroubleshootResponse
from src.services import troubleshooting_service as service
from src.services.container import ServiceContainer

router = APIRouter(tags=["incident analysis"])


@router.post("/troubleshoot", response_model=TroubleshootResponse,
             responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
             summary="Full multi-agent analysis: classify, retrieve, root cause and impact, actions, validation")
def troubleshoot(req: TroubleshootRequest, c: ServiceContainer = Depends(require_ready),
                 rid: str = Depends(request_id)) -> TroubleshootResponse:
    kpis = req.kpis.model_dump(exclude_none=True) if req.kpis is not None else {}
    res = service.run_troubleshoot(c, req.query, req.filters, kpis or None, req.top_k, req.options.max_revisions,
                                   req.options.include_trace)
    return TroubleshootResponse(request_id=rid, **res)
