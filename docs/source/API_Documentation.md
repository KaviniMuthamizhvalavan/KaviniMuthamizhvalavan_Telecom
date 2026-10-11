# API Documentation

AI-Powered Telecom Network Operations Assistant: REST API reference, generated on 2026-10-11 from the application's OpenAPI schema and real captured requests and responses (`tests/test_cases/api_examples.json`).

## 1. Conventions

| Item | Value |
|---|---|
| Base URL | `http://localhost:8000/api/v1` |
| Interactive docs | `http://localhost:8000/docs` (every nested model), schema at `/openapi.json` |
| Format | JSON request and response bodies |
| Every response | `request_id` (string, also in the `X-Request-ID` header) and `warnings` (array of non-fatal caveats, e.g. reduced mode). They are not repeated in the tables below. |
| Authentication | None (local use only) |
| LLM use | Only `/classify`, `/recommend` and `/troubleshoot` call the LLM (Claude Haiku 5.5). Without a key, or after the daily spend cap, they answer in reduced mode with a warning. |

**Errors** have one shape, never a stack trace:

```json
{"error": {"code": "OUT_OF_SCOPE", "message": "This assistant answers questions about mobile network operations.", "details": {}, "request_id": "c720f996ef9d"}}
```

| HTTP | `code` |
|---|---|
| 400 | `INVALID_FILTER`, `PROMPT_INJECTION`, `OUT_OF_SCOPE`, `GIBBERISH` |
| 404 | `NOT_FOUND` |
| 422 | `INVALID_INPUT` |
| 503 | `NOT_READY` (run `python -m scripts.bootstrap`) |
| 500 | `INTERNAL_ERROR` |

## 2. Endpoints

| # | Method | Endpoint | Purpose | LLM calls |
|---|---|---|---|---|
| 2.1 | GET | `/health` | Liveness, readiness and component status | 0 |
| 2.2 | GET | `/metadata` | Filter vocabularies, taxonomy and KPI specs for the UI | 0 |
| 2.3 | POST | `/search` | Hybrid similar-case search with metadata filters (no LLM) | 0 |
| 2.4 | GET | `/cases/{case_id}` | Full historical case record and assessment | 0 |
| 2.5 | POST | `/classify` | Classify an incident description (LLM agent; rule-based when the LLM is unavailable) | 1 |
| 2.6 | POST | `/recommend` | Basic RAG: similar cases, likely causes and cited recommendations in one LLM call | 1 |
| 2.7 | POST | `/troubleshoot` | Full multi-agent analysis: classify, retrieve, root cause and impact, actions, validation | 4 typical, up to 12 |
| 2.8 | POST | `/prioritize` | P1-P4 priority with reasons for a KPI snapshot | 0 |
| 2.9 | POST | `/predict/fault-risk` | Probability of a top-quartile fault occurrence rate | 0 |
| 2.10 | POST | `/predict/performance` | Expected throughput for the given conditions (and deficit if observed throughput is given) | 0 |
| 2.11 | POST | `/feedback` | Rate a run and mark similar cases relevant or not | 0 |
| 2.12 | GET | `/feedback/summary` | Aggregated feedback: ratings, helpful rate, most down-voted cases, trend | 0 |
| 2.13 | GET | `/evaluation/latest` | Latest saved evaluation results and live validation of recent runs (no LLM) | 0 |

### 2.1 `GET /health`

Liveness, readiness and component status.

**Request format**

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `deep` | query | boolean | no | default false; Also make one lightweight LLM API request |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `status` | string (enum) |
| `ready` | boolean |
| `data_source` | string |
| `components` | object |
| `versions` | object |

**Sample request**

```bash
curl http://localhost:8000/api/v1/health
```

**Sample response**. Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "status": "ok",
  "ready": true,
  "data_source": "full",
  "components": {
    "vector_store": {
      "ok": true,
      "cases_count": 100000,
      "kb_count": 81
    },
    "keyword_index": {
      "ok": true
    },
    "models": {
      "fault_risk": true,
      "performance": true
    },
    "database": {
      "ok": true
    },
    "llm": {
      "provider": "none",
      "model": "none",
      "configured": false,
      "reachable": null
    },
    "missing": []
  },
  "versions": {
    "app": "0.1.0",
    "prompt": "classifier_v1,analyst_v1,recommender_v1,judge_v1",
    "narrative_template": "v1",
    "embedding_model": "BAAI/bge-small-en-v1.5"
  }
}
```

### 2.2 `GET /metadata`

Filter vocabularies, taxonomy and KPI specs for the UI.

**Request format**

None.

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `states` | array of object |
| `seasons` | array of string |
| `weather` | array of string |
| `categories` | array of object |
| `symptoms` | array of object |
| `kpis` | array of object |
| `priorities` | array of string |
| `corpus_size` | integer |

**Sample request**

```bash
curl http://localhost:8000/api/v1/metadata
```

**Sample response**. Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "request_id": "d47222bd2a2b",
  "warnings": [],
  "states": [
    {
      "code": "AK",
      "name": "Alaska",
      "count": 1719
    },
    "... 58 more"
  ],
  "seasons": [
    "Spring",
    "... 3 more"
  ],
  "weather": [
    "Clear",
    "... 3 more"
  ],
  "categories": [
    {
      "code": "CONGESTION_CAPACITY",
      "name": "Congestion and capacity",
      "description": "Load exceeds capacity: many users or heavy traffic with low throughput and rising latency.",
      "count": 12781
    },
    "... 8 more"
  ],
  "symptoms": [
    {
      "code": "high_latency",
      "kpi": "latency_ms",
      "direction": 1,
      "label": "high latency"
    },
    "... 18 more"
  ],
  "kpis": [
    {
      "name": "latency_ms",
      "label": "Latency",
      "unit": "ms",
      "direction": 1,
      "min": 0.0,
      "max": 2000.0,
      "...": "4 more fields"
    },
    "... 20 more"
  ],
  "priorities": [
    "P1",
    "... 3 more"
  ],
  "corpus_size": 100000
}
```

### 2.3 `POST /search`

Hybrid similar-case search with metadata filters (no LLM).

**Request format**

JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | min length 5; max length 1000 |
| `filters` | object, nullable | no |  |
| `top_k` | integer | no | ≥ 1; ≤ 20; default 5 |
| `mode` | string (enum) | no | one of: hybrid_rerank, hybrid, dense, bm25; default "hybrid_rerank" |
| `use_rule_expansion` | boolean | no | default true |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `query` | string |
| `mode` | string |
| `parsed` | object |
| `applied_filters` | object |
| `expansion_terms` | array of string |
| `total_candidates` | integer |
| `timings_ms` | object |
| `results` | array of object |

**Sample request**

```bash
curl -X POST http://localhost:8000/api/v1/search -H "Content-Type: application/json" -d '{"query": "High latency and packet loss on video calls in winter", "filters": {"season": ["Winter"]}, "top_k": 3}'
```

**Sample response**. Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "request_id": "3f6cdc79f428",
  "warnings": [],
  "query": "High latency and packet loss on video calls in winter",
  "mode": "hybrid_rerank",
  "parsed": {
    "symptoms": [
      "high_latency",
      "... 1 more"
    ],
    "filters": {
      "season": [
        "Winter"
      ]
    }
  },
  "applied_filters": {
    "season": [
      "Winter"
    ]
  },
  "expansion_terms": [],
  "total_candidates": 24941,
  "timings_ms": {
    "dense": 102.2,
    "sparse": 4.5,
    "rerank": 11.3,
    "total": 132.2
  },
  "results": [
    {
      "rank": 1,
      "case_id": "CASE-002045",
      "final_score": 1.2,
      "score_breakdown": "{...}",
      "state": "CA",
      "city": "Tonytown",
      "...": "8 more fields"
    },
    "... 2 more"
  ]
}
```

### 2.4 `GET /cases/{case_id}`

Full historical case record and assessment.

**Request format**

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `case_id` | path | string | yes |  |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `case_id` | string |
| `raw` | object |
| `normalized` | object |
| `assessment` | object |
| `symptoms` | array of string |
| `env_tags` | array of string |
| `category_scores` | object |
| `primary_category` | string |
| `secondary_categories` | array of string |
| `priority` | object |
| `fault_risk_prob` | number |
| `fault_risk_band` | string |
| `narrative` | string |

**Sample request**

```bash
curl http://localhost:8000/api/v1/cases/CASE-002045
```

**Sample response**. Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "request_id": "45bbc7149ac0",
  "warnings": [],
  "case_id": "CASE-002045",
  "raw": {
    "Season": "Winter",
    "Cell Availability (%)": 92.209,
    "MTTR (hours)": 5.11,
    "Throughput (Mbps)": 416.963,
    "Latency (ms)": 107.497,
    "Packet Loss Rate (%)": 13.94,
    "...": "21 more fields"
  },
  "normalized": {
    "season": "Winter",
    "cell_availability_pct": 92.209,
    "mttr_hours": 5.11,
    "throughput_mbps": 416.963,
    "latency_ms": 107.497,
    "packet_loss_pct": 13.94,
    "...": "21 more fields"
  },
  "assessment": {
    "per_kpi": [
      "{...}",
      "... 18 more"
    ]
  },
  "symptoms": [
    "high_latency",
    "... 2 more"
  ],
  "env_tags": [
    "adverse_weather"
  ],
  "category_scores": {
    "CONGESTION_CAPACITY": 0.5,
    "TRANSPORT_QOS": 1.732,
    "RADIO_COVERAGE": 1.155,
    "MOBILITY_HANDOVER": 1.414,
    "AVAILABILITY_OUTAGE": 0.0,
    "FAULT_ALARM": 0.0,
    "CONFIG_CHANGE": 0.0,
    "SECURITY_AUTH": 0.0
  },
  "primary_category": "TRANSPORT_QOS",
  "secondary_categories": [
    "MOBILITY_HANDOVER",
    "... 1 more"
  ],
  "priority": {
    "level": "P3",
    "label": "Medium",
    "score": 0.488,
    "components": {
      "severity": 0.424,
      "impact": 0.341,
      "risk": 0.722
    }
  },
  "fault_risk_prob": 0.722,
  "fault_risk_band": "High",
  "narrative": "CASE-002045, CA, Winter, Snow, 8.0 C. Critical: packet loss 13.9% (worse than 97% of records; dropped packets,…"
}
```

### 2.5 `POST /classify`

Classify an incident description (LLM agent; rule-based when the LLM is unavailable).

**Request format**

JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | min length 5; max length 1000 |
| `kpis` | object, nullable | no |  |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `status` | string (enum) |
| `classification` | object |
| `kpi_assessment` | object, nullable |
| `usage` | object |

**Sample request**

```bash
curl -X POST http://localhost:8000/api/v1/classify -H "Content-Type: application/json" -d '{"query": "Handover success rate is low on a highway site in Ohio"}'
```

**Sample response** (reduced mode). Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "request_id": "21f2fd619c58",
  "warnings": [],
  "status": "degraded",
  "classification": {
    "primary_category": "MOBILITY_HANDOVER",
    "secondary_categories": [],
    "symptoms": [
      "low_handover_success"
    ],
    "filters": {
      "state": [
        "OH"
      ],
      "city": null,
      "season": [],
      "weather": []
    },
    "severity_hint": "unknown",
    "in_scope": true,
    "...": "5 more fields"
  },
  "kpi_assessment": null,
  "usage": {
    "llm_calls": 0,
    "tokens_in": 0,
    "tokens_out": 0,
    "cached_calls": 0
  }
}
```

### 2.6 `POST /recommend`

Basic RAG: similar cases, likely causes and cited recommendations in one LLM call.

**Request format**

JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | min length 5; max length 1000 |
| `filters` | object, nullable | no |  |
| `kpis` | object, nullable | no |  |
| `top_k` | integer | no | ≥ 1; ≤ 20; default 5 |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `run_id` | string |
| `status` | string (enum) |
| `parsed` | object |
| `similar_cases` | array of object |
| `answer` | object |
| `priority` | object, nullable |
| `sources` | array of object |
| `usage` | object |

**Sample request**

```bash
curl -X POST http://localhost:8000/api/v1/recommend -H "Content-Type: application/json" -d '{"query": "A cell is experiencing high latency, packet loss, and reduced throughput. What similar network conditions have occurred before?"}'
```

**Sample response** (full, Claude Haiku 5.5). Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "run_id": "811e0b0239814b72a019fce1c5118074",
  "status": "ok",
  "parsed": {
    "symptoms": [
      "high_latency",
      "... 2 more"
    ],
    "filters": {}
  },
  "similar_cases": [
    {
      "rank": 1,
      "case_id": "CASE-037746",
      "final_score": 1.18,
      "score_breakdown": "{...}",
      "state": "NV",
      "city": "New Joanne",
      "...": "8 more fields"
    },
    "... 4 more"
  ],
  "answer": {
    "summary": "Five similar past cases were found: four are tagged TRANSPORT_QOS+CONGESTION_CAPACITY and one is AVAILABILITY_…",
    "likely_causes": [
      "{...}",
      "... 5 more"
    ],
    "recommendations": [
      "{...}",
      "... 5 more"
    ]
  },
  "priority": {
    "level": "P4",
    "label": "Low",
    "score": 0.287,
    "components": {
      "severity": 0.322,
      "impact": 0.482,
      "risk": 0.045
    },
    "overrides": [],
    "reasons": [
      "Estimated from the median KPIs of the similar cases (no KPIs were given).",
      "... 5 more"
    ]
  },
  "sources": [
    {
      "id": "CASE-037746",
      "type": "case",
      "title": "TRANSPORT_QOS case, NV",
      "snippet": "[CASE-037746] NV/Summer/Rain, P2, TRANSPORT_QOS+CONGESTION_CAPACITY: latency 166.4 ms (crit), packet loss rate…",
      "score": 1.18
    },
    "... 7 more"
  ],
  "warnings": [],
  "usage": {
    "llm_calls": 1,
    "tokens_in": 2847,
    "tokens_out": 2548,
    "cached_calls": 0
  }
}
```

### 2.7 `POST /troubleshoot`

Full multi-agent analysis: classify, retrieve, root cause and impact, actions, validation.

**Request format**

JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | min length 5; max length 1000 |
| `filters` | object, nullable | no |  |
| `kpis` | object, nullable | no |  |
| `top_k` | integer | no | ≥ 1; ≤ 20; default 5 |
| `options` | object | no |  |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `run_id` | string |
| `status` | string (enum) |
| `classification` | object |
| `applied_filters` | object |
| `similar_cases` | array of object |
| `kpi_assessment` | object, nullable |
| `segment_stats` | object, nullable |
| `root_cause_analysis` | object, nullable |
| `impact` | object, nullable |
| `fault_risk` | object, nullable |
| `performance_prediction` | object, nullable |
| `priority` | object, nullable |
| `recommendations` | array of object |
| `escalation` | object, nullable |
| `validation` | object, nullable |
| `sources` | array of object |
| `trace` | array of object |
| `meta` | object |
| `usage` | object |

**Sample request**

```bash
curl -X POST http://localhost:8000/api/v1/troubleshoot -H "Content-Type: application/json" -d '{"query": "A cell is experiencing high latency, packet loss, and reduced throughput. What similar network conditions have occurred before?"}'
```

**Sample response** (full, Claude Haiku 5.5). Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "run_id": "cd050916292b4537bf503d3998411ada",
  "status": "ok",
  "classification": {
    "primary_category": "TRANSPORT_QOS",
    "secondary_categories": [
      "CONGESTION_CAPACITY"
    ],
    "symptoms": [
      "high_latency",
      "... 2 more"
    ],
    "filters": {
      "state": [],
      "city": null,
      "season": [],
      "weather": []
    },
    "severity_hint": "unknown",
    "in_scope": true,
    "...": "5 more fields"
  },
  "applied_filters": {},
  "similar_cases": [
    {
      "rank": 1,
      "case_id": "CASE-037746",
      "final_score": 1.18,
      "score_breakdown": "{...}",
      "state": "NV",
      "city": "New Joanne",
      "...": "8 more fields"
    },
    "... 4 more"
  ],
  "kpi_assessment": {
    "basis": "similar_cases_median",
    "anomalies": [
      "{...}",
      "... 3 more"
    ],
    "imputed_fields": []
  },
  "segment_stats": {
    "count": 8339,
    "top_lifts": [
      "{...}",
      "... 7 more"
    ],
    "priority_mix": {
      "P1": 0.173,
      "P2": 0.343,
      "P3": 0.406,
      "P4": 0.078
    },
    "median_fault_rate": 47.65
  },
  "root_cause_analysis": {
    "hypotheses": [
      "{...}",
      "... 2 more"
    ],
    "contributing_factors": [
      "{...}",
      "... 3 more"
    ],
    "data_limitations": [
      "No timestamps or time series, so trends cannot be verified; the season comparison is not available for this qu…",
      "... 5 more"
    ]
  },
  "impact": {
    "level": "Moderate",
    "affected_services": [
      "data",
      "... 2 more"
    ],
    "users_served": 3381,
    "data_gb": 31.72,
    "narrative": "The cell serves about 3,381 users (33rd percentile) and 31.72 GB of data, affecting data, real-time and video,…"
  },
  "fault_risk": {
    "probability": 0.041,
    "band": "Low",
    "top_drivers": [
      "{...}",
      "... 4 more"
    ],
    "basis": "similar_cases_median"
  },
  "performance_prediction": {
    "expected_throughput_mbps": 552.7,
    "observed": 336.664,
    "deficit_pct": -39.1,
    "model_r2": 0.328
  },
  "priority": {
    "level": "P4",
    "label": "Low",
    "score": 0.286,
    "components": {
      "severity": 0.322,
      "impact": 0.482,
      "risk": 0.041
    },
    "overrides": [],
    "reasons": [
      "Estimated from the median KPIs of the similar cases (no KPIs were given).",
      "... 5 more"
    ]
  },
  "recommendations": [
    {
      "step": 1,
      "action": "Run latency, jitter and packet loss measurements (e.g., TWAMP or ping series) from the site to the core and co…",
      "phase": "immediate",
      "rationale": "Confirms the transport degradation hypothesis before any network change is made.",
      "expected_kpi_effect": "Establishes measured latency and loss baseline; no direct KPI change expected.",
      "verification": "Measurement results show latency and loss values consistent with the affected period versus baseline.",
      "...": "3 more fields"
    },
    "... 5 more"
  ],
  "escalation": {
    "needed": true,
    "team": "Transport/IP team",
    "reason": "Priority P4 with degradation across latency, loss and throughput; escalate to the transport team if the degrad…"
  },
  "validation": {
    "verdict": "pass",
    "scores": {
      "groundedness": 0.7,
      "kpi_consistency": 0.6,
      "actionability": 0.75,
      "completeness": 0.6
    },
    "issues": [
      "{...}",
      "... 4 more"
    ],
    "summary": "The diagnosis is mostly grounded and the hypotheses follow the evidence, but it cites runbook and case IDs tha…",
    "rule_checks": [
      "{...}",
      "... 5 more"
    ],
    "revisions": 0
  },
  "sources": [
    {
      "id": "CASE-037746",
      "type": "case",
      "title": "TRANSPORT_QOS case, NV",
      "snippet": "[CASE-037746] NV/Summer/Rain, P2, TRANSPORT_QOS+CONGESTION_CAPACITY: latency 166.4 ms (crit), packet loss rate…",
      "score": 1.18
    },
    "... 12 more"
  ],
  "warnings": [],
  "trace": [
    {
      "node": "gate",
      "ms": 0.0,
      "llm_calls": 0,
      "tokens_in": 0,
      "tokens_out": 0,
      "tool_calls": [],
      "status": "ok"
    },
    "... 7 more"
  ],
  "meta": {
    "model": "claude-haiku-5-5",
    "judge_model": "claude-haiku-5-5",
    "prompt_version": "classifier_v1,analyst_v1,recommender_v1,judge_v1",
    "latency_ms": 32171.6,
    "llm_calls": 4,
    "tokens_in": 17303,
    "tokens_out": 6969,
    "cached_calls": 0
  },
  "usage": {
    "llm_calls": 4,
    "tokens_in": 17303,
    "tokens_out": 6969,
    "cached_calls": 0
  }
}
```

### 2.8 `POST /prioritize`

P1-P4 priority with reasons for a KPI snapshot.

**Request format**

JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `kpis` | object | yes |  |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `priority` | object |
| `anomalies` | array of object |
| `fault_risk_prob` | number |
| `imputed_fields` | array of string |

**Sample request**

```bash
curl -X POST http://localhost:8000/api/v1/prioritize -H "Content-Type: application/json" -d '{"kpis": {"latency_ms": 150, "packet_loss_pct": 14, "alarm_count": 16, "user_count": 9500, "weather": "Snow"}}'
```

**Sample response**. Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "request_id": "e22df98750aa",
  "warnings": [
    "Severity is relative to this network's history, not absolute thresholds."
  ],
  "priority": {
    "level": "P2",
    "label": "High",
    "score": 0.73,
    "components": {
      "severity": 0.612,
      "impact": 0.725,
      "risk": 0.892
    },
    "overrides": [],
    "reasons": [
      "Critical latency: 150 ms (worse than 97% of records)",
      "... 4 more"
    ]
  },
  "anomalies": [
    {
      "kpi": "latency_ms",
      "label": "Latency",
      "unit": "ms",
      "value": 150.0,
      "percentile": 0.969,
      "worse_than_pct": 96.9,
      "band": "critical",
      "imputed": false
    },
    "... 3 more"
  ],
  "fault_risk_prob": 0.892,
  "imputed_fields": [
    "jitter_ms",
    "... 16 more"
  ]
}
```

### 2.9 `POST /predict/fault-risk`

Probability of a top-quartile fault occurrence rate.

**Request format**

JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `kpis` | object | yes |  |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `probability` | number |
| `band` | string (enum) |
| `definition` | string |
| `top_drivers` | array of object |
| `imputed_fields` | array of string |
| `model` | object |

**Sample request**

```bash
curl -X POST http://localhost:8000/api/v1/predict/fault-risk -H "Content-Type: application/json" -d '{"kpis": {"latency_ms": 150, "packet_loss_pct": 14, "alarm_count": 16, "user_count": 9500, "weather": "Snow"}}'
```

**Sample response**. Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "request_id": "a9e160c41dd0",
  "warnings": [],
  "probability": 0.892,
  "band": "High",
  "definition": "P(fault occurrence rate >= 48.15%, the training-split p75)",
  "top_drivers": [
    {
      "feature": "weather",
      "importance": 0.315,
      "value": "Snow",
      "band": null,
      "imputed": false
    },
    "... 4 more"
  ],
  "imputed_fields": [
    "cell_availability_pct",
    "... 12 more"
  ],
  "model": {
    "version": "fault_risk-v1",
    "roc_auc": 0.874
  }
}
```

### 2.10 `POST /predict/performance`

Expected throughput for the given conditions (and deficit if observed throughput is given).

**Request format**

JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `kpis` | object | yes |  |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `expected_throughput_mbps` | number |
| `observed_throughput_mbps` | number, nullable |
| `deficit_pct` | number, nullable |
| `assessment` | string (enum), nullable |
| `model` | object |
| `imputed_fields` | array of string |

**Sample request**

```bash
curl -X POST http://localhost:8000/api/v1/predict/performance -H "Content-Type: application/json" -d '{"kpis": {"latency_ms": 150, "packet_loss_pct": 14, "alarm_count": 16, "user_count": 9500, "weather": "Snow", "throughput_mbps": 200}}'
```

**Sample response**. Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "request_id": "28d8ed57033a",
  "warnings": [],
  "expected_throughput_mbps": 352.8,
  "observed_throughput_mbps": 200.0,
  "deficit_pct": -43.3,
  "assessment": "below_expected",
  "model": {
    "version": "performance-v1",
    "r2": 0.328,
    "mae": 161.82
  },
  "imputed_fields": [
    "cell_availability_pct",
    "... 12 more"
  ]
}
```

### 2.11 `POST /feedback`

Rate a run and mark similar cases relevant or not.

**Request format**

JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `run_id` | string | yes | min length 1 |
| `rating` | integer, nullable | no | ≥ 1; ≤ 5 |
| `helpful` | boolean, nullable | no |  |
| `corrected_category` | string (enum), nullable | no |  |
| `comment` | string, nullable | no | max length 1000 |
| `case_feedback` | array of object, nullable | no |  |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `feedback_id` | integer |
| `accepted` | boolean |
| `effects` | object |

**Sample request**

```bash
curl -X POST http://localhost:8000/api/v1/feedback -H "Content-Type: application/json" -d '{"run_id": "6456988312b641c18b6a4c1d86397f73", "rating": 4, "helpful": true, "case_feedback": [{"case_id": "CASE-002045", "relevant": true}]}'
```

**Sample response**. Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "request_id": "84d616c790f7",
  "warnings": [],
  "feedback_id": 1,
  "accepted": true,
  "effects": {
    "priors_updated": 1,
    "correction_stored": false
  }
}
```

### 2.12 `GET /feedback/summary`

Aggregated feedback: ratings, helpful rate, most down-voted cases, trend.

**Request format**

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `days` | query | integer | no | ≥ 1; ≤ 3650; default 30 |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `total_runs` | integer |
| `total_feedback` | integer |
| `avg_rating` | number, nullable |
| `helpful_rate` | number, nullable |
| `by_category` | array of object |
| `most_downvoted_cases` | array of object |
| `corrections_count` | integer |
| `trend` | array of object |

**Sample request**

```bash
curl http://localhost:8000/api/v1/feedback/summary
```

**Sample response**. Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "request_id": "7b8006a04b6d",
  "warnings": [],
  "total_runs": 2,
  "total_feedback": 1,
  "avg_rating": 4.0,
  "helpful_rate": 1.0,
  "by_category": [
    {
      "category": "TRANSPORT_QOS",
      "n": 1,
      "avg_rating": 4.0
    }
  ],
  "most_downvoted_cases": [],
  "corrections_count": 0,
  "trend": [
    {
      "date": "2026-10-09",
      "n": 1,
      "avg_rating": 4.0
    }
  ]
}
```

### 2.13 `GET /evaluation/latest`

Latest saved evaluation results and live validation of recent runs (no LLM).

**Request format**

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `days` | query | integer | no | ≥ 1; ≤ 3650; default 30; Window for the live-validation summary |

**Response format** (HTTP 200)

| Field | Type |
|---|---|
| `offline` | object, nullable |
| `live` | object, nullable |
| `offline_alternatives` | array of object |

**Sample request**

```bash
curl "http://localhost:8000/api/v1/evaluation/latest?days=30"
```

**Sample response** (from the saved results; live block abbreviated). Trimmed: lists show the first item, deeper objects are `{...}`.

```json
{
  "request_id": "3f9c1a2b7d4e",
  "warnings": [],
  "offline": {
    "headline": [
      "{...}",
      "... 28 more"
    ],
    "totals": {
      "PASS": 26,
      "info": 1,
      "FAIL": 2
    },
    "generated_utc": "2026-10-09T10:09:46+00:00",
    "models": {
      "runtime": "claude-sonnet-5-5",
      "runtime_judge": "claude-sonnet-5-5",
      "eval_judge": "claude-opus-5-5",
      "embedding": "BAAI/bge-small-en-v1.5"
    },
    "dataset": {
      "source": "full",
      "cases": 100000
    },
    "deepeval": [
      "{...}",
      "... 13 more"
    ],
    "...": "4 more fields"
  },
  "live": {
    "total": 12,
    "verdicts": {
      "pass": 9,
      "fail": 2,
      "unvalidated": 1,
      "not_judged": 0
    },
    "pass_rate": 0.82,
    "by_model": [],
    "avg_scores": null,
    "scored_runs": 11,
    "recent": []
  },
  "offline_alternatives": [
    {
      "id": "aicredits_haiku_demo",
      "headline": [
        "{...}",
        "... 28 more"
      ],
      "totals": "{...}",
      "generated_utc": "2026-10-11T07:55:45+00:00",
      "models": "{...}",
      "dataset": "{...}",
      "...": "5 more fields"
    }
  ]
}
```

