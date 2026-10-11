// Inputs that produce API-ready shapes: SearchFilters and KPISnapshot. Labels, ranges and medians come from /metadata.
import { useId } from 'react'
import type { KpiInfo, KpiSnapshot, Metadata, SearchFilters } from '../api/types'
import { CONTEXT_FIELDS, COPY, KEY_KPIS } from '../lib/copy'
import { COUNT_UNITS } from '../lib/format'
import { Disclosure, TokenSelect } from './ui'

export interface FilterState {
  state: string[]
  season: string[]
  weather: string[]
  priority: string[]
  categories: string[]
  symptoms: string[]
  city: string
}

export const EMPTY_FILTERS: FilterState = { state: [], season: [], weather: [], priority: [], categories: [], symptoms: [], city: '' }

export function toFilters(f: FilterState): SearchFilters | undefined {
  const out: SearchFilters = {}
  for (const k of ['state', 'season', 'weather', 'priority', 'categories', 'symptoms'] as const) if (f[k].length) out[k] = f[k]
  if (f.city.trim()) out.city = f.city.trim()
  return Object.keys(out).length ? out : undefined
}

export const filterCount = (f: FilterState) =>
  (['state', 'season', 'weather', 'priority', 'categories', 'symptoms'] as const).reduce((n, k) => n + f[k].length, 0) + (f.city.trim() ? 1 : 0)

export function FilterPanel({ meta, value, onChange }: { meta: Metadata; value: FilterState; onChange: (f: FilterState) => void }) {
  const set = <K extends keyof FilterState>(k: K, v: FilterState[K]) => onChange({ ...value, [k]: v })
  const cityId = useId()
  return (
    <div className="filter-grid">
      <TokenSelect label="State" options={meta.states.map((s) => ({ label: `${s.name} (${s.code})`, value: s.code }))} value={value.state} onChange={(v) => set('state', v)} />
      <TokenSelect label="Season" options={meta.seasons.map((s) => ({ label: s, value: s }))} value={value.season} onChange={(v) => set('season', v)} />
      <TokenSelect label="Weather" options={meta.weather.map((s) => ({ label: s, value: s }))} value={value.weather} onChange={(v) => set('weather', v)} />
      <TokenSelect label="Priority" options={meta.priorities.map((s) => ({ label: s, value: s }))} value={value.priority} onChange={(v) => set('priority', v)} />
      <TokenSelect label="Incident type" options={meta.categories.map((c) => ({ label: c.name, value: c.code }))} value={value.categories} onChange={(v) => set('categories', v)} />
      <TokenSelect label="Symptoms (all must match)" options={meta.symptoms.map((s) => ({ label: s.label[0].toUpperCase() + s.label.slice(1), value: s.code }))} value={value.symptoms} onChange={(v) => set('symptoms', v)} />
      <div className="field">
        <label className="field-label" htmlFor={cityId}>
          City
        </label>
        <input id={cityId} className="input" value={value.city} onChange={(e) => set('city', e.target.value)} placeholder="Optional" maxLength={80} />
        <span className="field-hint">{COPY.cityNote}</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- KPI form
export type KpiValues = Record<string, string> // raw input text per KPI name, plus 'season' and 'weather'

export function medianValues(meta: Metadata, except: string[] = []): KpiValues {
  const out: KpiValues = {}
  for (const k of meta.kpis) if (!except.includes(k.name)) out[k.name] = String(roundFor(k, k.p50))
  return out
}

const roundFor = (k: KpiInfo, v: number) => (COUNT_UNITS.has(k.unit) ? Math.round(v) : Math.round(v * 100) / 100)

export function kpiError(k: KpiInfo, raw: string | undefined): string | null {
  if (raw == null || raw.trim() === '') return null
  const v = Number(raw)
  if (!Number.isFinite(v)) return 'Enter a number.'
  if (v < k.min || v > k.max) return `Allowed ${k.min} to ${k.max}.`
  return null
}

/** Snapshot with only the filled, valid fields. Returns null when any field is invalid. */
export function toSnapshot(meta: Metadata, values: KpiValues): KpiSnapshot | null {
  const out: KpiSnapshot = {}
  for (const k of meta.kpis) {
    const raw = values[k.name]
    if (raw == null || raw.trim() === '') continue
    if (kpiError(k, raw)) return null
    out[k.name] = Number(raw)
  }
  if (values.season) out.season = values.season
  if (values.weather) out.weather = values.weather
  return out
}

function KpiInput({ k, value, onChange, optional }: { k: KpiInfo; value: string; onChange: (v: string) => void; optional?: boolean }) {
  const id = useId()
  const err = kpiError(k, value)
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {k.label}
        {k.unit && <span className="muted"> ({k.unit})</span>}
        {optional && <span className="muted">, optional</span>}
      </label>
      <input
        id={id}
        className="input num"
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={!!err}
        aria-describedby={`${id}-h`}
        placeholder={`median ${roundFor(k, k.p50)}`}
      />
      <span className="field-hint" id={`${id}-h`} style={err ? { color: 'var(--sev-critical)' } : undefined}>
        {err ?? `Typical ${roundFor(k, k.p25)} to ${roundFor(k, k.p75)}`}
      </span>
    </div>
  )
}

export function KpiForm({ meta, values, onChange, optional = [] }: { meta: Metadata; values: KpiValues; onChange: (v: KpiValues) => void; optional?: string[] }) {
  const specs = Object.fromEntries(meta.kpis.map((k) => [k.name, k]))
  const set = (name: string, v: string) => onChange({ ...values, [name]: v })
  const rest = meta.kpis.map((k) => k.name).filter((n) => !KEY_KPIS.includes(n) && !CONTEXT_FIELDS.includes(n))
  const seasonId = useId()
  const weatherId = useId()
  return (
    <div className="kpi-form">
      <div className="kpi-grid">
        {KEY_KPIS.filter((n) => specs[n]).map((n) => (
          <KpiInput key={n} k={specs[n]} value={values[n] ?? ''} onChange={(v) => set(n, v)} optional={optional.includes(n)} />
        ))}
      </div>
      <Disclosure summary="More KPIs and context" aside={`${rest.length + CONTEXT_FIELDS.length + 2} fields`}>
        <div className="kpi-grid">
          {[...rest, ...CONTEXT_FIELDS]
            .filter((n) => specs[n])
            .map((n) => (
              <KpiInput key={n} k={specs[n]} value={values[n] ?? ''} onChange={(v) => set(n, v)} />
            ))}
          <div className="field">
            <label className="field-label" htmlFor={seasonId}>
              Season
            </label>
            <select id={seasonId} className="select" value={values.season ?? ''} onChange={(e) => set('season', e.target.value)}>
              <option value="">Not set</option>
              {meta.seasons.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor={weatherId}>
              Weather
            </label>
            <select id={weatherId} className="select" value={values.weather ?? ''} onChange={(e) => set('weather', e.target.value)}>
              <option value="">Not set</option>
              {meta.weather.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
        </div>
      </Disclosure>
    </div>
  )
}
