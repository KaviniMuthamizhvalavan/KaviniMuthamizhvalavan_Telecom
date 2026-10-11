from fastapi import APIRouter, Depends

from src.api.dependencies import request_id, require_ready
from src.api.schemas import ErrorResponse, SearchRequest, SearchResponse
from src.services import troubleshooting_service as service
from src.services.container import ServiceContainer

router = APIRouter(tags=["retrieval"])


@router.post("/search", response_model=SearchResponse, summary="Hybrid similar-case search with metadata filters (no LLM)",
             responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
def search(req: SearchRequest, c: ServiceContainer = Depends(require_ready), rid: str = Depends(request_id)) -> SearchResponse:
    res = service.search(c, req.query, req.filters, req.top_k, req.mode, req.use_rule_expansion)
    return SearchResponse(request_id=rid, **res)
