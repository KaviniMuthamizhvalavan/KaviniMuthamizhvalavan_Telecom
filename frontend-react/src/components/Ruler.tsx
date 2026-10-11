// One shared 0-100 percentile ruler for every KPI: position = share of historical records this value is worse
// than. Bands mark the baseline: normal up to p75, degraded to p90, critical beyond. Same scale everywhere, so
// severity compares at a glance.
import type { Anomaly, KpiInfo, PerKpi } from '../api/types'
import { fmtValue } from '../lib/format'
import { BandMark } from './ui'

const TICKS = [0, 25, 50, 75, 90]

/** Worse-than share in 0-100. Troubleshoot and prioritize send worse_than_pct; search and case detail send a
 * direction-adjusted percentile in 0-1. */
export const worseThan = (a: Pick<Anomaly, 'percentile' | 'worse_than_pct'>) => a.worse_than_pct ?? a.percentile * 100

export function RulerTrack({ pct, band, label }: { pct: number; band: string; label: string }) {
  const x = Math.max(0, Math.min(100, pct))
  return (
    <div className="ruler" role="img" aria-label={`${label}: worse than ${x.toFixed(0)}% of records`}>
      <span className="ruler-band normal" style={{ width: '75%' }} />
      <span className="ruler-band degraded" style={{ left: '75%', width: '15%' }} />
      <span className="ruler-band critical" style={{ left: '90%', width: '10%' }} />
      <span className={`ruler-marker band-${band}`} style={{ left: `${x}%` }} />
    </div>
  )
}

export function RulerScale() {
  return (
    <div className="ruler-scale" aria-hidden>
      {TICKS.map((t) => (
        <span key={t} style={{ left: `${t}%` }}>
          {t}
        </span>
      ))}
    </div>
  )
}

type Row = (Anomaly | PerKpi) & { worse_than_pct?: number }

const short = (v: number) => fmtValue(Math.abs(v) >= 100 ? Math.round(v) : Math.round(v * 100) / 100)

/** "typical 77, degraded beyond 105" from /metadata percentiles; direction-aware (low throughput is bad). */
function baseline(k: KpiInfo | undefined): string | null {
  if (!k) return null
  const worse = k.direction < 0 ? 'below' : 'above'
  // For "lower is worse" KPIs the degraded threshold is the 25th percentile of raw values.
  const deg = k.direction < 0 ? k.p25 : k.p75
  return `typical ${short(k.p50)}, degraded ${worse} ${short(deg)}`
}

export function KpiRulers({ rows, caption, kpis }: { rows: Row[]; caption?: string; kpis?: KpiInfo[] }) {
  const spec = Object.fromEntries((kpis ?? []).map((k) => [k.name, k]))
  return (
    <div className="kpi-rulers">
      <div className="kpi-row kpi-head">
        <span>KPI</span>
        <span className="r">Value</span>
        <span className="kpi-scale-label">
          <span>Worse than this share of records (%)</span>
          <RulerScale />
        </span>
        <span>Band</span>
      </div>
      {rows.map((a) => {
        const w = worseThan(a)
        return (
          <div className="kpi-row" key={a.kpi}>
            <span className="kpi-name">
              {a.label}
              {'imputed' in a && a.imputed ? <span className="muted small"> (imputed)</span> : null}
            </span>
            <span className="r kpi-valcell">
              <span className="num kpi-val">
                {fmtValue(a.value)} <span className="muted">{a.unit}</span>
              </span>
              {baseline(spec[a.kpi]) && <span className="kpi-base">{baseline(spec[a.kpi])}</span>}
            </span>
            <span className="kpi-track">
              <RulerTrack pct={w} band={a.band} label={a.label} />
              <span className="kpi-pct num">{w.toFixed(0)}%</span>
            </span>
            <span>
              <BandMark band={a.band} />
            </span>
          </div>
        )
      })}
      {caption && <p className="kpi-caption">{caption}</p>}
    </div>
  )
}
