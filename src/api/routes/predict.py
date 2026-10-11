"""Deterministic decision-support endpoints: prioritization and both ML predictions (no LLM)."""
from fastapi import APIRouter, Depends

from src.api.dependencies import request_id, require_ready
from src.api.errors import ApiError
from src.api.schemas import ErrorResponse, FaultRiskResponse, KPIRequest, PerformanceResponse, PrioritizeResponse
from src.services.container import ServiceContainer
from src.services.kpi_analyzer import assess
from src.services.prioritization import prioritize as prioritize_snapshot

router = APIRouter(tags=["decision support"])
ERRORS = {422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}
MIN_KPIS_FOR_PRIORITY = 3


def _kpis(req: KPIRequest) -> dict:
    return req.kpis.model_dump(exclude_none=True)


@router.post("/prioritize", response_model=PrioritizeResponse, responses=ERRORS,
             summary="P1-P4 priority with reasons for a KPI snapshot")
def prioritize(req: KPIRequest, c: ServiceContainer = Depends(require_ready),
               rid: str = Depends(request_id)) -> PrioritizeResponse:
    kpis = _kpis(req)
    numeric = [k for k in kpis if k not in ("season", "weather")]
    if len(numeric) < MIN_KPIS_FOR_PRIORITY:
        raise ApiError(422, "INVALID_INPUT", f"Provide at least {MIN_KPIS_FOR_PRIORITY} KPI values to prioritize.",
                       {"provided": numeric})
    assessment = assess(kpis, c.baselines)
    risk = c.predictor.predict_fault_risk(kpis)["probability"]
    warnings = ["Severity is relative to this network's history, not absolute thresholds."]
    return PrioritizeResponse(request_id=rid, warnings=warnings,
                              priority=prioritize_snapshot(assessment, risk, c.baselines),
                              anomalies=assessment["anomalies"], fault_risk_prob=risk,
                              imputed_fields=assessment["imputed_fields"])


@router.post("/predict/fault-risk", response_model=FaultRiskResponse, responses=ERRORS,
             summary="Probability of a top-quartile fault occurrence rate")
def fault_risk(req: KPIRequest, c: ServiceContainer = Depends(require_ready),
               rid: str = Depends(request_id)) -> FaultRiskResponse:
    return FaultRiskResponse(request_id=rid, **c.predictor.predict_fault_risk(_kpis(req)))


@router.post("/predict/performance", response_model=PerformanceResponse, responses=ERRORS,
             summary="Expected throughput for the given conditions (and deficit if observed throughput is given)")
def performance(req: KPIRequest, c: ServiceContainer = Depends(require_ready),
                rid: str = Depends(request_id)) -> PerformanceResponse:
    return PerformanceResponse(request_id=rid, **c.predictor.predict_performance(_kpis(req)))
