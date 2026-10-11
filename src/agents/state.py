"""Shared typed state (blackboard) for the troubleshooting graph (plan §8.7).

Each node reads declared keys and writes only its own; agents never message each other directly. The judge
talks back through `revision_instructions`, addressed to a specific agent.
"""
from typing import Any, TypedDict


class TroubleshootState(TypedDict, total=False):
    # request and routing
    request: dict  # {query, filters, kpis, top_k, max_revisions}
    guardrail: dict  # {text, band, relevance}
    route: str  # full | reduced
    classification: dict
    rejected: bool
    applied_filters: dict
    # evidence (deterministic tools)
    similar_cases: list[dict]
    total_candidates: int
    assessment: dict | None
    kpi_basis: str
    segment_stats: dict
    fault_risk: dict | None
    performance: dict | None
    impact: dict | None
    priority: dict | None
    kb_analyst: list[dict]
    kb_recommender: list[dict]
    # agent outputs
    analysis: dict | None
    recommendations: list[dict]
    removed_rec_citations: list[str]
    escalation: dict | None
    validation: dict
    sources: list[dict]
    allowed_ids: list[str]
    # control
    revision_count: int
    revision_instructions: dict  # {"analyst": [...], "recommender": [...]}
    next_after_judge: str
    status: str  # ok | degraded | needs_clarification
    degraded_steps: list[str]
    warnings: list[str]
    trace: list[dict]
    usage: Any  # RunUsage (shared across nodes)
