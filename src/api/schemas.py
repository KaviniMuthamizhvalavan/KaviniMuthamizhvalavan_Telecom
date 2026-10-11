"""Request/response models for the API contract (plan §9). Examples feed the OpenAPI docs."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from src.agents.analyst_agent import ContributingFactor, Hypothesis
from src.agents.classifier_agent import Classification
from src.agents.recommender_agent import Escalation, Recommendation
from src.rag.filters import SearchFilters
from src.services.troubleshooting_service import BasicAnswer
from src.utils.schema import CATEGORY_CODES, KPI_SPECS, SEASONS, WEATHER

# ---------------------------------------------------------------- shared
_kpi_fields: dict[str, Any] = {
    name: (float | None, Field(default=None, ge=spec.plausible_min, le=spec.plausible_max,
                               description=f"{spec.label} ({spec.unit})"))
    for name, spec in KPI_SPECS.items()
}
_kpi_fields["season"] = (Literal[tuple(SEASONS)] | None, Field(default=None))
_kpi_fields["weather"] = (Literal[tuple(WEATHER)] | None, Field(default=None))
KPISnapshot = create_model("KPISnapshot", __config__=ConfigDict(extra="forbid"), **_kpi_fields)
KPISnapshot.__doc__ = "KPI snapshot; every field optional and range-checked. Missing values are imputed with dataset medians."


class ApiResponse(BaseModel):
    request_id: str = ""
    warnings: list[str] = []


# ---------------------------------------------------------------- health / metadata
class HealthResponse(BaseModel):
    status: Literal["ok", "not_ready"]
    ready: bool
    data_source: str
    components: dict[str, Any]
    versions: dict[str, str]


class StateInfo(BaseModel):
    code: str
    name: str
    count: int


class CategoryInfo(BaseModel):
    code: str
    name: str
    description: str
    count: int


class SymptomInfo(BaseModel):
    code: str
    kpi: str
    direction: int
    label: str


class KPIInfo(BaseModel):
    name: str
    label: str
    unit: str
    direction: int
    min: float = Field(description="validation lower bound enforced by the API")
    max: float = Field(description="validation upper bound enforced by the API")
    p25: float
    p50: float
    p75: float
    p90: float


class MetadataResponse(ApiResponse):
    states: list[StateInfo]
    seasons: list[str]
    weather: list[str]
    categories: list[CategoryInfo]
    symptoms: list[SymptomInfo]
    kpis: list[KPIInfo]
    priorities: list[str]
    corpus_size: int


# ---------------------------------------------------------------- search
class SearchRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "query": "high latency and packet loss with reduced throughput",
        "filters": {"state": ["TX"], "season": ["Winter"]}, "top_k": 5, "mode": "hybrid_rerank"}]})
    query: str = Field(min_length=5, max_length=1000)
    filters: SearchFilters | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal["hybrid_rerank", "hybrid", "dense", "bm25"] = "hybrid_rerank"
    use_rule_expansion: bool = True


class Anomaly(BaseModel):
    kpi: str
    label: str
    value: float
    unit: str
    band: Literal["degraded", "critical"]
    percentile: float


class ScoreBreakdown(BaseModel):
    dense_rank: int | None
    bm25_rank: int | None
    rrf: float
    symptom_overlap: float
    feedback_prior: float


class CaseResult(BaseModel):
    rank: int
    case_id: str
    final_score: float
    score_breakdown: ScoreBreakdown
    state: str
    city: str
    season: str
    weather: str
    primary_category: str
    secondary_categories: list[str]
    priority: str
    fault_risk_band: str
    anomalies: list[Anomaly]
    summary: str


class Parsed(BaseModel):
    symptoms: list[str]
    filters: dict[str, list[str]]


class SearchResponse(ApiResponse):
    query: str
    mode: str
    parsed: Parsed
    applied_filters: dict[str, Any]
    expansion_terms: list[str]
    total_candidates: int
    timings_ms: dict[str, float]
    results: list[CaseResult]


# ---------------------------------------------------------------- cases
class PerKPI(BaseModel):
    kpi: str
    label: str
    value: float
    unit: str
    percentile: float
    band: Literal["normal", "degraded", "critical"]


class CasePriority(BaseModel):
    level: str
    label: str
    score: float
    components: dict[str, float]


class CaseResponse(ApiResponse):
    case_id: str
    raw: dict[str, Any]
    normalized: dict[str, Any]
    assessment: dict[str, list[PerKPI]]
    symptoms: list[str]
    env_tags: list[str]
    category_scores: dict[str, float]
    primary_category: str
    secondary_categories: list[str]
    priority: CasePriority
    fault_risk_prob: float
    fault_risk_band: str
    narrative: str


# ---------------------------------------------------------------- prioritize / predict
class KPIRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"kpis": {
        "latency_ms": 131, "packet_loss_pct": 12.9, "throughput_mbps": 312, "alarm_count": 13,
        "user_count": 7075, "data_usage_gb": 25.8, "season": "Winter", "weather": "Snow"}}]})
    kpis: KPISnapshot


class PriorityDetail(BaseModel):
    level: str
    label: str
    score: float
    components: dict[str, float]
    overrides: list[str]
    reasons: list[str]


class PrioritizeResponse(ApiResponse):
    priority: PriorityDetail
    anomalies: list[dict[str, Any]]
    fault_risk_prob: float
    imputed_fields: list[str]


class Driver(BaseModel):
    feature: str
    importance: float
    value: Any
    band: str | None
    imputed: bool


class FaultRiskResponse(ApiResponse):
    probability: float
    band: Literal["Low", "Medium", "High"]
    definition: str
    top_drivers: list[Driver]
    imputed_fields: list[str]
    model: dict[str, Any]


class PerformanceResponse(ApiResponse):
    expected_throughput_mbps: float
    observed_throughput_mbps: float | None
    deficit_pct: float | None
    assessment: Literal["below_expected", "as_expected", "above_expected"] | None
    model: dict[str, Any]
    imputed_fields: list[str]


# ---------------------------------------------------------------- classify / recommend (LLM-backed)
class Usage(BaseModel):
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cached_calls: int = 0


class ClassifyRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "query": "Calls drop when users move between cells, handover failures are rising in Ohio"}]})
    query: str = Field(min_length=5, max_length=1000)
    kpis: KPISnapshot | None = None


class ClassifyResponse(ApiResponse):
    status: Literal["ok", "degraded", "needs_clarification"]
    classification: Classification
    kpi_assessment: dict[str, Any] | None = None
    usage: Usage


class RecommendRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "query": "A cell is experiencing high latency, packet loss, and reduced throughput",
        "filters": {"season": ["Winter"]}, "top_k": 5}]})
    query: str = Field(min_length=5, max_length=1000)
    filters: SearchFilters | None = None
    kpis: KPISnapshot | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class Source(BaseModel):
    id: str
    type: Literal["case", "runbook"]
    title: str
    snippet: str
    score: float | None = None


class RecommendResponse(ApiResponse):
    run_id: str
    status: Literal["ok", "degraded"]
    parsed: Parsed
    similar_cases: list[CaseResult]
    answer: BasicAnswer
    priority: PriorityDetail | None
    sources: list[Source]
    usage: Usage


# ---------------------------------------------------------------- troubleshoot (multi-agent, Requirement 2)
class TroubleshootOptions(BaseModel):
    max_revisions: Literal[0, 1] = 1
    include_trace: bool = True


class TroubleshootRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "query": "A cell is experiencing high latency, packet loss, and reduced throughput. "
                 "What similar network conditions have occurred before?",
        "top_k": 5, "options": {"max_revisions": 1, "include_trace": True}}]})
    query: str = Field(min_length=5, max_length=1000)
    filters: SearchFilters | None = None
    kpis: KPISnapshot | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    options: TroubleshootOptions = Field(default_factory=TroubleshootOptions)


class KPIAssessmentView(BaseModel):
    basis: Literal["provided_kpis", "similar_cases_median"]
    anomalies: list[dict[str, Any]]
    imputed_fields: list[str]


class SegmentStatsView(BaseModel):
    count: int
    top_lifts: list[dict[str, Any]]
    priority_mix: dict[str, float]
    median_fault_rate: float | None


class RootCauseAnalysis(BaseModel):
    hypotheses: list[Hypothesis]
    contributing_factors: list[ContributingFactor]
    data_limitations: list[str]


class ImpactView(BaseModel):
    level: str | None
    affected_services: list[str]
    users_served: int | None
    data_gb: float | None
    narrative: str


class FaultRiskView(BaseModel):
    probability: float
    band: Literal["Low", "Medium", "High"]
    top_drivers: list[Driver]
    basis: str


class PerformanceView(BaseModel):
    expected_throughput_mbps: float
    observed: float | None
    deficit_pct: float | None
    model_r2: float


class RuleCheck(BaseModel):
    rule: str
    passed: bool
    critical: bool
    target: str
    detail: str


class Validation(BaseModel):
    verdict: Literal["pass", "fail", "unvalidated"]
    scores: dict[str, float]
    issues: list[dict[str, Any]]
    revisions: int
    rule_checks: list[RuleCheck]
    summary: str = ""


class TraceEntry(BaseModel):
    node: str
    ms: float
    llm_calls: int
    tokens_in: int
    tokens_out: int
    tool_calls: list[str]
    status: str


class RunMeta(BaseModel):
    model: str
    judge_model: str
    prompt_version: str
    latency_ms: float
    llm_calls: int
    tokens_in: int
    tokens_out: int
    cached_calls: int


class TroubleshootResponse(ApiResponse):
    run_id: str
    status: Literal["ok", "degraded", "needs_clarification"]
    classification: Classification
    applied_filters: dict[str, Any]
    similar_cases: list[CaseResult]
    kpi_assessment: KPIAssessmentView | None
    segment_stats: SegmentStatsView | None
    root_cause_analysis: RootCauseAnalysis | None
    impact: ImpactView | None
    fault_risk: FaultRiskView | None
    performance_prediction: PerformanceView | None
    priority: PriorityDetail | None
    recommendations: list[Recommendation]
    escalation: Escalation | None
    validation: Validation | None
    sources: list[Source]
    trace: list[TraceEntry]
    meta: RunMeta
    usage: Usage


# ---------------------------------------------------------------- feedback (Phase 9)
class CaseVote(BaseModel):
    case_id: str = Field(pattern=r"^CASE-\d{6}$")
    relevant: bool


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "run_id": "3f2a...", "rating": 4, "helpful": True,
        "case_feedback": [{"case_id": "CASE-000123", "relevant": False}]}]})
    run_id: str = Field(min_length=1)
    rating: int | None = Field(default=None, ge=1, le=5)
    helpful: bool | None = None
    corrected_category: Literal[tuple(CATEGORY_CODES)] | None = None
    comment: str | None = Field(default=None, max_length=1000)
    case_feedback: list[CaseVote] | None = None

    @model_validator(mode="after")
    def _not_empty(self):
        if all(v in (None, []) for v in (self.rating, self.helpful, self.corrected_category, self.comment,
                                         self.case_feedback)):
            raise ValueError("Provide at least one of rating, helpful, corrected_category, comment, case_feedback.")
        return self


class FeedbackResponse(ApiResponse):
    feedback_id: int
    accepted: bool
    effects: dict[str, Any]


class FeedbackSummaryResponse(ApiResponse):
    total_runs: int
    total_feedback: int
    avg_rating: float | None
    helpful_rate: float | None
    by_category: list[dict[str, Any]]
    most_downvoted_cases: list[dict[str, Any]]
    corrections_count: int
    trend: list[dict[str, Any]]


class EvaluationResponse(ApiResponse):
    """Saved offline evaluation (evaluation/results/final/) and live runtime-judge outcomes of stored runs."""
    offline: dict[str, Any] | None
    live: dict[str, Any] | None
    # 2026-10-11: other saved configurations (same shape as offline, plus "id"); empty until such a run exists
    offline_alternatives: list[dict[str, Any]] = []


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}
    request_id: str = ""


class ErrorResponse(BaseModel):
    error: ErrorBody
