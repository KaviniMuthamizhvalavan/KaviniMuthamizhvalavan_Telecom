// The query composer: description, examples, optional filters and KPI values. AI calls happen only on an
// explicit action: the Run button, Ctrl+Enter, or (demo mode) a preset card / number key.
import { Play, Stop } from '@phosphor-icons/react'
import { useEffect, useId, useRef } from 'react'
import type { Metadata, TroubleshootRequest } from '../api/types'
import { EMPTY_FILTERS, FilterPanel, filterCount, KpiForm, toFilters, toSnapshot, type FilterState, type KpiValues } from '../components/forms'
import { Disclosure } from '../components/ui'
import { EXAMPLES } from '../lib/copy'
import { usePrefs } from '../state/prefs'
import type { Mode } from '../state/queries'

export interface ComposerState {
  query: string
  filters: FilterState
  useKpis: boolean
  kpis: KpiValues
  topK: number
}

export const EMPTY_COMPOSER: ComposerState = { query: '', filters: EMPTY_FILTERS, useKpis: false, kpis: {}, topK: 5 }

export function buildRequest(meta: Metadata, s: ComposerState, query = s.query): TroubleshootRequest | string {
  const q = query.trim()
  if (q.length < 5) return 'Enter a problem description of at least 5 characters.'
  const body: TroubleshootRequest = { query: q, top_k: s.topK, options: { include_trace: true } }
  const filters = toFilters(s.filters)
  if (filters) body.filters = filters
  if (s.useKpis) {
    const snap = toSnapshot(meta, s.kpis)
    if (snap === null) return 'Fix the highlighted KPI values, or clear "Use these KPI values".'
    if (Object.keys(snap).length) body.kpis = snap
  }
  return body
}

interface Props {
  meta: Metadata
  state: ComposerState
  onChange: (s: ComposerState) => void
  onRun: (query?: string) => void
  onCancel: () => void
  running: boolean
  mode: Mode
  error: string | null
  collapsed?: boolean
  onExpand?: () => void
  onNew?: () => void
}

export function Composer({ meta, state, onChange, onRun, onCancel, running, mode, error, collapsed, onExpand, onNew }: Props) {
  const { demo } = usePrefs()
  const qId = useId()
  const ref = useRef<HTMLTextAreaElement>(null)
  const set = <K extends keyof ComposerState>(k: K, v: ComposerState[K]) => onChange({ ...state, [k]: v })

  // Demo mode: number keys 1-5 run a preset when focus is not in a text field.
  useEffect(() => {
    if (!demo) return
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.ctrlKey || e.metaKey || e.altKey || t.closest('input, textarea, select, [contenteditable]')) return
      const i = Number(e.key) - 1
      if (i >= 0 && i < EXAMPLES.length && !running) {
        e.preventDefault()
        onChange({ ...state, query: EXAMPLES[i].query })
        onRun(EXAMPLES[i].query)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [demo, running, state, onChange, onRun])

  const nFilters = filterCount(state.filters)
  const presets = demo && (
    <ol className="presets" aria-label="Demo incidents">
      {EXAMPLES.map((ex, i) => (
        <li key={ex.label}>
          <button
            type="button"
            className="preset"
            disabled={running}
            aria-current={state.query === ex.query ? 'true' : undefined}
            onClick={() => {
              onChange({ ...state, query: ex.query })
              onRun(ex.query)
            }}
          >
            <span className="kbd">{i + 1}</span>
            <span className="preset-label">{ex.label}</span>
            <span className="preset-q">{ex.query}</span>
          </button>
        </li>
      ))}
    </ol>
  )

  if (collapsed) {
    return (
      <div className="composer composer-collapsed">
        {demo && (
          <ol className="presets-compact" aria-label="Demo incidents">
            {EXAMPLES.map((ex, i) => (
              <li key={ex.label}>
                <button
                  type="button"
                  className="preset-mini"
                  disabled={running}
                  aria-current={state.query === ex.query ? 'true' : undefined}
                  onClick={() => {
                    onChange({ ...state, query: ex.query })
                    onRun(ex.query)
                  }}
                >
                  <span className="kbd">{i + 1}</span> {ex.label}
                </button>
              </li>
            ))}
          </ol>
        )}
        <div className="query-bar">
          <div className="query-bar-text">
            <span className="field-label">Problem description</span>
            <p>{state.query}</p>
            {(nFilters > 0 || state.useKpis) && (
              <p className="muted small">
                {[nFilters ? `${nFilters} filter${nFilters > 1 ? 's' : ''}` : '', state.useKpis ? 'KPI values used' : ''].filter(Boolean).join(', ')}
              </p>
            )}
          </div>
          <div className="query-bar-actions">
            {running ? (
              <button type="button" className="btn" onClick={onCancel}>
                <Stop size={14} weight="fill" aria-hidden /> Stop waiting
              </button>
            ) : (
              <>
                <button type="button" className="btn" onClick={onExpand}>
                  Edit and rerun
                </button>
                <button type="button" className="btn" onClick={onNew}>
                  New analysis
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault()
        onRun()
      }}
    >
      {presets}

      <div className="field">
        <label className="field-label" htmlFor={qId}>
          Describe the network problem
        </label>
        <textarea
          id={qId}
          ref={ref}
          className="textarea composer-q"
          rows={demo ? 2 : 3}
          maxLength={1000}
          value={state.query}
          placeholder="For example: calls drop when users move between cells in Ohio, handover failures are rising"
          onChange={(e) => set('query', e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault()
              onRun()
            }
          }}
          aria-describedby={`${qId}-hint`}
          aria-invalid={!!error}
        />
        <span className="field-hint" id={`${qId}-hint`}>
          Plain language works. Mention symptoms, location, season or weather if known.
        </span>
      </div>

      {!demo && (
        <div className="examples">
          <span className="examples-label">Examples</span>
          {EXAMPLES.map((ex) => (
            <button type="button" key={ex.label} className="btn-link example" onClick={() => set('query', ex.query)}>
              {ex.label}
            </button>
          ))}
        </div>
      )}

      <div className="composer-options">
        <Disclosure summary="Filters" aside={nFilters ? `${nFilters} set` : 'None'}>
          <FilterPanel meta={meta} value={state.filters} onChange={(f) => set('filters', f)} />
        </Disclosure>
        <Disclosure summary="KPI values" aside={state.useKpis ? 'Used in the analysis' : 'Not used'}>
          <label className="check" style={{ marginBottom: 'var(--s4)' }}>
            <input type="checkbox" checked={state.useKpis} onChange={(e) => set('useKpis', e.target.checked)} />
            Use these KPI values in the analysis (otherwise KPIs are estimated from similar cases)
          </label>
          <KpiForm meta={meta} values={state.kpis} onChange={(v) => set('kpis', v)} />
        </Disclosure>
      </div>

      {error && (
        <p className="composer-error" role="alert">
          {error}
        </p>
      )}

      <div className="composer-run">
        {running ? (
          <button type="button" className="btn btn-lg" onClick={onCancel}>
            <Stop size={16} weight="fill" aria-hidden /> Stop waiting
          </button>
        ) : (
          <button type="submit" className="btn btn-primary btn-lg" disabled={mode === 'offline' || mode === 'loading'}>
            <Play size={16} weight="fill" aria-hidden /> Run analysis
          </button>
        )}
        <label className="composer-topk">
          <span>Similar cases</span>
          <select className="select" value={state.topK} onChange={(e) => set('topK', Number(e.target.value))}>
            {[3, 5, 8, 10].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <span className="composer-note">
          {running
            ? 'Stopping only stops waiting here; the backend still finishes and stores the analysis.'
            : mode === 'full'
              ? 'Uses the AI model. A new description costs a small amount; a repeated one is served from the cache.'
              : mode === 'reduced'
                ? 'Reduced mode: rule-based analysis, no AI cost, a few seconds.'
                : ''}
          {!running && <span className="kbd-hint"> Ctrl+Enter runs.</span>}
        </span>
      </div>
    </form>
  )
}
