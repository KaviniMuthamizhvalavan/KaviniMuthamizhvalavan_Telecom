"""Generate docs/source/API_Documentation.md from the app's OpenAPI schema and the captured examples (plan §12.4).

Run from the repo root:  python -m scripts.build_api_doc   (then: python -m scripts.build_docs api)
Per endpoint: endpoint and method, request format, response format, one sample request and one sample response.
Field tables come from the code (FastAPI/Pydantic schemas); samples come from tests/test_cases/api_examples.json
(scripts/capture_api_examples.py), trimmed for reading. /evaluation/latest is sampled from the saved evaluation
results. No API spend. 2026-10-11: rewritten to be concise (top-level fields only; nested models are at /docs).
"""
import json

from src.utils.config import PROJECT_ROOT

OUT = PROJECT_ROOT / "docs" / "source" / "API_Documentation.md"
EXAMPLES = PROJECT_ROOT / "tests" / "test_cases" / "api_examples.json"
ORDER = ["/health", "/metadata", "/search", "/cases/{case_id}", "/classify", "/recommend", "/troubleshoot",
         "/prioritize", "/predict/fault-risk", "/predict/performance", "/feedback", "/feedback/summary",
         "/evaluation/latest"]
LLM_ENDPOINTS = {"/classify": "1", "/recommend": "1", "/troubleshoot": "4 typical, up to 12"}
# Prefer the full-mode (AI) sample where one was captured.
PREFER = {"/troubleshoot": "full", "/recommend": "full"}
ENVELOPE = {"request_id", "warnings"}  # on every response; described once in the conventions


def type_of(prop: dict) -> str:
    if "$ref" in prop:
        return "object"
    if "anyOf" in prop:
        kinds = [type_of(p) for p in prop["anyOf"] if p.get("type") != "null"]
        nullable = any(p.get("type") == "null" for p in prop["anyOf"])
        return " or ".join(dict.fromkeys(kinds)) + (", nullable" if nullable else "")
    if prop.get("type") == "array":
        return f"array of {type_of(prop.get('items', {}))}"
    if "enum" in prop:
        return "string (enum)"
    return prop.get("type", "object")


def num(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def notes(prop: dict) -> str:
    out = []
    for key, label in (("minLength", "min length"), ("maxLength", "max length"), ("minimum", "≥"),
                       ("maximum", "≤"), ("exclusiveMinimum", ">"), ("maxItems", "max items")):
        for p in [prop, *prop.get("anyOf", [])]:
            if key in p:
                out.append(f"{label} {num(p[key])}")
    if "enum" in prop:
        vals = ", ".join(map(str, prop["enum"]))
        out.append(f"one of: {vals[:90]}{'…' if len(vals) > 90 else ''}")
    if "default" in prop and prop["default"] not in (None, [], {}):
        out.append(f"default {json.dumps(prop['default'])}")
    if prop.get("description"):
        out.append(prop["description"].replace("\n", " "))
    return "; ".join(dict.fromkeys(out)).replace("|", "/")


def fields(schema_name: str, schemas: dict, request: bool) -> str:
    sch = schemas[schema_name]
    req = set(sch.get("required", []))
    props = {k: v for k, v in sch.get("properties", {}).items() if request or k not in ENVELOPE}
    if request:
        rows = ["| Field | Type | Required | Notes |", "|---|---|---|---|"]
        rows += [f"| `{k}` | {type_of(v)} | {'yes' if k in req else 'no'} | {notes(v)} |" for k, v in props.items()]
    else:
        rows = ["| Field | Type |", "|---|---|"]
        rows += [f"| `{k}` | {type_of(v)} |" for k, v in props.items()]
    return "\n".join(rows)


def trim(obj, depth=0):
    """Readable sample: first list item plus a count, short strings, deep objects collapsed."""
    if isinstance(obj, list):
        if not obj:
            return []
        head = [trim(obj[0], depth + 1)]
        return head + ([f"... {len(obj) - 1} more"] if len(obj) > 1 else [])
    if isinstance(obj, dict):
        if depth >= 3 and obj:
            return "{...}"
        items = list(obj.items())
        if depth >= 1 and len(items) > 8:  # nested objects: the first fields only (top-level fields all shown)
            out = {k: trim(v, depth + 1) for k, v in items[:6]}
            out["..."] = f"{len(items) - 6} more fields"
            return out
        return {k: trim(v, depth + 1) for k, v in items}
    if isinstance(obj, float):
        return round(obj, 3)
    if isinstance(obj, str) and len(obj) > 110:
        return obj[:110] + "…"
    return obj


def pick(examples: list[dict], path: str) -> dict | None:
    ok = [e for e in examples if e["status"] < 400]
    want = PREFER.get(path)
    return next((e for e in ok if want and want in e["name"]), ok[0] if ok else None)


def evaluation_sample() -> dict:
    """From the saved results (no API call); the live block is abbreviated."""
    from src.services import evaluation_results
    return {"request_id": "3f9c1a2b7d4e", "warnings": [], "offline": evaluation_results.load_offline(),
            "live": {"total": 12, "verdicts": {"pass": 9, "fail": 2, "unvalidated": 1, "not_judged": 0},
                     "pass_rate": 0.82, "by_model": [], "avg_scores": None, "scored_runs": 11, "recent": []},
            "offline_alternatives": evaluation_results.load_alternatives()}


def main() -> None:
    from src.main import app
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    ex = json.loads(EXAMPLES.read_text(encoding="utf-8"))
    by_path: dict[str, list] = {}
    for e in ex["examples"] + ex["llm_examples"]:
        p = e["path"].replace("/api/v1", "")
        by_path.setdefault("/cases/{case_id}" if p.startswith("/cases/") else p, []).append(e)

    md = ["# API Documentation", "",
          "AI-Powered Telecom Network Operations Assistant: REST API reference, generated on 2026-10-11 from the "
          "application's OpenAPI schema and real captured requests and responses "
          "(`tests/test_cases/api_examples.json`).", "",
          "## 1. Conventions", "",
          "| Item | Value |", "|---|---|",
          "| Base URL | `http://localhost:8000/api/v1` |",
          "| Interactive docs | `http://localhost:8000/docs` (every nested model), schema at `/openapi.json` |",
          "| Format | JSON request and response bodies |",
          "| Every response | `request_id` (string, also in the `X-Request-ID` header) and `warnings` (array of non-fatal "
          "caveats, e.g. reduced mode). They are not repeated in the tables below. |",
          "| Authentication | None (local use only) |",
          "| LLM use | Only `/classify`, `/recommend` and `/troubleshoot` call the LLM (Claude Haiku 5.5). Without a key, "
          "or after the daily spend cap, they answer in reduced mode with a warning. |", "",
          "**Errors** have one shape, never a stack trace:", "",
          "```json", json.dumps({"error": {"code": "OUT_OF_SCOPE", "message": "This assistant answers questions about "
                                           "mobile network operations.", "details": {}, "request_id": "c720f996ef9d"}}),
          "```", "",
          "| HTTP | `code` |", "|---|---|",
          "| 400 | `INVALID_FILTER`, `PROMPT_INJECTION`, `OUT_OF_SCOPE`, `GIBBERISH` |",
          "| 404 | `NOT_FOUND` |", "| 422 | `INVALID_INPUT` |", "| 503 | `NOT_READY` (run `python -m scripts.bootstrap`) |",
          "| 500 | `INTERNAL_ERROR` |", "",
          "## 2. Endpoints", "",
          "| # | Method | Endpoint | Purpose | LLM calls |", "|---|---|---|---|---|"]
    ops = []
    for i, path in enumerate(ORDER, 1):
        for method, op in spec["paths"][f"/api/v1{path}"].items():
            ops.append((i, path, method, op))
            md.append(f"| 2.{i} | {method.upper()} | `{path}` | {op.get('summary', '')} | {LLM_ENDPOINTS.get(path, '0')} |")
    md.append("")

    for i, path, method, op in ops:
        md += [f"### 2.{i} `{method.upper()} {path}`", "", f"{op.get('summary', '')}.", "", "**Request format**", ""]
        params = op.get("parameters", [])
        body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
        if params:
            md += ["| Parameter | In | Type | Required | Notes |", "|---|---|---|---|---|"]
            md += [f"| `{p['name']}` | {p['in']} | {type_of(p.get('schema', {}))} | {'yes' if p.get('required') else 'no'} "
                   f"| {notes({**p.get('schema', {}), 'description': p.get('description', '')})} |" for p in params]
            md.append("")
        if body and "$ref" in body:
            md += ["JSON body:", "", fields(body["$ref"].split("/")[-1], schemas, request=True), ""]
        if not params and not body:
            md += ["None.", ""]
        ok = op["responses"].get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})
        if "$ref" in ok:
            md += ["**Response format** (HTTP 200)", "", fields(ok["$ref"].split("/")[-1], schemas, request=False), ""]

        e = pick(by_path.get(path, []), path)
        if e is not None:
            req = e["request"]
            curl = (f"curl -X {e['method']} http://localhost:8000{e['path']} -H \"Content-Type: application/json\" "
                    f"-d '{json.dumps(req)}'" if req is not None else f"curl http://localhost:8000{e['path']}")
            response = e["response"]
            label = f" ({e['name'].split('(')[-1].rstrip(')')})" if "(" in e["name"] else ""
        else:  # /evaluation/latest: no captured example; built from the saved results
            curl = "curl \"http://localhost:8000/api/v1/evaluation/latest?days=30\""
            response, label = evaluation_sample(), " (from the saved results; live block abbreviated)"
        md += ["**Sample request**", "", "```bash", curl, "```", "",
               f"**Sample response**{label}. Trimmed: lists show the first item, deeper objects are `{{...}}`.", "",
               "```json", json.dumps(trim(response), indent=2, ensure_ascii=False), "```", ""]

    OUT.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(PROJECT_ROOT)} ({len(md)} blocks)")


if __name__ == "__main__":
    main()
