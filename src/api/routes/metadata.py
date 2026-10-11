from fastapi import APIRouter, Depends

from src.api.dependencies import request_id, require_ready
from src.api.schemas import MetadataResponse
from src.services.container import ServiceContainer
from src.utils.schema import CATEGORIES, KPI_SPECS, NORMAL, PRIORITIES, SEASONS, STATE_NAMES, SYMPTOMS, WEATHER

router = APIRouter(tags=["metadata"])


@router.get("/metadata", response_model=MetadataResponse, summary="Filter vocabularies, taxonomy and KPI specs for the UI")
def metadata(c: ServiceContainer = Depends(require_ready), rid: str = Depends(request_id)) -> MetadataResponse:
    b, cases = c.baselines, c.cases
    cat_counts = cases["primary_category"].value_counts().to_dict()
    categories = [{"code": k, "name": v.name, "description": v.description, "count": int(cat_counts.get(k, 0))}
                  for k, v in CATEGORIES.items()]
    categories.append({"code": NORMAL, "name": "No significant degradation",
                       "description": "No KPI worse than the network's usual range.", "count": int(cat_counts.get(NORMAL, 0))})
    kpis = [{"name": k, "label": s.label, "unit": s.unit, "direction": s.direction, "min": s.plausible_min,
             "max": s.plausible_max, **{p: b.quantiles[k][p] for p in ("p25", "p50", "p75", "p90")}}
            for k, s in KPI_SPECS.items()]
    return MetadataResponse(
        request_id=rid,
        states=[{"code": code, "name": STATE_NAMES[code], "count": int(n)} for code, n in sorted(b.vocab["state"].items())],
        seasons=SEASONS, weather=WEATHER, categories=categories,
        symptoms=[{"code": s.code, "kpi": s.kpi, "direction": KPI_SPECS[s.kpi].direction, "label": s.label}
                  for s in SYMPTOMS.values()],
        kpis=kpis, priorities=PRIORITIES, corpus_size=len(cases))
