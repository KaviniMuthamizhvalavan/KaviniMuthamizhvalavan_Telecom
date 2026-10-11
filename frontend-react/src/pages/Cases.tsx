// Case search: hybrid search over the historical records with filters, a retrieval-mode choice and a four-mode
// comparison. No AI model involved.
import { Check, MagnifyingGlass } from '@phosphor-icons/react'
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Metadata, SearchResponse } from '../api/types'
import { ApiErrorNotice } from '../components/ApiErrorNotice'
import { CaseTable } from '../components/CaseTable'
import { EMPTY_FILTERS, FilterPanel, filterCount, toFilters, type FilterState } from '../components/forms'
import { Guard } from '../components/Guard'
import { PageHead } from '../components/Shell'
import { Disclosure, Facts, Section, Seg } from '../components/ui'
import { RETRIEVAL_MODES } from '../lib/copy'
import { firstFilter, fmtNum } from '../lib/format'
import { useMetadata } from '../state/queries'

interface Submitted {
  query: string
  mode: string
  topK: number
  compare: boolean
}

// Module-level memory so a search survives switching areas (no persistence beyond the tab).
let last: { sub: Submitted; results: Record<string, SearchResponse | null>; error: ApiError | null } | null = null
let lastForm: { query: string; filters: FilterState; mode: string; topK: number; compare: boolean } | null = null

function CompareGrid({ results, symptoms, topK, meta }: { results: Record<string, SearchResponse | null>; symptoms: string[]; topK: number; meta: Metadata }) {
  const symKpi = Object.fromEntries(meta.symptoms.map((s) => [s.code, s.kpi]))
  const modes = RETRIEVAL_MODES.filter((m) => m.value in results)
  const counts: Record<string, number | null> = {}
  const matchesAll = (anoms: { kpi: string }[]) => symptoms.length > 0 && symptoms.every((s) => anoms.some((a) => a.kpi === symKpi[s]))
  for (const m of modes) {
    const r = results[m.value]
    counts[m.label] = r ? r.results.slice(0, topK).filter((c) => matchesAll(c.anomalies)).length : null
  }
  return (
    <>
      <div className="tbl-wrap">
        <table className="tbl compare">
          <thead>
            <tr>
              <th scope="col" className="r">
                Rank
              </th>
              {modes.map((m) => (
                <th scope="col" key={m.value}>
                  {m.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: topK }, (_, i) => (
              <tr key={i}>
                <td className="r num">{i + 1}</td>
                {modes.map((m) => {
                  const r = results[m.value]
                  if (!r) return <td key={m.value} className="muted">Unavailable</td>
                  const c = r.results[i]
                  if (!c) return <td key={m.value} />
                  const hit = matchesAll(c.anomalies)
                  return (
                    <td key={m.value} className={hit ? 'hit' : undefined}>
                      <span className="id">{c.case_id}</span>
                      {hit && <Check size={13} weight="bold" aria-label="matches every queried symptom" />}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {symptoms.length > 0 && (
        <p className="muted small fact-note">
          Checked cases are abnormal on every queried symptom.{' '}
          {Object.entries(counts)
            .filter(([, n]) => n != null)
            .map(([k, n]) => `${k} ${n} of ${topK}`)
            .join(', ')}
          .
        </p>
      )}
    </>
  )
}

function CasesBody({ meta }: { meta: Metadata }) {
  const [query, setQuery] = useState(lastForm?.query ?? '')
  const [filters, setFilters] = useState<FilterState>(lastForm?.filters ?? EMPTY_FILTERS)
  const [mode, setMode] = useState(lastForm?.mode ?? 'hybrid_rerank')
  const [topK, setTopK] = useState(lastForm?.topK ?? 10)
  const [compare, setCompare] = useState(lastForm?.compare ?? false)
  const [state, setState] = useState(last)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  lastForm = { query, filters, mode, topK, compare }

  const search = async () => {
    if (query.trim().length < 5) {
      setFormError('Enter search text of at least 5 characters; filters narrow the results.')
      return
    }
    setFormError(null)
    setBusy(true)
    const sub: Submitted = { query: query.trim(), mode, topK, compare }
    const modes = compare ? RETRIEVAL_MODES.map((m) => m.value) : [mode]
    const results: Record<string, SearchResponse | null> = {}
    let error: ApiError | null = null
    await Promise.all(
      modes.map(async (m) => {
        try {
          results[m] = await api.search({ query: sub.query, filters: toFilters(filters), top_k: topK, mode: m })
        } catch (e) {
          results[m] = null
          if (m === mode) error = e instanceof ApiError ? e : new ApiError('INTERNAL_ERROR', String(e))
        }
      }),
    )
    last = { sub, results, error }
    setState(last)
    setBusy(false)
  }

  const main = state?.results[state.sub.mode] ?? null
  const label = (v: string) => RETRIEVAL_MODES.find((m) => m.value === v)?.label ?? v
  const nf = filterCount(filters)
  return (
    <>
      <form
        className="search-bar"
        onSubmit={(e) => {
          e.preventDefault()
          search()
        }}
      >
        <div className="search-row">
          <label className="visually-hidden" htmlFor="cs-q">
            Search text
          </label>
          <input id="cs-q" className="input search-input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Describe what to find, for example: high latency and packet loss in winter" maxLength={1000} aria-invalid={!!formError} />
          <button type="submit" className="btn btn-primary btn-lg" disabled={busy}>
            <MagnifyingGlass size={16} weight="bold" aria-hidden /> {busy ? 'Searching' : 'Search'}
          </button>
        </div>
        {formError && (
          <p className="composer-error" role="alert">
            {formError}
          </p>
        )}
        <div className="search-options">
          <div className="field">
            <span className="field-label">Retrieval mode</span>
            <Seg label="Retrieval mode" options={RETRIEVAL_MODES} value={mode} onChange={setMode} />
          </div>
          <label className="field" style={{ width: 120 }}>
            <span className="field-label">Results</span>
            <select className="select" value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
              {[5, 10, 20].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="check" style={{ alignSelf: 'end', minHeight: 36 }}>
            <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} /> Compare all four modes
          </label>
        </div>
        <Disclosure summary="Filters" aside={nf ? `${nf} set` : 'None'}>
          <FilterPanel meta={meta} value={filters} onChange={setFilters} />
        </Disclosure>
      </form>

      {state?.error && <ApiErrorNotice error={state.error} />}
      {!state && !busy && <p className="empty">Search {fmtNum(meta.corpus_size)} historical records by description and filters. Runs without an AI model.</p>}
      {busy && <div className="skeleton" style={{ height: 200, marginTop: 'var(--s5)' }} />}
      {!busy && main && (
        <>
          <Section title="Results" meta={`${main.results.length} shown`}>
            <Facts
              items={[
                { label: 'Matching records', value: fmtNum(main.total_candidates), sub: 'after filters' },
                { label: 'Retrieval mode', value: label(state!.sub.mode), text: true, sub: `${fmtNum(main.timings_ms.total ?? Object.values(main.timings_ms).reduce((a, b) => a + b, 0))} ms` },
                {
                  label: 'Query expanded with',
                  value: main.expansion_terms.length ? main.expansion_terms.join(', ') : 'No extra terms',
                  text: true,
                  sub: 'terms added from recognised symptoms',
                },
              ]}
            />
            {main.warnings.map((w, i) => (
              <p key={i} className="muted small fact-note">
                {w}
              </p>
            ))}
            <div style={{ marginTop: 'var(--s5)' }}>
              {main.results.length ? (
                <CaseTable cases={main.results} meta={meta} showBreakdown />
              ) : (
                <p className="muted">
                  No records match these filters.
                  {firstFilter(main.applied_filters) && ` Remove the ${firstFilter(main.applied_filters)} filter and search again.`}
                </p>
              )}
            </div>
          </Section>
          {state!.sub.compare && (
            <Section title="Same query, four retrieval modes">
              <CompareGrid results={state!.results} symptoms={main.parsed.symptoms} topK={state!.sub.topK} meta={meta} />
            </Section>
          )}
        </>
      )}
    </>
  )
}

export default function Cases() {
  const meta = useMetadata()
  return (
    <div className="page">
      <PageHead title="Cases" lead={`Search ${meta.data ? fmtNum(meta.data.corpus_size) : 'the'} historical records with hybrid retrieval. Select a case to see its detail and why it ranked there.`} />
      <Guard>{(m) => <CasesBody meta={m} />}</Guard>
    </div>
  )
}
