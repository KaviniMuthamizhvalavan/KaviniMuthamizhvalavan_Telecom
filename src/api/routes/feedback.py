"""Feedback capture and summary (plan §9.3 #11-12, §8.6). No LLM; comments are PII-redacted and never sent to one."""
from fastapi import APIRouter, Depends, Query

from src.api.dependencies import request_id, require_ready
from src.api.errors import ApiError, NotFoundError
from src.api.schemas import ErrorResponse, FeedbackRequest, FeedbackResponse, FeedbackSummaryResponse
from src.services.container import ServiceContainer
from src.services.guardrails import normalize, redact_pii

router = APIRouter(tags=["feedback"])


def _store(c: ServiceContainer):
    if c.runs is None:
        raise ApiError(503, "NOT_READY", "The feedback database is unavailable.", {"error": c.errors.get("database")})
    return c.runs


@router.post("/feedback", response_model=FeedbackResponse, summary="Rate a run and mark similar cases relevant or not",
             responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
def submit(req: FeedbackRequest, c: ServiceContainer = Depends(require_ready),
           rid: str = Depends(request_id)) -> FeedbackResponse:
    store = _store(c)
    if store.get_run(req.run_id) is None:
        raise NotFoundError(f"run {req.run_id}")
    votes = [v.model_dump() for v in req.case_feedback or []]
    unknown = [v["case_id"] for v in votes if v["case_id"] not in c.case_index]
    if unknown:
        raise ApiError(422, "INVALID_INPUT", "Unknown case IDs in case_feedback.", {"unknown": unknown})
    warnings, comment = [], None
    if req.comment:
        comment, found = redact_pii(normalize(req.comment))
        if found:
            warnings.append(f"Personal data was removed from the comment ({', '.join(found)}).")
    out = store.add_feedback(req.run_id, req.rating, req.helpful, req.corrected_category, comment, votes)
    return FeedbackResponse(request_id=rid, warnings=warnings, accepted=True, **out)


@router.get("/feedback/summary", response_model=FeedbackSummaryResponse,
            summary="Aggregated feedback: ratings, helpful rate, most down-voted cases, trend")
def summary(days: int = Query(30, ge=1, le=3650), c: ServiceContainer = Depends(require_ready),
            rid: str = Depends(request_id)) -> FeedbackSummaryResponse:
    return FeedbackSummaryResponse(request_id=rid, **_store(c).summary(days))
