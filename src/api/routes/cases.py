import re

from fastapi import APIRouter, Depends, Path

from src.api.dependencies import request_id, require_ready
from src.api.errors import NotFoundError
from src.api.schemas import CaseResponse, ErrorResponse
from src.rag.documents import build_case_text
from src.services.container import ServiceContainer
from src.services.kpi_analyzer import BAND_NAMES, CATEGORY_LIST
from src.services.prioritization import LEVEL_NAMES
from src.utils.schema import COLUMN_MAP, KPI_SPECS, SEVERITY_KPIS, SYMPTOMS

router = APIRouter(tags=["retrieval"])
_RAW_BY_NORM = {v: k for k, v in COLUMN_MAP.items()}


def _py(v):
    return v.item() if hasattr(v, "item") else v


@router.get("/cases/{case_id}", response_model=CaseResponse, summary="Full historical case record and assessment",
            responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
def get_case(case_id: str = Path(examples=["CASE-004217"]), c: ServiceContainer = Depends(require_ready),
             rid: str = Depends(request_id)) -> CaseResponse:
    case_id = case_id.strip().upper()
    if not re.fullmatch(r"CASE-\d{6}", case_id) or case_id not in c.case_index:
        raise NotFoundError(f"case {case_id}")
    row = c.cases.iloc[c.case_index[case_id]]
    normalized = {norm: _py(row[norm]) for norm in COLUMN_MAP.values()}
    raw = {_RAW_BY_NORM[k]: v for k, v in normalized.items()}
    raw["Issue Reported"] = "yes" if normalized["issue_reported"] else "no"
    per_kpi = [{"kpi": k, "label": KPI_SPECS[k].label, "value": float(row[k]), "unit": KPI_SPECS[k].unit,
                "percentile": round(float(row[f"bad_{k}"]), 4), "band": BAND_NAMES[int(row[f"sev_{k}"])]}
               for k in SEVERITY_KPIS]
    return CaseResponse(
        request_id=rid, case_id=case_id, raw=raw, normalized=normalized, assessment={"per_kpi": per_kpi},
        symptoms=[s for s in SYMPTOMS if bool(row[f"sym_{s}"])],
        env_tags=[t for t in ("adverse_weather", "extreme_temperature", "high_humidity") if bool(row[f"env_{t}"])],
        category_scores={cat: round(float(row[f"score_{cat}"]), 3) for cat in CATEGORY_LIST},
        primary_category=row["primary_category"],
        secondary_categories=[x for x in (row["secondary_1"], row["secondary_2"]) if x],
        priority={"level": row["priority"], "label": LEVEL_NAMES[row["priority"]],
                  "score": round(float(row["priority_score"]), 3),
                  "components": {"severity": round(float(row["severity_score"]), 3),
                                 "impact": round(float(row["impact_score"]), 3),
                                 "risk": round(float(row["fault_risk_prob"]), 3)}},
        fault_risk_prob=round(float(row["fault_risk_prob"]), 4), fault_risk_band=row["fault_risk_band"],
        narrative=build_case_text(row))
