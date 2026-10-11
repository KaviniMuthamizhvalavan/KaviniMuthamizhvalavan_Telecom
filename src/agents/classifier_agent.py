"""Network Incident Classification Agent (plan §8.2, Requirement 1).

LLM path: one JSON call (classifier_v1 prompt), then deterministic post-processing (vocabulary checks, state
normalization, KPI reconciliation). Fallback and reduced mode: rule_classify() over the rule parser, with the
same output shape and source="rules".
"""
import logging
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.rag.filters import _NAME_TO_CODE
from src.services import query_parser
from src.services.llm_client import LLMClient, LLMError, RunUsage
from src.utils.schema import CATEGORIES, CATEGORY_CODES, NORMAL, SEASONS, STATE_NAMES, SYMPTOMS, WEATHER

log = logging.getLogger(__name__)
PROMPT_VERSION = "classifier_v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
MAX_TOKENS = 400
CLARIFY_CONFIDENCE = 0.4
TIE_MARGIN = 0.05  # KPI category scores within 5% count as tied; the text then decides
CLARIFY_QUESTION = ("Which symptoms or KPIs are affected (for example latency, packet loss, throughput, dropped "
                    "calls, handover, availability, alarms), and where?")

Category = Literal[tuple(CATEGORY_CODES)]
Severity = Literal["low", "medium", "high", "critical", "unknown"]


class ClassifierFilters(BaseModel):
    state: list[str] = Field(default_factory=list)
    city: str | None = None
    season: list[str] = Field(default_factory=list)
    weather: list[str] = Field(default_factory=list)


class LLMClassification(BaseModel):
    """What the LLM must return (validated; one repair attempt on failure)."""
    primary_category: Category
    secondary_categories: list[Category] = Field(default_factory=list, max_length=2)
    symptoms: list[str] = Field(default_factory=list)
    filters: ClassifierFilters = Field(default_factory=ClassifierFilters)
    severity_hint: Severity = "unknown"
    in_scope: bool = True
    needs_clarification: bool = False
    clarification_question: str | None = None
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""


class Classification(LLMClassification):
    source: Literal["llm", "rules", "merged"] = "llm"


# ---------------------------------------------------------------------------- prompt
def build_prompt(kpi_assessment: dict | None) -> str:
    cats = "\n".join(f"- {c.code}: {c.description} Defining symptoms: {', '.join(c.symptoms)}"
                     for c in CATEGORIES.values())
    syms = "\n".join(f"- {s.code}: {s.label}" for s in SYMPTOMS.values())
    kpi = ""
    if kpi_assessment:
        anomalies = [f"{a['kpi']}={a['value']} ({a['band']})" for a in kpi_assessment.get("anomalies", [])][:8]
        kpi = ("\n## KPI snapshot supplied with the query (deterministic assessment)\n"
               f"Anomalies: {', '.join(anomalies) or 'none'}. KPI-derived symptoms: "
               f"{', '.join(kpi_assessment.get('symptoms', [])) or 'none'}.\n")
    return (PROMPT_PATH.read_text(encoding="utf-8")
            .replace("{{categories}}", cats).replace("{{symptoms}}", syms)
            .replace("{{seasons}}", ", ".join(SEASONS)).replace("{{weather}}", ", ".join(WEATHER))
            .replace("{{kpi_section}}", kpi))


# ---------------------------------------------------------------------------- rules
def _category_scores(symptoms: list[str], keyword_categories: list[str]) -> dict[str, float]:
    """Symptom membership normalized by category size (as kpi_analyzer does), plus a keyword bonus."""
    scores = {}
    for code, cat in CATEGORIES.items():
        hits = len(set(symptoms) & set(cat.symptoms))
        scores[code] = hits / math.sqrt(len(cat.symptoms)) + (0.5 if code in keyword_categories else 0.0)
    return scores


def rule_classify(query: str) -> Classification:
    p = query_parser.parse(query)
    scores = _category_scores(p.symptoms, p.categories)
    ranked = sorted((c for c in scores if scores[c] > 0), key=lambda c: (-scores[c], CATEGORY_CODES.index(c)))
    vague = not p.symptoms and not ranked
    conf = 0.0 if vague else round(min(0.75, 0.35 + 0.1 * len(p.symptoms) + (0.1 if p.categories else 0)), 2)
    return Classification(
        primary_category=ranked[0] if ranked else NORMAL, secondary_categories=ranked[1:3], symptoms=p.symptoms,
        filters=ClassifierFilters(**{k: v for k, v in p.filters.items() if k in ("state", "season", "weather")}),
        severity_hint=p.severity_hint, in_scope=True, needs_clarification=vague,
        clarification_question=CLARIFY_QUESTION if vague else None, confidence=conf,
        rationale=("Rule-based: matched " + ", ".join(p.symptoms) + ".") if p.symptoms else
                  "Rule-based: no known symptom words were found.", source="rules")


# ---------------------------------------------------------------------------- post-processing
def _clean(c: LLMClassification, warnings: list[str]) -> Classification:
    out = Classification(**c.model_dump(), source="llm")
    bad = [s for s in out.symptoms if s not in SYMPTOMS]
    out.symptoms = [s for s in dict.fromkeys(out.symptoms) if s in SYMPTOMS]
    if bad:
        warnings.append(f"Classifier returned unknown symptoms, dropped: {bad}")
    out.secondary_categories = [x for x in dict.fromkeys(out.secondary_categories) if x != out.primary_category][:2]
    states, dropped = [], []
    for v in out.filters.state:
        key = str(v).strip()
        code = key.upper() if key.upper() in STATE_NAMES else _NAME_TO_CODE.get(key.lower())
        (states.append(code) if code else dropped.append(v))
    season_map = {s.lower(): s for s in SEASONS} | {"autumn": "Fall"}
    weather_map = {w.lower(): w for w in WEATHER}
    seasons = [season_map[s.lower()] for s in out.filters.season if s.lower() in season_map]
    weather = [weather_map[w.lower()] for w in out.filters.weather if w.lower() in weather_map]
    dropped += [s for s in out.filters.season if s.lower() not in season_map]
    dropped += [w for w in out.filters.weather if w.lower() not in weather_map]
    if dropped:
        warnings.append(f"Unrecognized filter values were ignored: {dropped}")
    out.filters = ClassifierFilters(state=sorted(set(states)), city=out.filters.city or None,
                                    season=sorted(set(seasons)), weather=sorted(set(weather)))
    if out.needs_clarification and not out.clarification_question:
        out.clarification_question = CLARIFY_QUESTION
    return out


def reconcile(c: Classification, kpi_assessment: dict | None) -> Classification:
    """KPI evidence wins on symptoms; the text decides between tied KPI categories (plan §8.2)."""
    if not kpi_assessment:
        return c
    provided = {p["kpi"] for p in kpi_assessment["per_kpi"] if not p["imputed"]}
    kpi_syms = list(kpi_assessment["symptoms"])
    text_only = [s for s in c.symptoms if SYMPTOMS[s].kpi not in provided]
    symptoms = list(dict.fromkeys([*kpi_syms, *text_only]))
    scores = kpi_assessment["category_scores"]
    best = max(scores.values()) if scores else 0
    if best > 0:
        tied = [k for k, v in scores.items() if v >= best * (1 - TIE_MARGIN)]
        primary = c.primary_category if c.primary_category in tied else kpi_assessment["primary_category"]
    else:
        primary = c.primary_category
    secondary = [x for x in [c.primary_category, *c.secondary_categories, *kpi_assessment["secondary_categories"]]
                 if x and x != primary and x != NORMAL]
    return c.model_copy(update={"symptoms": symptoms, "primary_category": primary,
                                "secondary_categories": list(dict.fromkeys(secondary))[:2], "source": "merged",
                                "needs_clarification": c.needs_clarification and not symptoms})


# ---------------------------------------------------------------------------- entry point
def classify(llm: LLMClient | None, query: str, kpi_assessment: dict | None = None,
             usage: RunUsage | None = None) -> tuple[Classification, list[str], bool]:
    """Returns (classification, warnings, degraded). degraded=True when the rule fallback was used."""
    warnings: list[str] = []
    degraded = False
    if llm is not None and llm.available:
        try:
            raw = llm.generate_json([{"role": "system", "content": build_prompt(kpi_assessment)},
                                     {"role": "user", "content": query}],
                                    LLMClassification, max_tokens=MAX_TOKENS, usage=usage, purpose="classify",
                                    prompt_version=PROMPT_VERSION, reasoning=llm.s.classifier_reasoning)
            c = _clean(raw, warnings)
        except LLMError as exc:
            log.warning("classifier fallback to rules: %s", exc)
            warnings.append("The LLM classifier was unavailable; a rule-based classification is shown.")
            c, degraded = rule_classify(query), True
    else:
        c, degraded = rule_classify(query), True
    c = reconcile(c, kpi_assessment)
    # Plan §8.2 routing: clarify only when confidence < 0.4 AND no symptom was identified; a recognized
    # symptom always continues the workflow, whatever the LLM's own needs_clarification flag says.
    clarify = c.in_scope and c.confidence < CLARIFY_CONFIDENCE and not c.symptoms
    c.needs_clarification = clarify
    c.clarification_question = (c.clarification_question or CLARIFY_QUESTION) if clarify else None
    return c, warnings, degraded
