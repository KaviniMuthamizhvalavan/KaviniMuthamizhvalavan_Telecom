"""Phase 0 environment and feasibility smoke tests.

Run from the repo root:  python -m scripts.check_env [--skip-llm] [--judge-model MODEL]
Prints PASS/FAIL with timings per component. Never prints API keys.
"""
import argparse
import json
import random
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

from pydantic import BaseModel

from src.utils.config import get_settings
from src.utils.net import use_system_certificates

use_system_certificates()

RESULTS: list[tuple[str, bool, str]] = []

# Preference order for a judge model from a different family than the Llama runtime model.
JUDGE_CANDIDATES = (
    "qwen/qwen2.5-72b-instruct",
    "qwen/qwen3-next-80b-a3b-instruct",
    "mistralai/mistral-large-2-instruct",
    "mistralai/mistral-medium-3-instruct",
    "mistralai/mixtral-8x22b-instruct-v0.1",
    "google/gemma-3-27b-it",
    "openai/gpt-oss-120b",
)


def check(name):
    def wrap(fn):
        def run(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                detail = fn(*args, **kwargs) or ""
                RESULTS.append((name, True, f"{detail} ({time.perf_counter() - t0:.1f}s)"))
            except Exception as exc:  # report and continue with the remaining checks
                RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"[:300]))
                traceback.print_exc(limit=1, file=sys.stderr)
        return run
    return wrap


def synthetic_narratives(n: int) -> list[str]:
    """Short texts shaped like the planned case narratives (not real data)."""
    rnd = random.Random(0)
    symptoms = ["critical packet loss", "high latency", "reduced throughput", "weak signal", "dropped calls",
                "handover failures", "critical alarms", "authentication failures", "low availability"]
    states, seasons = ["TX", "MN", "CA", "NY", "OH"], ["Winter", "Summer", "Spring", "Fall"]
    out = []
    for i in range(n):
        picked = rnd.sample(symptoms, 3)
        out.append(f"CASE-{i:06d} {rnd.choice(states)} {rnd.choice(seasons)}. Critical: {picked[0]}. "
                   f"Degraded: {picked[1]}, {picked[2]}. Priority P{rnd.randint(1, 4)}.")
    return out


# ---------------------------------------------------------------- LLM checks
@check("config: NVIDIA key loaded")
def check_config():
    s = get_settings()
    if not s.llm_api_key:
        raise RuntimeError("no LLM_API_KEY / NVIDIA_API_KEY found in environment or .env")
    return f"key present ({len(s.llm_api_key)} chars), base_url={s.llm_base_url}, model={s.llm_model}"


def _client():
    from openai import OpenAI
    s = get_settings()
    return OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, max_retries=2, timeout=90)


@check("llm: plain chat")
def check_chat():
    s = get_settings()
    t0 = time.perf_counter()
    r = _client().chat.completions.create(
        model=s.llm_model, temperature=0, max_tokens=20,
        messages=[{"role": "user", "content": "Reply with exactly: OK"}])
    text = (r.choices[0].message.content or "").strip()
    usage = r.usage
    return f"reply={text!r}, latency={time.perf_counter() - t0:.1f}s, tokens={usage.total_tokens if usage else '?'}"


class _Classification(BaseModel):
    primary_category: str
    symptoms: list[str]
    confidence: float


@check("llm: JSON mode -> Pydantic")
def check_json():
    s = get_settings()
    schema = json.dumps(_Classification.model_json_schema())
    r = _client().chat.completions.create(
        model=s.llm_model, temperature=0, max_tokens=200, response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": f"Respond with JSON only, matching this schema: {schema}"},
            {"role": "user", "content": "Classify: high latency and packet loss at a cell in Texas. "
                                        "Categories: TRANSPORT_QOS, RADIO_COVERAGE, CONGESTION_CAPACITY."}])
    parsed = _Classification.model_validate_json(r.choices[0].message.content)
    return f"primary={parsed.primary_category}, symptoms={parsed.symptoms}"


@check("llm: tool call round trip")
def check_tools():
    s = get_settings()
    tools = [{"type": "function", "function": {
        "name": "segment_stats", "description": "Statistics for historical network cases in a US state.",
        "parameters": {"type": "object", "properties": {"state": {"type": "string"}}, "required": ["state"]}}}]
    messages = [{"role": "user", "content": "How many historical cases are there in TX? Use the tool."}]
    client = _client()
    r1 = client.chat.completions.create(model=s.llm_model, temperature=0, max_tokens=200,
                                        messages=messages, tools=tools, tool_choice="auto")
    msg = r1.choices[0].message
    if not msg.tool_calls:
        raise RuntimeError(f"model did not call the tool: {msg.content!r}")
    call = msg.tool_calls[0]
    args = json.loads(call.function.arguments)
    messages += [msg.model_dump(exclude_none=True),
                 {"role": "tool", "tool_call_id": call.id, "content": json.dumps({"count": 1711})}]
    r2 = client.chat.completions.create(model=s.llm_model, temperature=0, max_tokens=100, messages=messages)
    return f"called {call.function.name}({args}); final answer mentions 1711: {'1711' in (r2.choices[0].message.content or '').replace(',', '')}"


@check("llm: judge model (different family) JSON")
def check_judge(model_override: str | None):
    s = get_settings()
    client = _client()
    available = {m.id for m in client.models.list().data}
    candidates = [model_override] if model_override else ([s.eval_llm_model] if s.eval_llm_model else [])
    candidates += [m for m in JUDGE_CANDIDATES if m in available and m not in candidates]
    tried = []
    for model in candidates:
        try:
            r = client.chat.completions.create(
                model=model, temperature=0, max_tokens=300,
                messages=[{"role": "system", "content": 'Respond with JSON only: {"score": <0..1>, "reason": "<short>"}'},
                          {"role": "user", "content": "Is 'Check backhaul links for packet loss' a relevant action for "
                                                      "high packet loss? Score relevance."}])
            from evaluation.deepeval_judge import _extract_json
            data = json.loads(_extract_json(r.choices[0].message.content or ""))
            float(data["score"])
            return f"usable judge: {model} (score={data['score']}); catalog has {len(available)} models"
        except Exception as exc:
            tried.append(f"{model}: {type(exc).__name__}")
    raise RuntimeError(f"no judge candidate worked; tried {tried}")


@check("deepeval: AnswerRelevancy with custom judge")
def check_deepeval(model_override: str | None):
    import evaluation  # noqa: F401 - sets the DeepEval telemetry opt-out before DeepEval is imported
    from deepeval.metrics import AnswerRelevancyMetric
    from deepeval.test_case import LLMTestCase

    from evaluation.deepeval_judge import OpenAICompatibleJudge
    judge = OpenAICompatibleJudge(model=model_override) if model_override else OpenAICompatibleJudge()
    metric = AnswerRelevancyMetric(threshold=0.7, model=judge, async_mode=False, include_reason=False)
    case = LLMTestCase(
        input="A cell has high latency and packet loss. What should I check first?",
        actual_output="Check the transport backhaul for congestion and packet loss, then review recent alarms.")
    metric.measure(case)
    return f"judge={judge.get_model_name()}, score={metric.score:.2f}"


# ---------------------------------------------------------------- local checks
@check("embeddings: bge-small throughput")
def check_embeddings():
    from sentence_transformers import SentenceTransformer
    s = get_settings()
    t0 = time.perf_counter()
    model = SentenceTransformer(s.embedding_model, device="cpu")
    load = time.perf_counter() - t0
    texts = synthetic_narratives(2000)
    t1 = time.perf_counter()
    vecs = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    rate = len(texts) / (time.perf_counter() - t1)
    return f"dim={vecs.shape[1]}, load={load:.1f}s, {rate:.0f} docs/s -> 100k est. {100_000 / rate / 60:.1f} min"


@check("chroma: 5k upsert, 45 metadata fields, $and query")
def check_chroma():
    import chromadb
    import numpy as np
    tmp = Path(tempfile.mkdtemp(prefix="chroma_smoke_"))
    try:
        client = chromadb.PersistentClient(path=str(tmp), settings=chromadb.Settings(anonymized_telemetry=False))
        coll = client.get_or_create_collection("smoke", metadata={"hnsw:space": "cosine"})
        rnd = np.random.default_rng(0)
        n, batch = 5000, client.get_max_batch_size()
        emb = rnd.normal(size=(n, 384)).astype("float32")
        emb /= np.linalg.norm(emb, axis=1, keepdims=True)
        metas = []
        for i in range(n):
            m = {"state": ["TX", "MN", "CA"][i % 3], "season": ["Winter", "Summer"][i % 2],
                 "priority": f"P{i % 4 + 1}", "primary_category": "TRANSPORT_QOS"}
            m.update({f"sym_{k}": bool((i >> k) & 1) for k in range(19)})
            m.update({f"kpi_{k}": float(rnd.random()) for k in range(22)})
            metas.append(m)
        t0 = time.perf_counter()
        for s in range(0, n, batch):
            coll.upsert(ids=[f"CASE-{i:06d}" for i in range(s, min(s + batch, n))],
                        embeddings=emb[s:s + batch].tolist(), metadatas=metas[s:s + batch])
        upsert_s = time.perf_counter() - t0
        where = {"$and": [{"state": "TX"}, {"season": "Winter"}, {"sym_1": True}]}
        t1 = time.perf_counter()
        res = coll.query(query_embeddings=[emb[0].tolist()], n_results=50, where=where)
        q_ms = (time.perf_counter() - t1) * 1000
        ok = all(m["state"] == "TX" and m["season"] == "Winter" and m["sym_1"] for m in res["metadatas"][0])
        if not ok:
            raise RuntimeError("filter not respected")
        return (f"{len(metas[0])} fields, max_batch={batch}, upsert {n / upsert_s:.0f} docs/s "
                f"(100k est. {100_000 / (n / upsert_s) / 60:.1f} min), filtered query {q_ms:.0f} ms, "
                f"{len(res['ids'][0])} hits all compliant")
    finally:
        del client
        shutil.rmtree(tmp, ignore_errors=True)


@check("bm25s: 100k docs, full score vector + mask")
def check_bm25():
    import bm25s
    import numpy as np
    import Stemmer
    stemmer = Stemmer.Stemmer("english")
    texts = synthetic_narratives(100_000)
    t0 = time.perf_counter()
    tokens = bm25s.tokenize(texts, stopwords="en", stemmer=stemmer, show_progress=False)
    retriever = bm25s.BM25()
    retriever.index(tokens, show_progress=False)
    build = time.perf_counter() - t0
    q = bm25s.tokenize(["high latency and packet loss in winter"], stopwords="en", stemmer=stemmer,
                       show_progress=False, return_ids=False)[0]
    t1 = time.perf_counter()
    scores = retriever.get_scores(q)
    mask = np.zeros(len(texts), dtype=bool)
    mask[::3] = True
    masked = np.where(mask, scores, -np.inf)
    top = np.argpartition(-masked, 50)[:50]
    q_ms = (time.perf_counter() - t1) * 1000
    if scores.shape[0] != len(texts) or not mask[top].all():
        raise RuntimeError("score vector or mask wrong")
    return f"build {build:.1f}s, query+mask {q_ms:.0f} ms, vector len {scores.shape[0]}"


@check("langgraph: conditional graph + mermaid export")
def check_langgraph():
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class S(TypedDict):
        llm: bool
        path: list

    g = StateGraph(S)
    g.add_node("gate", lambda s: {"path": s["path"] + ["gate"]})
    g.add_node("classify", lambda s: {"path": s["path"] + ["classify"]})
    g.add_node("rules", lambda s: {"path": s["path"] + ["rules"]})
    g.add_edge(START, "gate")
    g.add_conditional_edges("gate", lambda s: "classify" if s["llm"] else "rules", ["classify", "rules"])
    g.add_edge("classify", END)
    g.add_edge("rules", END)
    app = g.compile()
    a = app.invoke({"llm": True, "path": []})["path"]
    b = app.invoke({"llm": False, "path": []})["path"]
    mermaid = app.get_graph().draw_mermaid()
    if a != ["gate", "classify"] or b != ["gate", "rules"]:
        raise RuntimeError(f"routing wrong: {a} {b}")
    return f"routes ok ({a} / {b}), mermaid {len(mermaid)} chars"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-llm", action="store_true", help="skip checks that call the LLM API")
    parser.add_argument("--judge-model", default=None)
    args = parser.parse_args()

    print(f"Python {sys.version.split()[0]}")
    check_config()
    if not args.skip_llm:
        check_chat()
        check_json()
        check_tools()
        check_judge(args.judge_model)
        check_deepeval(args.judge_model)
    check_embeddings()
    check_chroma()
    check_bm25()
    check_langgraph()

    print("\n" + "=" * 100)
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name:48s} {detail}")
    failed = sum(not ok for _, ok, _ in RESULTS)
    print("=" * 100 + f"\n{len(RESULTS) - failed}/{len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
