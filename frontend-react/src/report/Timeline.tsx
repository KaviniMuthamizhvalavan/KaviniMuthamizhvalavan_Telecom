// The signature move: the report's own timestamped timeline. While the analysis runs, it shows the expected
// sequence with an estimated position (the backend answers in one response, so no step is reported live);
// when the report arrives, the real per-step trace replaces it.
import { Check, Circle, Warning } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type { RunMeta, TraceEntry } from '../api/types'
import { STEP_LABEL } from '../lib/copy'
import { fmtNum, fmtSeconds } from '../lib/format'

// Typical step durations (ms) from the recorded Claude Haiku run in tests/test_cases/api_examples.json (32.2 s),
// and from the recorded reduced-mode run (1.0 s).
const TYPICAL_FULL: [string, number][] = [
  ['gate', 0],
  ['classify', 1900],
  ['retrieve', 120],
  ['gather_evidence', 630],
  ['analyze', 12100],
  ['recommend', 6300],
  ['judge', 11100],
  ['finalize', 0],
]
const TYPICAL_REDUCED: [string, number][] = [
  ['gate', 0],
  ['rules', 5],
  ['retrieve', 150],
  ['gather_evidence', 710],
  ['reduced', 20],
  ['finalize', 0],
]

/** Cached calls are counted separately from new (billed) calls by the backend's run budget. */
export function cacheNote(meta: RunMeta): string | null {
  if (!meta.cached_calls) return null
  if (!meta.llm_calls) return `All ${meta.cached_calls} model calls were served from the response cache: no model cost.`
  return `${meta.cached_calls} model call${meta.cached_calls === 1 ? ' was' : 's were'} served from the response cache.`
}

function useElapsed(startedAt: number | null) {
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    if (startedAt == null) return
    const t = setInterval(() => setNow(performance.now()), 100)
    return () => clearInterval(t)
  }, [startedAt])
  return startedAt == null ? 0 : Math.max(0, now - startedAt)
}

export function LiveTimeline({ startedAt, reduced }: { startedAt: number | null; reduced: boolean }) {
  const elapsed = useElapsed(startedAt)
  const steps = reduced ? TYPICAL_REDUCED : TYPICAL_FULL
  let t = 0
  const rows = steps.map(([node, ms]) => {
    const start = t
    t += ms
    return { node, start, end: t }
  })
  const total = t
  // Estimated position: the first step whose typical end is still ahead. Past the typical total, the last
  // model step stays "in progress" (the judge may have asked for one revision).
  let current = rows.findIndex((r) => elapsed < r.end)
  if (current === -1) current = rows.length - 2
  return (
    <div className="timeline" aria-live="off">
      <div className="timeline-head">
        <span className="timeline-title">Analysis running</span>
        <span className="timeline-clock num" aria-label={`${fmtSeconds(elapsed)} seconds elapsed`}>
          T+{fmtSeconds(elapsed)} s
        </span>
      </div>
      <ol className="tl-list">
        {rows.map((r, i) => {
          const state = i < current ? 'done' : i === current ? 'active' : 'queued'
          return (
            <li key={r.node} className={`tl-row ${state}`}>
              <span className="tl-time num">T+{fmtSeconds(r.start)}</span>
              <span className="tl-dot" aria-hidden>
                {state === 'done' ? <Check size={11} weight="bold" /> : <Circle size={9} weight={state === 'active' ? 'fill' : 'regular'} />}
              </span>
              <span className="tl-label">{STEP_LABEL[r.node] ?? r.node}</span>
              <span className="tl-state">{state === 'active' ? 'in progress' : state === 'done' ? '' : ''}</span>
            </li>
          )
        })}
      </ol>
      <p className="timeline-note">
        Expected sequence. Positions are estimated from a typical {fmtSeconds(total, 0)} s run; the real step timings replace them when the report arrives.
      </p>
    </div>
  )
}

export function TraceTimeline({ trace, meta, compact }: { trace: TraceEntry[]; meta: RunMeta; compact?: boolean }) {
  if (!trace.length) return <p className="muted small">The trace was not requested for this run.</p>
  let t = 0
  const rows = trace.map((e) => {
    const start = t
    t += e.ms
    return { ...e, start }
  })
  const cached = meta.cached_calls
  return (
    <div className={`timeline done${compact ? ' compact' : ''}`}>
      <div className="timeline-head">
        <span className="timeline-title">Agent trace</span>
        <span className="timeline-clock num">{fmtSeconds(meta.latency_ms)} s</span>
      </div>
      <ol className="tl-list">
        {rows.map((r, i) => {
          const fallback = r.status === 'fallback'
          return (
            <li key={`${r.node}-${i}`} className={`tl-row done${fallback ? ' fallback' : ''}`}>
              <span className="tl-time num">T+{fmtSeconds(r.start)}</span>
              <span className="tl-dot" aria-hidden>
                {fallback ? <Warning size={11} weight="bold" /> : <Check size={11} weight="bold" />}
              </span>
              <span className="tl-label">
                {STEP_LABEL[r.node] ?? r.node}
                {fallback && <span className="tl-flag"> rule-based fallback</span>}
                {!compact && r.tool_calls.length > 0 && <span className="tl-tools">{r.tool_calls.join(', ')}</span>}
              </span>
              <span className="tl-state num">
                {r.ms >= 50 ? `${fmtSeconds(r.ms)} s` : r.ms > 0 ? `${Math.round(r.ms)} ms` : ''}
                {r.llm_calls > 0 && !compact && (
                  <span className="tl-tokens">
                    {r.llm_calls} call{r.llm_calls > 1 ? 's' : ''}, {fmtNum(r.tokens_in + r.tokens_out)} tokens
                  </span>
                )}
              </span>
            </li>
          )
        })}
      </ol>
      <p className="timeline-note">
        {meta.model === 'none' ? (
          'No AI model: rule-based steps only.'
        ) : (
          <>
            {meta.llm_calls} new model call{meta.llm_calls === 1 ? '' : 's'}, {fmtNum(meta.tokens_in + meta.tokens_out)} tokens. Agents <span className="id">{meta.model}</span>, judge <span className="id">{meta.judge_model}</span>.
            {cached > 0 && <strong className="cache-note"> {cacheNote(meta)}</strong>}
          </>
        )}
      </p>
    </div>
  )
}
