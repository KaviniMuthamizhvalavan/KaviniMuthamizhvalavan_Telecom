"""Metadata filters compiled two ways with identical semantics (plan §7.6, §9.1).

- to_chroma_where(): for dense search in Chroma
- to_mask():         for BM25 masking and analytics over the cases dataframe
A unit test asserts both select the same records.

Semantics: list fields match any listed value; `symptoms` requires every listed symptom;
`categories` matches the primary incident type; `city` is an exact, case-insensitive match.
"""
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from src.utils.schema import CATEGORY_CODES, KPI_SPECS, PRIORITIES, SEASONS, STATE_NAMES, SYMPTOMS, WEATHER


class KPIRange(BaseModel):
    min: float | None = None
    max: float | None = None


class SearchFilters(BaseModel):
    state: list[str] | None = Field(default=None, examples=[["TX"]])
    city: str | None = None
    season: list[str] | None = Field(default=None, examples=[["Winter"]])
    weather: list[str] | None = None
    categories: list[str] | None = None
    symptoms: list[str] | None = None
    kpi_ranges: dict[str, KPIRange] | None = None
    priority: list[str] | None = None

    def is_empty(self) -> bool:
        return not any(v for v in self.model_dump().values())


class InvalidFilterError(ValueError):
    def __init__(self, field: str, invalid: list, allowed: list):
        super().__init__(f"invalid {field}: {invalid}")
        self.details = {"field": field, "invalid": invalid, "allowed": allowed}


_NAME_TO_CODE = {name.lower(): code for code, name in STATE_NAMES.items()}


def _normalize_list(values, allowed: list[str], field: str, aliases: dict[str, str] | None = None) -> list[str] | None:
    if not values:
        return None
    lookup = {a.lower(): a for a in allowed}
    if aliases:
        lookup.update(aliases)
    out, bad = [], []
    for v in values:
        key = str(v).strip().lower()
        if key in lookup:
            out.append(lookup[key])
        else:
            bad.append(v)
    if bad:
        raise InvalidFilterError(field, bad, allowed)
    return sorted(set(out))


def validate(f: SearchFilters | None) -> tuple[SearchFilters, list[str]]:
    """Normalize values (state names -> codes, case-insensitive enums); raise InvalidFilterError on unknowns."""
    f = f or SearchFilters()
    warnings = []
    data = {
        "state": _normalize_list(f.state, list(STATE_NAMES), "state", _NAME_TO_CODE),
        "season": _normalize_list(f.season, SEASONS, "season", {"autumn": "Fall"}),
        "weather": _normalize_list(f.weather, WEATHER, "weather"),
        "categories": _normalize_list(f.categories, CATEGORY_CODES, "categories"),
        "symptoms": _normalize_list(f.symptoms, list(SYMPTOMS), "symptoms"),
        "priority": _normalize_list(f.priority, PRIORITIES, "priority"),
        "city": f.city.strip().lower() if f.city and f.city.strip() else None,
        "kpi_ranges": None,
    }
    if f.kpi_ranges:
        bad = [k for k in f.kpi_ranges if k not in KPI_SPECS]
        if bad:
            raise InvalidFilterError("kpi_ranges", bad, list(KPI_SPECS))
        data["kpi_ranges"] = {k: r for k, r in f.kpi_ranges.items() if r.min is not None or r.max is not None} or None
    if data["city"]:
        warnings.append("City names in this dataset are synthetic, so a city filter usually matches very few records.")
    return SearchFilters(**data), warnings


def _conditions(f: SearchFilters) -> list[tuple[str, str, object]]:
    """Flatten filters into (field, op, value) triples shared by both compilers."""
    conds = []
    for field, col in (("state", "state"), ("season", "season"), ("weather", "weather"),
                       ("categories", "primary_category"), ("priority", "priority")):
        values = getattr(f, field)
        if values:
            conds.append((col, "in", list(values)))
    if f.city:
        conds.append(("city_lc", "eq", f.city))
    for code in f.symptoms or []:
        conds.append((f"sym_{code}", "eq", True))
    for kpi, r in (f.kpi_ranges or {}).items():
        if r.min is not None:
            conds.append((kpi, "gte", float(r.min)))
        if r.max is not None:
            conds.append((kpi, "lte", float(r.max)))
    return conds


def to_chroma_where(f: SearchFilters) -> dict | None:
    ops = {"in": "$in", "eq": "$eq", "gte": "$gte", "lte": "$lte"}
    clauses = [{col: {ops[op]: val}} for col, op, val in _conditions(f)]
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}  # Chroma rejects multi-key dicts


def to_mask(f: SearchFilters, cases: pd.DataFrame) -> np.ndarray:
    mask = np.ones(len(cases), dtype=bool)
    for col, op, val in _conditions(f):
        s = cases[col]
        if op == "in":
            mask &= s.isin(val).to_numpy()
        elif op == "eq":
            mask &= (s == val).to_numpy()
        elif op == "gte":
            mask &= (s >= val).to_numpy()
        elif op == "lte":
            mask &= (s <= val).to_numpy()
    return mask
