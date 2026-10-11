// The five data charts. Hand-built (HTML and CSS, no chart library), palette tokens only, every value also
// printed as text, and each chart has a "Show table" switch to the underlying numbers.
import { useState, type ReactNode } from 'react'
import type { Anomaly, KpiInfo, RunMeta, TraceEntry } from '../api/types'
import { STEP_LABEL } from '../lib/copy'
import { fmtMbps, fmtNum, fmtSeconds, fmtSignedPct, fmtValue } from '../lib/format'
import { RulerScale, RulerTrack, worseThan } from './Ruler'
import { BandMark } from './ui'

const clamp = (v: number, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, v))

/** A chart with a switch to its table. The table is the same data, nothing hidden. */
export function ChartBlock({ title, chart, table, caption }: { title?: ReactNode; chart: ReactNode; table: ReactNode; caption?: ReactNode }) {
  const [asTable, setAsTable] = useState(false)
  return (
    <figure className="chart-block">
      <div className="chart-head">
        {title && <figcaption className="chart-title">{title}</figcaption>}
        <button type="button" className="btn-link chart-toggle" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>
          {asTable ? 'Show chart' : 'Show table'}
        </button>
      </div>
      {asTable ? <div className="tbl-wrap">{table}</div> : chart}
      {caption && <p className="chart-caption">{caption}</p>}
    </figure>
  )
}

// ---------------------------------------------------------------- 1. KPI percentile strip (top of the report)
/** Worst first: critical before degraded, then by worse-than share. */
export function worstKpis(anomalies: Anomaly[], n = 4): Anomaly[] {
  const rank = (a: Anomaly) => (a.band === 'critical' ? 1000 : a.band === 'degraded' ? 500 : 0) + worseThan(a)
  return [...anomalies].sort((a, b) => rank(b) - rank(a)).slice(0, n)
}

export function PercentileStrip({ anomalies }: { anomalies: Anomaly[] }) {
  const top = worstKpis(anomalies)
  return (
    <ul className="pstrip" aria-label="Most abnormal KPIs">
      {top.map((a) => {
        const w = worseThan(a)
        return (
          <li key={a.kpi} className="pstrip-row">
            <span className="pstrip-name">{a.label}</span>
            <span className="pstrip-val num">
              {fmtValue(a.value)} <span className="muted">{a.unit}</span>
            </span>
            <RulerTrack pct={w} band={a.band} label={a.label} />
            <span className="pstrip-band">
              <span className="num">{w.toFixed(0)}%</span> <BandMark band={a.band} />
            </span>
          </li>
        )
      })}
      <li className="pstrip-row pstrip-scale" aria-hidden>
        <span className="pstrip-name">Worse than % of records</span>
        <span />
        <RulerScale />
        <span />
      </li>
    </ul>
  )
}

export function PercentileTable({ anomalies }: { anomalies: Anomaly[] }) {
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th scope="col">KPI</th>
          <th scope="col" className="r">Value</th>
          <th scope="col" className="r">Worse than (% of records)</th>
          <th scope="col">Band</th>
        </tr>
      </thead>
      <tbody>
        {worstKpis(anomalies, anomalies.length).map((a) => (
          <tr key={a.kpi}>
            <td>{a.label}</td>
            <td className="r">
              {fmtValue(a.value)} {a.unit}
            </td>
            <td className="r">{worseThan(a).toFixed(0)}</td>
            <td>
              <BandMark band={a.band} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------- 2. expected vs observed throughput
export function ThroughputChart({ expected, observed, deficitPct, typical }: { expected: number; observed: number | null; deficitPct: number | null; typical?: KpiInfo }) {
  const max = Math.max(expected, observed ?? 0, typical?.p75 ?? 0) * 1.1
  const x = (v: number) => clamp((v / max) * 100)
  return (
    <div className="tput" role="img" aria-label={`Expected ${fmtMbps(expected)}${observed != null ? `, observed ${fmtMbps(observed)}, ${fmtSignedPct(deficitPct)}` : ''}`}>
      <div className="tput-row">
        <span className="tput-label">Expected</span>
        <span className="tput-track">
          {typical && <span className="tput-typical" style={{ left: `${x(typical.p25)}%`, width: `${x(typical.p75) - x(typical.p25)}%` }} />}
          <span className="tput-bar expected" style={{ width: `${x(expected)}%` }} />
        </span>
        <span className="tput-val num">{fmtMbps(expected)}</span>
      </div>
      {observed != null && (
        <div className="tput-row">
          <span className="tput-label">Observed</span>
          <span className="tput-track">
            {typical && <span className="tput-typical" style={{ left: `${x(typical.p25)}%`, width: `${x(typical.p75) - x(typical.p25)}%` }} />}
            <span className="tput-bar observed" style={{ width: `${x(observed)}%` }} />
            <span className="tput-gap" style={{ left: `${x(Math.min(observed, expected))}%`, width: `${Math.abs(x(expected) - x(observed))}%` }} />
          </span>
          <span className="tput-val num">
            {fmtMbps(observed)} <span className={deficitPct != null && deficitPct < 0 ? 'tput-deficit' : 'muted'}>{fmtSignedPct(deficitPct)}</span>
          </span>
        </div>
      )}
      {typical && (
        <p className="tput-legend">
          <span className="tput-swatch" aria-hidden /> Typical range in this network, {fmtNum(typical.p25)} to {fmtNum(typical.p75)} Mbps
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 3. agent trace waterfall
export function TraceWaterfall({ trace }: { trace: TraceEntry[] }) {
  const total = trace.reduce((s, e) => s + e.ms, 0) || 1
  let t = 0
  return (
    <ol className="wf" aria-label="Time spent per step">
      {trace.map((e, i) => {
        const start = t
        t += e.ms
        const fallback = e.status === 'fallback'
        return (
          <li key={`${e.node}-${i}`} className={`wf-row${fallback ? ' fallback' : ''}${e.llm_calls ? ' llm' : ''}`}>
            <span className="wf-label">
              {STEP_LABEL[e.node] ?? e.node}
              {fallback && <span className="tl-flag"> fallback</span>}
            </span>
            <span className="wf-track">
              <span className="wf-bar" style={{ left: `${(start / total) * 100}%`, width: `max(2px, ${(e.ms / total) * 100}%)` }} />
            </span>
            <span className="wf-ms num">{e.ms >= 50 ? `${fmtSeconds(e.ms)} s` : e.ms > 0 ? `${Math.round(e.ms)} ms` : '0'}</span>
          </li>
        )
      })}
    </ol>
  )
}

export function TraceTable({ trace, meta }: { trace: TraceEntry[]; meta: RunMeta }) {
  let t = 0
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th scope="col">Start</th>
          <th scope="col">Step</th>
          <th scope="col" className="r">Duration</th>
          <th scope="col" className="r">Model calls</th>
          <th scope="col" className="r">Tokens</th>
          <th scope="col">Tools</th>
          <th scope="col">Status</th>
        </tr>
      </thead>
      <tbody>
        {trace.map((e, i) => {
          const start = t
          t += e.ms
          return (
            <tr key={`${e.node}-${i}`}>
              <td className="num nowrap">T+{fmtSeconds(start)}</td>
              <td>{STEP_LABEL[e.node] ?? e.node}</td>
              <td className="r nowrap">{fmtSeconds(e.ms, 2)} s</td>
              <td className="r">{e.llm_calls}</td>
              <td className="r">{fmtNum(e.tokens_in + e.tokens_out)}</td>
              <td className="secondary small">{e.tool_calls.join(', ')}</td>
              <td>{e.status === 'fallback' ? 'Fallback' : 'OK'}</td>
            </tr>
          )
        })}
        <tr>
          <td />
          <td>
            <b>Total</b>
          </td>
          <td className="r nowrap">
            <b>{fmtSeconds(meta.latency_ms, 2)} s</b>
          </td>
          <td className="r">{meta.llm_calls}</td>
          <td className="r">{fmtNum(meta.tokens_in + meta.tokens_out)}</td>
          <td colSpan={2} className="secondary small">
            {meta.cached_calls ? `${meta.cached_calls} cached calls` : ''}
          </td>
        </tr>
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------- 4. judge scores against pass marks
// Pass marks of the runtime judge: groundedness 0.70, every other score 0.60.
export const passMark = (k: string) => (k === 'groundedness' ? 0.7 : 0.6)

export function ScoreBars({ scores, labels }: { scores: Record<string, number>; labels: Record<string, string> }) {
  return (
    <ul className="scores" aria-label="Judge scores against pass marks">
      {Object.entries(scores).map(([k, v]) => {
        const mark = passMark(k)
        const ok = v >= mark
        return (
          <li key={k} className={`score-row ${ok ? 'ok' : 'below'}`}>
            <span className="score-label">{labels[k] ?? k}</span>
            <span className="score-track" role="img" aria-label={`${labels[k] ?? k} ${v.toFixed(2)}, pass mark ${mark.toFixed(2)}`}>
              <span className="score-bar" style={{ width: `${clamp(v * 100)}%` }} />
              <span className="score-mark" style={{ left: `${mark * 100}%` }} />
            </span>
            <span className="score-val num">
              {v.toFixed(2)} <span className="muted">/ {mark.toFixed(2)}</span>
            </span>
          </li>
        )
      })}
    </ul>
  )
}

export function ScoreTable({ scores, labels }: { scores: Record<string, number>; labels: Record<string, string> }) {
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th scope="col">Score</th>
          <th scope="col" className="r">Value</th>
          <th scope="col" className="r">Pass mark</th>
          <th scope="col">Result</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(scores).map(([k, v]) => (
          <tr key={k}>
            <td>{labels[k] ?? k}</td>
            <td className="r">{v.toFixed(2)}</td>
            <td className="r">{passMark(k).toFixed(2)}</td>
            <td>{v >= passMark(k) ? 'Meets' : 'Below'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------- 5. basic RAG vs multi-agent (dumbbell)
export interface PairRow {
  label: string
  a: number | null
  c: number | null
}

export function Dumbbell({ rows, aLabel, cLabel }: { rows: PairRow[]; aLabel: string; cLabel: string }) {
  return (
    <div className="db">
      <p className="db-legend">
        <span className="db-dot a" aria-hidden /> {aLabel}
        <span className="db-dot c" aria-hidden /> {cLabel}
        <span className="muted">Mean score, 0 to 1</span>
      </p>
      <ul className="db-list">
        {rows.map((r) => {
          const lo = Math.min(r.a ?? r.c ?? 0, r.c ?? r.a ?? 0)
          const hi = Math.max(r.a ?? r.c ?? 0, r.c ?? r.a ?? 0)
          return (
            <li key={r.label} className="db-row">
              <span className="db-label">{r.label}</span>
              <span className="db-track" role="img" aria-label={`${r.label}: ${aLabel} ${r.a?.toFixed(2) ?? 'n/a'}, ${cLabel} ${r.c?.toFixed(2) ?? 'n/a'}`}>
                <span className="db-line" style={{ left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }} />
                {r.a != null && <span className="db-dot a" style={{ left: `${r.a * 100}%` }} />}
                {r.c != null && <span className="db-dot c" style={{ left: `${r.c * 100}%` }} />}
              </span>
              <span className="db-val num">
                {r.a?.toFixed(2) ?? 'n/a'} <span className="muted">to</span> <b>{r.c?.toFixed(2) ?? 'n/a'}</b>
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
