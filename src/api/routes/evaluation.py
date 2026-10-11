"""Evaluation results for the UI's Evaluation page (2026-10-10). Read-only: runs no evaluation, calls no LLM."""
from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_container, request_id
from src.api.schemas import EvaluationResponse
from src.services import evaluation_results
from src.services.container import ServiceContainer

router = APIRouter(tags=["evaluation"])


@router.get("/evaluation/latest", response_model=EvaluationResponse,
            summary="Latest saved evaluation results and live validation of recent runs (no LLM)")
def latest(days: int = Query(30, ge=1, le=3650, description="Window for the live-validation summary"),
           c: ServiceContainer = Depends(get_container), rid: str = Depends(request_id)) -> EvaluationResponse:
    warnings = []
    offline = evaluation_results.load_offline()
    if offline is None:
        warnings.append("No saved evaluation results yet. Run: python -m evaluation.run_all --suite all")
    live = None
    if getattr(c, "runs", None) is None:
        warnings.append("The run database is unavailable, so live validation cannot be shown.")
    else:
        live = c.runs.validation_summary(days)
    return EvaluationResponse(request_id=rid, warnings=warnings, offline=offline, live=live,
                              offline_alternatives=evaluation_results.load_alternatives())
