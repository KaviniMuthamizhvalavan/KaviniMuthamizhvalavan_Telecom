# NetOps Triage (React frontend)

The frontend for the telecom network operations assistant. It talks to the FastAPI backend over HTTP only
(`/api/v1`, proxied by Vite) and never imports `src/`.

## Run

```powershell
npm install
npm run dev          # http://localhost:5173, API expected on http://localhost:8000
```

| Variable | Default | Effect |
|---|---|---|
| `VITE_API_TARGET` | `http://localhost:8000` | Backend the dev and preview servers proxy `/api` to |
| `VITE_FIXTURES` | unset | `1` (dev server only): Investigate replays a recorded Claude Haiku run (`src/dev/troubleshoot.fixture.json`) instead of calling `/troubleshoot`, so the UI can be worked on without AI spend. A notice says so on screen. Never included in `npm run build`. |
| `VITE_FIXTURE_VARIANT` | `full` | `reduced` replays the recorded reduced-mode run |
| `VITE_FIXTURE_DELAY_MS` | `6000` | Simulated analysis time for the fixture |

`npm test` runs the Vitest unit tests; `npm run typecheck` runs TypeScript; `npm run build` builds to `dist/`.

## Areas

| Area | What it does | Endpoints |
|---|---|---|
| Investigate | Describe an incident, live agent timeline, summary-first report, feedback | `/troubleshoot`, `/cases/{id}`, `/feedback` |
| Cases | Similar-case search with filters; compare retrieval modes | `/search`, `/cases/{id}` |
| Simulate | What-if KPIs: fault risk, throughput, priority | `/predict/fault-risk`, `/predict/performance`, `/prioritize`, `/cases/{id}` |
| Quality | Live judge verdicts, feedback loop, saved evaluation runs (switch named by models) | `/evaluation/latest`, `/feedback/summary` |

Shell: `/health` (mode: Full AI, Reduced, API offline; refreshed every 20 s), `/health?deep=true` (Test AI model,
one small model request), `/metadata`.

## Honesty rules the UI keeps

- AI analyses run only on an explicit action (Run analysis, Ctrl+Enter, or a demo preset card or number key).
- The live timeline during an analysis is the expected step sequence with an estimated position (the backend
  answers in one response). When the report arrives, the real per-step trace is in its Agent trace tab.
- KPI values are labelled Measured (entered by the user) or Estimated (median of the similar cases); severity is
  relative to this network's history (degraded > p75, critical > p90) and shown on one shared 0-100 ruler.
- Cached model calls are reported from `meta.cached_calls` ("served from the response cache").
