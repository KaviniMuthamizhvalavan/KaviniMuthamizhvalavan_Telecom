// What-if: adjust a KPI snapshot and read predicted fault risk, expected throughput and priority. No AI model.
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { FaultRiskResponse, Metadata, PerformanceResponse, PrioritizeResponse } from '../api/types'
import { ApiErrorNotice } from '../components/ApiErrorNotice'
import { Guard } from '../components/Guard'
import { KpiForm, medianValues, toSnapshot, type KpiValues } from '../components/forms'
import { KpiRulers } from '../components/Ruler'
import { PageHead } from '../components/Shell'
import { BandMark, PriorityMark, RiskMark, Section, Seg } from '../components/ui'
import { COPY } from '../lib/copy'
import { fmtMbps, fmtPct, fmtSignedPct, humanize } from '../lib/format'

interface Results {
  risk?: FaultRiskResponse
  perf?: PerformanceResponse
  priority?: PrioritizeResponse
  errors: ApiError[]
}

let lastValues: KpiValues | null = null
let lastResults: Results | null = null

function SimulateBody({ meta }: { meta: Metadata }) {
  const [source, setSource] = useState<'medians' | 'case'>('medians')
  const [values, setValues] = useState<KpiValues>(lastValues ?? medianValues(meta, ['throughput_mbps']))
  const [caseId, setCaseId] = useState('')
  const [loadMsg, setLoadMsg] = useState<string | null>(null)
  const [results, setResults] = useState<Results | null>(lastResults)
  const [busy, setBusy] = useState(false)
  lastValues = values

  const loadCase = async () => {
    const id = caseId.trim().toUpperCase()
    if (!/^CASE-\d{6}$/.test(id)) {
      setLoadMsg('Enter a case ID like CASE-004217.')
      return
    }
    try {
      const c = await api.getCase(id)
      const v: KpiValues = {}
      for (const k of meta.kpis) {
        const x = c.normalized[k.name]
        if (typeof x === 'number') v[k.name] = String(Math.round(x * 100) / 100)
      }
      if (typeof c.normalized.season === 'string') v.season = c.normalized.season
      if (typeof c.normalized.weather === 'string') v.weather = c.normalized.weather
      setValues(v)
      setLoadMsg(`Loaded ${id}.`)
    } catch (e) {
      setLoadMsg(e instanceof ApiError && e.code === 'NOT_FOUND' ? 'No case with that ID.' : 'Could not load the case.')
    }
  }

  const predict = async () => {
    const snap = toSnapshot(meta, values)
    if (!snap) return
    setBusy(true)
    const [risk, perf, priority] = await Promise.allSettled([api.faultRisk(snap), api.performance(snap), api.prioritize(snap)])
    const errors = [risk, perf, priority].filter((r) => r.status === 'rejected').map((r) => (r as PromiseRejectedResult).reason as ApiError)
    const out: Results = {
      risk: risk.status === 'fulfilled' ? risk.value : undefined,
      perf: perf.status === 'fulfilled' ? perf.value : undefined,
      priority: priority.status === 'fulfilled' ? priority.value : undefined,
      errors,
    }
    lastResults = out
    setResults(out)
    setBusy(false)
  }

  const invalid = toSnapshot(meta, values) === null
  const pr = results?.priority?.priority
  return (
    <div className="simulate">
      <div className="sim-inputs">
        <div className="sim-source">
          <span className="field-label">Start from</span>
          <Seg
            label="Start from"
            value={source}
            onChange={(v) => {
              setSource(v)
              if (v === 'medians') {
                setValues(medianValues(meta, ['throughput_mbps']))
                setLoadMsg(null)
              }
            }}
            options={[
              { label: 'Typical values', value: 'medians' },
              { label: 'A historical case', value: 'case' },
            ]}
          />
          {source === 'case' && (
            <form
              className="sim-case"
              onSubmit={(e) => {
                e.preventDefault()
                loadCase()
              }}
            >
              <input className="input" value={caseId} onChange={(e) => setCaseId(e.target.value)} placeholder="CASE-004217" aria-label="Case ID" />
              <button type="submit" className="btn">
                Load case
              </button>
            </form>
          )}
          {loadMsg && (
            <p className="muted small" role="status">
              {loadMsg}
            </p>
          )}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            predict()
          }}
        >
          <KpiForm meta={meta} values={values} onChange={setValues} optional={['throughput_mbps']} />
          <div className="composer-run">
            <button type="submit" className="btn btn-primary btn-lg" disabled={busy || invalid}>
              {busy ? 'Predicting' : 'Predict'}
            </button>
            <span className="composer-note">Empty fields are filled with dataset medians. Enter an observed throughput to see the deficit.</span>
          </div>
        </form>
      </div>

      {results?.errors.map((e, i) => <ApiErrorNotice key={i} error={e} />)}
      {!results && <p className="empty">Adjust the values and press Predict. Results compare against this network's history.</p>}
      {results && (
        <>
          <dl className="summary-row sim-readout">
            <div className="summary-cell">
              <dt>Fault risk</dt>
              <dd className="summary-big">{results.risk ? <>{fmtPct(results.risk.probability)} <RiskMark band={results.risk.band} /></> : 'n/a'}</dd>
              {results.risk && <dd className="summary-sub">Chance of a top-quartile fault rate. Model ROC-AUC {results.risk.model.roc_auc.toFixed(2)}.</dd>}
            </div>
            <div className="summary-cell">
              <dt>Expected throughput</dt>
              <dd className="summary-big num">{results.perf ? fmtMbps(results.perf.expected_throughput_mbps) : 'n/a'}</dd>
              {results.perf && (
                <dd className="summary-sub">
                  {results.perf.observed_throughput_mbps != null
                    ? `Observed ${fmtMbps(results.perf.observed_throughput_mbps)}, ${fmtSignedPct(results.perf.deficit_pct)} (${humanize(results.perf.assessment ?? '').toLowerCase()}).`
                    : 'Enter an observed throughput to see the deficit.'}{' '}
                  Model R2 {results.perf.model.r2.toFixed(2)}, a rough expectation.
                </dd>
              )}
            </div>
            <div className="summary-cell">
              <dt>Priority</dt>
              <dd className="summary-big">{pr ? <PriorityMark level={pr.level} /> : 'n/a'}</dd>
              {pr && (
                <dd className="summary-sub num">
                  Score {pr.score.toFixed(2)}: {Object.entries(pr.components).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(', ')}.
                </dd>
              )}
            </div>
          </dl>

          <div className="sim-grid">
            <Section title="KPI assessment" meta="Measured: the values above">
              {results.priority && results.priority.anomalies.length ? (
                <KpiRulers rows={results.priority.anomalies} caption={COPY.severityNote} kpis={meta.kpis} />
              ) : (
                <p className="muted">No KPI is outside its normal band.</p>
              )}
              {results.priority && results.priority.imputed_fields.length > 0 && <p className="muted small fact-note">Filled with dataset medians: {results.priority.imputed_fields.join(', ')}.</p>}
            </Section>
            <Section title="Why this priority and risk">
              {pr && (
                <ul className="foot-list">
                  {pr.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                  {pr.overrides.map((r, i) => (
                    <li key={`o${i}`}>Override: {r}</li>
                  ))}
                </ul>
              )}
              {results.risk && results.risk.top_drivers.length > 0 && (
                <>
                  <h3 className="subhead">Top fault-risk drivers</h3>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th scope="col">Driver</th>
                        <th scope="col">Value</th>
                        <th scope="col">Band</th>
                        <th scope="col" className="r">
                          Importance
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.risk.top_drivers.map((d) => (
                        <tr key={d.feature}>
                          <td>{humanize(d.feature)}</td>
                          <td className="num">
                            {String(d.value)}
                            {d.imputed && <span className="muted small"> (median)</span>}
                          </td>
                          <td>{d.band ? <BandMark band={d.band} /> : <span className="muted">n/a</span>}</td>
                          <td className="r">{d.importance.toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="muted small fact-note">{results.risk.definition}</p>
                </>
              )}
            </Section>
          </div>
        </>
      )}
    </div>
  )
}

export default function Simulate() {
  return (
    <div className="page">
      <PageHead title="Simulate" lead="Adjust KPI values to see the predicted fault risk, expected throughput and priority. Runs without an AI model." />
      <Guard>{(meta) => <SimulateBody meta={meta} />}</Guard>
    </div>
  )
}
