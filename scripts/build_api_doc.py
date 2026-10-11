"""Generate docs/source/API_Documentation.md from the app's OpenAPI schema and the captured examples (plan §12.4).

Run from the repo root:  python -m scripts.build_api_doc   (then: python -m scripts.build_docs api)
Field tables come from the code (FastAPI/Pydantic schemas); samples come from tests/test_cases/api_examples.json
(scripts/capture_api_examples.py). No API spend.
"""
import json

from src.utils.config import PROJECT_ROOT

OUT = PROJECT_ROOT / "docs" / "source" / "API_Documentation.md"
EXAMPLES = PROJECT_ROOT / "tests" / "test_cases" / "api_examples.json"
ORDER = ["/health", "/metadata", "/search", "/cases/{case_id}", "/classify", "/recommend", "/troubleshoot",
         "/prioritize", "/predict/fault-risk", "/predict/performance", "/feedback", "/feedback/summary",
         "/evaluation/latest"]
LLM_ENDPOINTS = {"/classify": "1 call", "/recommend": "1 call", "/troubleshoot": "4 calls typical, up to 12"}


def type_of(prop: dict, schemas: dict) -> str:
    if "$ref" in prop:
        return f"`{prop['$ref'].split('/')[-1]}`"
    if "anyOf" in prop:
        kinds = [type_of(p, schemas) for p in prop["anyOf"]]
        return " or ".join(k for k in kinds if k != "null") + (" (nullable)" if "null" in kinds else "")
    if prop.get("type") == "array":
        return f"array of {type_of(prop.get('items', {}), schemas)}"
    if "enum" in prop:
        return "enum"
    if "const" in prop:
        return f"`{prop['const']}`"
    return prop.get("type", "object")


def num(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def refs_in(schema_name: str, schemas: dict) -> list[str]:
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                found.append(node["$ref"].split("/")[-1])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(schemas[schema_name].get("properties", {}))
    return list(dict.fromkeys(found))


def constraints(prop: dict) -> str:
    out = []
    for key, label in (("minLength", "min length"), ("maxLength", "max length"), ("minimum", "≥"),
                       ("maximum", "≤"), ("exclusiveMinimum", ">"), ("minItems", "min items"), ("maxItems", "max items")):
        if key in prop:
            out.append(f"{label} {num(prop[key])}")
    for alt in prop.get("anyOf", []):
        out += [c for c in constraints(alt).split("; ") if c]
    if "enum" in prop:
        vals = ", ".join(map(str, prop["enum"]))
        out.append(f"one of: {vals[:240]}{'…' if len(vals) > 240 else ''}")
    if "default" in prop and prop["default"] not in (None, [], {}):
        out.append(f"default {json.dumps(prop['default'])}")
    return "; ".join(out)


def field_table(schema_name: str, schemas: dict) -> str:
    sch = schemas[schema_name]
    req = set(sch.get("required", []))
    props = sch.get("properties", {})
    with_desc = any(p.get("description") for p in props.values())  # the column is shown only when used
    rows = ["| Field | Type | Required | Constraints |" + (" Description |" if with_desc else ""),
            "|---|---|---|---|" + ("---|" if with_desc else "")]
    for name, prop in props.items():
        desc = (prop.get("description") or "").replace("|", "\\|").replace("\n", " ")
        rows.append(f"| `{name}` | {type_of(prop, schemas)} | {'yes' if name in req else 'no'} | "
                    f"{constraints(prop).replace('|', '/')} |" + (f" {desc} |" if with_desc else ""))
    return "\n".join(rows)


def shorten(obj, depth=0):
    """Trim long lists and strings so samples stay readable; marks what was cut."""
    if isinstance(obj, list):
        items = [shorten(x, depth + 1) for x in obj[:2]]
        return items + ([f"... {len(obj) - 2} more"] if len(obj) > 2 else [])
    if isinstance(obj, dict):
        return {k: shorten(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, str) and len(obj) > 220:
        return obj[:220] + "…"
    return obj


def main() -> None:
    from src.main import app
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    ex = json.loads(EXAMPLES.read_text(encoding="utf-8"))
    by_path = {}
    for e in ex["examples"] + ex["llm_examples"]:
        by_path.setdefault(e["path"].replace("/api/v1", "").replace(e["path"].split("/")[-1], "{case_id}")
                           if e["path"].startswith("/api/v1/cases/") else e["path"].replace("/api/v1", ""), []).append(e)

    md = ["# API Documentation", "",
          "AI-Powered Telecom Network Operations Assistant: REST API reference, generated on 2026-10-11 from the "
          "application's OpenAPI schema (`app.openapi()`) and real captured request/response pairs "
          "(`tests/test_cases/api_examples.json`, `scripts/capture_api_examples.py`).", "",
          "## 1. Conventions", "",
          "| Item | Value |", "|---|---|",
          "| Base URL | `http://localhost:8000/api/v1` |",
          "| Interactive docs | Swagger UI at `http://localhost:8000/docs`, ReDoc at `/redoc`, schema at `/openapi.json` |",
          "| Format | JSON request and response bodies (`Content-Type: application/json`) |",
          "| Request ID | Every response carries an `X-Request-ID` header; every response body has a `request_id` |",
          "| Authentication | None (local use only) |",
          "| LLM use | Only `/classify`, `/recommend` and `/troubleshoot` call the LLM (Claude Haiku 5.5 by default). "
          "Without a key, or after the daily spend cap, they return a deterministic reduced-mode answer with a warning. |",
          "| Warnings | Non-fatal caveats (relative severity, imputed KPIs, reduced mode) are returned in `warnings[]`, never as errors |",
          "",
          "### Error envelope", "",
          "Errors never return stack traces. Every error has the same shape:", "",
          "```json", json.dumps({"error": {"code": "INVALID_INPUT", "message": "Check the highlighted values.",
                                           "details": {"errors": ["..."]}, "request_id": "c720f996ef9d"}}, indent=2),
          "```", "",
          "| HTTP | `code` | When |", "|---|---|---|",
          "| 400 | `INVALID_FILTER` | A filter value is not in the dataset vocabulary (see `/metadata`) |",
          "| 400 | `PROMPT_INJECTION` | The query contains instructions aimed at the assistant |",
          "| 400 | `OUT_OF_SCOPE` | The query is not about mobile network operations |",
          "| 400 | `GIBBERISH` | The query does not look like a sentence |",
          "| 404 | `NOT_FOUND` | Unknown case ID or run ID |",
          "| 422 | `INVALID_INPUT` | Request validation failed (types, ranges, unknown fields, empty feedback) |",
          "| 503 | `NOT_READY` | Data artifacts are missing; run `python -m scripts.bootstrap` |",
          "| 500 | `INTERNAL_ERROR` | Unexpected error; quote the `request_id` |", "",
          "## 2. Endpoints", ""]
    used = []
    for i, path in enumerate(ORDER, 1):
        for method, op in spec["paths"][f"/api/v1{path}"].items():
            md += [f"### 2.{i} `{method.upper()} {path}`", "", f"**Purpose:** {op.get('summary', '')}.", ""]
            if op.get("description"):
                md += [op["description"].strip(), ""]
            if path in LLM_ENDPOINTS:
                md += [f"**LLM calls:** {LLM_ENDPOINTS[path]} (about $0.007, ≈ ₹0.75 through AICredits, per uncached "
                       "`/troubleshoot` query on Claude Haiku 5.5; identical requests are served from the response cache).", ""]
            params = [p for p in op.get("parameters", [])]
            if params:
                md += ["**Parameters**", "", "| Name | In | Type | Required | Description |", "|---|---|---|---|---|"]
                md += [f"| `{p['name']}` | {p['in']} | {type_of(p.get('schema', {}), schemas)} | "
                       f"{'yes' if p.get('required') else 'no'} | {p.get('description', '')} |" for p in params]
                md.append("")
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if body and "$ref" in body:
                name = body["$ref"].split("/")[-1]
                md += [f"**Request body** (`{name}`)", "", field_table(name, schemas), ""]
                used.append(name)
            ok = op["responses"].get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})
            if "$ref" in ok:
                name = ok["$ref"].split("/")[-1]
                md += [f"**Response 200** (`{name}`)", "", field_table(name, schemas), ""]
                used.append(name)
            for e in by_path.get(path, []):
                kind = "Sample" if e["status"] < 400 else "Error example"
                md += [f"**{kind}: {e['name']}** (HTTP {e['status']})" + (f". {e['note']}" if e.get("note") else ""), ""]
                if e["request"] is not None:
                    curl = (f"curl -X {e['method']} http://localhost:8000{e['path']} -H \"Content-Type: application/json\" "
                            f"-d '{json.dumps(e['request'])}'")
                else:
                    curl = f"curl http://localhost:8000{e['path']}"
                md += ["```bash", curl, "```", "", "```json", json.dumps(shorten(e["response"]), indent=2), "```", ""]
    nested, queue = [], [r for name in used for r in refs_in(name, schemas)]
    while queue:  # every model referenced by the endpoint tables, transitively, one table each
        name = queue.pop(0)
        if name not in nested and name not in used:
            nested.append(name)
            queue += refs_in(name, schemas)
    md += ["## 3. Nested models", "", "Models referenced by the request and response tables above.", ""]
    for name in nested:
        md += [f"### `{name}`", "", field_table(name, schemas), ""]
    md += ["## 4. Full schema", "",
           "The full machine-readable schema, including every nested model (`TroubleshootResponse`, `Recommendation`, "
           "`RootCauseAnalysis`, `Priority`, ...), is served at `GET /openapi.json` and browsable at `/docs`. "
           f"The schema has {len(schemas)} models.", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT.relative_to(PROJECT_ROOT)} ({len(md)} lines)")


if __name__ == "__main__":
    main()
