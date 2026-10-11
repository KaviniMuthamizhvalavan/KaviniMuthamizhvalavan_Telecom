"""Runs and feedback persistence in SQLite `artifacts/app.db` (plan §6.4e, §8.6).

- runs: every /recommend and /troubleshoot response (Phase 8).
- feedback / case_feedback: user ratings and per-case relevance votes (Phase 9).
- Online use: a smoothed per-(case, category) prior feeds the retriever's rerank (weight 0.1, bounded ±0.05).
- Offline use: runs rated <= 2 export to tests/test_cases/feedback_regressions.json.
The classifier correction memory (few-shot corrections) is cut for the 3-day schedule (plan §5.0): corrected
categories are stored and counted, not yet fed back to the classifier.

CLI:  python -m src.services.feedback_service --export-regressions
"""
import json
import logging
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

RUNS_DDL = """CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, created_at TEXT, endpoint TEXT, query TEXT, request_json TEXT, response_json TEXT,
    status TEXT, primary_category TEXT, priority TEXT, judge_verdict TEXT, model TEXT, prompt_version TEXT,
    latency_ms REAL, tokens_in INTEGER, tokens_out INTEGER)"""
FEEDBACK_DDL = """CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT REFERENCES runs(run_id), created_at TEXT,
    rating INTEGER, helpful INTEGER, corrected_category TEXT, comment TEXT)"""
CASE_FEEDBACK_DDL = """CREATE TABLE IF NOT EXISTS case_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT REFERENCES runs(run_id), case_id TEXT, category TEXT,
    relevant INTEGER, created_at TEXT)"""
REGRESSIONS = Path(__file__).resolve().parents[2] / "tests" / "test_cases" / "feedback_regressions.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunStore:
    """Runs, feedback and case feedback (one SQLite file, thread-safe for the API's worker threads)."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as con:
            for ddl in (RUNS_DDL, FEEDBACK_DDL, CASE_FEEDBACK_DDL):
                con.execute(ddl)
            con.execute("CREATE INDEX IF NOT EXISTS ix_case_feedback_cat ON case_feedback(category)")

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    # ------------------------------------------------------------------ runs
    def save_run(self, *, run_id: str, endpoint: str, query: str, request: dict, response: dict, status: str,
                 primary_category: str | None, priority: str | None, judge_verdict: str | None, model: str,
                 prompt_version: str, latency_ms: float, tokens_in: int, tokens_out: int) -> None:
        row = (run_id, _now(), endpoint, query, json.dumps(request, default=str), json.dumps(response, default=str),
               status, primary_category, priority, judge_verdict, model, prompt_version, latency_ms, tokens_in,
               tokens_out)
        with self._lock, self._conn() as con:
            con.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)

    def get_run(self, run_id: str) -> dict | None:
        with self._lock, self._conn() as con:
            row = con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ feedback
    def add_feedback(self, run_id: str, rating: int | None, helpful: bool | None, corrected_category: str | None,
                     comment: str | None, case_feedback: list[dict]) -> dict:
        """Returns {feedback_id, effects}. The run must exist (caller checks). Case votes use the run's category."""
        run = self.get_run(run_id)
        category = run["primary_category"] if run else None
        with self._lock, self._conn() as con:
            cur = con.execute("INSERT INTO feedback (run_id, created_at, rating, helpful, corrected_category, comment) "
                              "VALUES (?, ?, ?, ?, ?, ?)",
                              (run_id, _now(), rating, None if helpful is None else int(helpful), corrected_category,
                               comment))
            fid = cur.lastrowid
            for cf in case_feedback:
                con.execute("INSERT INTO case_feedback (run_id, case_id, category, relevant, created_at) "
                            "VALUES (?, ?, ?, ?, ?)", (run_id, cf["case_id"], category, int(cf["relevant"]), _now()))
        return {"feedback_id": fid, "effects": {"priors_updated": len(case_feedback),
                                                "correction_stored": corrected_category is not None}}

    def priors(self, category: str | None) -> dict[str, float]:
        """prior(case, category) = (relevant + 1) / (relevant + not_relevant + 2)  (Beta(1,1) smoothing, §8.6).
        Only cases with votes are returned; the retriever uses 0.5 (no effect) for the rest."""
        if not category:
            return {}
        with self._lock, self._conn() as con:
            rows = con.execute("SELECT case_id, SUM(relevant) AS up, COUNT(*) - SUM(relevant) AS down "
                               "FROM case_feedback WHERE category = ? GROUP BY case_id", (category,)).fetchall()
        return {r["case_id"]: (r["up"] + 1) / (r["up"] + r["down"] + 2) for r in rows}

    def summary(self, days: int = 30) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock, self._conn() as con:
            total_runs = con.execute("SELECT COUNT(*) FROM runs WHERE created_at >= ?", (since,)).fetchone()[0]
            fb = con.execute("SELECT COUNT(*) AS n, AVG(rating) AS avg_rating, AVG(helpful) AS helpful_rate, "
                             "SUM(corrected_category IS NOT NULL) AS corrections FROM feedback WHERE created_at >= ?",
                             (since,)).fetchone()
            by_cat = con.execute("SELECT r.primary_category AS category, COUNT(*) AS n, AVG(f.rating) AS avg_rating "
                                 "FROM feedback f JOIN runs r ON r.run_id = f.run_id WHERE f.created_at >= ? "
                                 "GROUP BY r.primary_category ORDER BY n DESC", (since,)).fetchall()
            down = con.execute("SELECT case_id, category, SUM(relevant) AS up, COUNT(*) - SUM(relevant) AS down "
                               "FROM case_feedback WHERE created_at >= ? GROUP BY case_id, category "
                               "HAVING down > 0 ORDER BY down DESC, up ASC LIMIT 10", (since,)).fetchall()
            trend = con.execute("SELECT substr(created_at, 1, 10) AS date, COUNT(*) AS n, AVG(rating) AS avg_rating "
                                "FROM feedback WHERE created_at >= ? GROUP BY date ORDER BY date", (since,)).fetchall()
        rnd = lambda v: None if v is None else round(float(v), 3)  # noqa: E731
        return {"total_runs": total_runs, "total_feedback": fb["n"], "avg_rating": rnd(fb["avg_rating"]),
                "helpful_rate": rnd(fb["helpful_rate"]),
                "by_category": [{"category": r["category"], "n": r["n"], "avg_rating": rnd(r["avg_rating"])}
                                for r in by_cat],
                "most_downvoted_cases": [{"case_id": r["case_id"], "category": r["category"], "up": r["up"],
                                          "down": r["down"]} for r in down],
                "corrections_count": int(fb["corrections"] or 0),
                "trend": [{"date": r["date"], "n": r["n"], "avg_rating": rnd(r["avg_rating"])} for r in trend]}

    # ------------------------------------------------------------------ live validation (Evaluation page)
    def validation_summary(self, days: int = 30, recent: int = 10) -> dict:
        """Runtime-judge outcomes of stored /troubleshoot runs: every run is validated by the judge agent (pass,
        fail) or not validated (reduced mode); clarification requests and rejections are not judged."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock, self._conn() as con:
            rows = con.execute("SELECT model, judge_verdict, COUNT(*) AS n, AVG(latency_ms) AS lat, "
                               "AVG(tokens_in + tokens_out) AS tok FROM runs WHERE endpoint = 'troubleshoot' "
                               "AND created_at >= ? GROUP BY model, judge_verdict", (since,)).fetchall()
            judged = con.execute("SELECT response_json FROM runs WHERE endpoint = 'troubleshoot' AND created_at >= ? "
                                 "AND judge_verdict IN ('pass', 'fail') ORDER BY created_at DESC LIMIT 500",
                                 (since,)).fetchall()
            last = con.execute("SELECT created_at, query, model, status, judge_verdict, latency_ms FROM runs "
                               "WHERE endpoint = 'troubleshoot' AND created_at >= ? ORDER BY created_at DESC LIMIT ?",
                               (since, recent)).fetchall()
        verdicts, by_model = Counter(), {}
        for r in rows:
            key = r["judge_verdict"] if r["judge_verdict"] in ("pass", "fail", "unvalidated") else "not_judged"
            verdicts[key] += r["n"]
            m = by_model.setdefault(r["model"] or "none", {"model": r["model"] or "none", "runs": 0, "pass": 0,
                                                           "fail": 0, "unvalidated": 0, "not_judged": 0,
                                                           "_lat": 0.0, "_tok": 0.0})
            m["runs"] += r["n"]
            m[key] += r["n"]
            m["_lat"] += (r["lat"] or 0) * r["n"]
            m["_tok"] += (r["tok"] or 0) * r["n"]
        models = []
        for m in sorted(by_model.values(), key=lambda x: -x["runs"]):
            lat, tok = m.pop("_lat"), m.pop("_tok")
            models.append({**m, "avg_latency_s": round(lat / m["runs"] / 1000, 1),
                           "avg_tokens": int(tok / m["runs"])})
        sums, n_scored = Counter(), 0
        for (resp,) in judged:
            try:
                scores = (json.loads(resp).get("validation") or {}).get("scores") or {}
            except ValueError:
                continue
            if scores:
                n_scored += 1
                sums.update({k: float(v) for k, v in scores.items()})
        judged_total = verdicts["pass"] + verdicts["fail"]
        return {"days": days, "total": sum(verdicts.values()),
                "verdicts": {k: verdicts[k] for k in ("pass", "fail", "unvalidated", "not_judged")},
                "pass_rate": round(verdicts["pass"] / judged_total, 3) if judged_total else None,
                "by_model": models,
                "avg_scores": {k: round(v / n_scored, 3) for k, v in sums.items()} if n_scored else None,
                "scored_runs": n_scored,
                "recent": [{"created_at": r["created_at"], "query": (r["query"] or "")[:160], "model": r["model"],
                            "status": r["status"], "verdict": r["judge_verdict"],
                            "latency_s": round((r["latency_ms"] or 0) / 1000, 1)} for r in last]}

    def low_rated_runs(self, max_rating: int = 2) -> list[dict]:
        with self._lock, self._conn() as con:
            rows = con.execute("SELECT r.run_id, r.endpoint, r.query, r.request_json, r.primary_category, "
                               "MIN(f.rating) AS rating, f.corrected_category, f.comment FROM feedback f "
                               "JOIN runs r ON r.run_id = f.run_id WHERE f.rating <= ? GROUP BY r.run_id",
                               (max_rating,)).fetchall()
        return [dict(r) for r in rows]


def save_safely(store: "RunStore | None", **kwargs) -> None:
    """Persistence must never fail a request: log and continue."""
    if store is None:
        return
    try:
        store.save_run(**kwargs)
    except Exception as exc:
        log.warning("run %s not persisted: %s", kwargs.get("run_id"), exc)


def export_regressions(store: RunStore, path: Path = REGRESSIONS) -> int:
    """Runs rated <= 2 become regression cases included in every evaluation run (plan §8.6 offline use)."""
    rows = store.low_rated_runs()
    cases = [{"id": f"FR-{r['run_id'][:8]}", "run_id": r["run_id"], "endpoint": r["endpoint"], "query": r["query"],
              "request": json.loads(r["request_json"] or "{}"), "original_category": r["primary_category"],
              "expected_primary": r["corrected_category"] or None, "rating": r["rating"], "comment": r["comment"]}
             for r in rows]
    path.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    return len(cases)


def main() -> None:
    import argparse

    from src.utils.config import get_settings
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-regressions", action="store_true")
    args = parser.parse_args()
    store = RunStore(get_settings().artifacts_dir / "app.db")
    if args.export_regressions:
        print(f"exported {export_regressions(store)} low-rated runs to {REGRESSIONS}")
    else:
        print(json.dumps(store.summary(), indent=2))


if __name__ == "__main__":
    main()
