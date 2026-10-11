// Detail panels behind the report tabs: KPIs, validation, data and sources. Each fact appears once.
import type { Metadata, TroubleshootResponse, Validation } from '../api/types'
import { ChartBlock, ScoreBars, ScoreTable, ThroughputChart } from '../components/charts'
import { KpiRulers } from '../components/Ruler'
import { Disclosure, Facts, Mark, PriorityMark, RiskMark, VerdictMark } from '../components/ui'
import { COPY, SCORE_LABEL } from '../lib/copy'
import { factorLabel, fmtMbps, fmtNum, fmtPct, fmtSignedPct, humanize, joinList } from '../lib/format'

// ---------------------------------------------------------------- KPIs: full ruler table, throughput, fault risk
export function KpiPanel({ resp, meta }: { resp: TroubleshootResponse; meta: Metadata }) {
  const a = resp.kpi_assessment
  const perf = resp.performance_prediction
  const risk = resp.fault_risk
  const tput = meta.kpis.find((k) => k.name === 'throughput_mbps')
  return (
    <div className="assessment">
      {a && a.anomalies.length > 0 ? (
        <KpiRulers rows={a.anomalies} caption={COPY.severityNote} kpis={meta.kpis} />
      ) : (
        <p className="muted">{a ? 'No KPI is outside its normal band.' : 'No KPI assessment is available.'}</p>
      )}
      {a && a.imputed_fields.length > 0 && <p className="muted small fact-note">Filled with dataset medians: {a.imputed_fields.join(', ')}.</p>}

      <div className="kpi-pair">
        {perf && (
          <ChartBlock
            title="Throughput against the model's expectation"
            chart={<ThroughputChart expected={perf.expected_throughput_mbps} observed={perf.observed} deficitPct={perf.deficit_pct} typical={tput} />}
            table={
              <table className="tbl">
                <tbody>
                  <tr>
                    <th scope="row">Expected</th>
                    <td className="r">{fmtMbps(perf.expected_throughput_mbps)}</td>
                  </tr>
                  <tr>
                    <th scope="row">Observed</th>
                    <td className="r">{perf.observed != null ? fmtMbps(perf.observed) : 'n/a'}</td>
                  </tr>
                  <tr>
                    <th scope="row">Difference</th>
                    <td className="r">{fmtSignedPct(perf.deficit_pct)}</td>
                  </tr>
                  {tput && (
                    <tr>
                      <th scope="row">Typical range (p25 to p75)</th>
                      <td className="r">
                        {fmtNum(tput.p25)} to {fmtNum(tput.p75)} Mbps
                      </td>
                    </tr>
                  )}
                  <tr>
                    <th scope="row">Model R2</th>
                    <td className="r">{perf.model_r2.toFixed(2)}</td>
                  </tr>
                </tbody>
              </table>
            }
            caption={`The throughput model explains ${fmtPct(perf.model_r2)} of variance (R2 ${perf.model_r2.toFixed(2)}): a rough expectation.`}
          />
        )}
        {risk && (
          <Facts
            items={[
              {
                label: 'Fault risk',
                value: (
                  <>
                    {fmtPct(risk.probability)} <RiskMark band={risk.band} />
                  </>
                ),
                sub: 'Chance of a top-quartile fault rate (48% or more)',
              },
              { label: 'Data served', value: resp.impact?.data_gb != null ? `${resp.impact.data_gb} GB` : 'n/a', sub: 'by the affected cell' },
            ]}
          />
        )}
      </div>
      {resp.impact?.narrative && (
        <Disclosure summary="Impact detail">
          <p className="impact-narrative">{resp.impact.narrative}</p>
        </Disclosure>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- validation
// Priority reasons that restate a KPI anomaly are already on the KPI rulers.
const ANOMALY_REASON = /^(Degraded|Critical) .*worse than/

export function ValidationPanel({ val, resp }: { val: Validation | null; resp: TroubleshootResponse }) {
  if (!val) return <p className="muted">No validation was run.</p>
  const pr = resp.priority
  const reasons = (pr?.reasons ?? []).filter((r) => !ANOMALY_REASON.test(r))
  const failed = val.rule_checks.filter((c) => !c.passed).length
  return (
    <div className="validation">
      <p className="val-verdict">
        <VerdictMark verdict={val.verdict} />
        <span className="muted">
          {val.verdict === 'unvalidated' ? 'Rule checks only, no AI judge' : `after ${val.revisions} revision${val.revisions === 1 ? '' : 's'}`}
        </span>
      </p>
      {val.summary && <p className="val-summary">{val.summary}</p>}
      {Object.keys(val.scores).length > 0 && (
        <ChartBlock title="Judge scores against pass marks" chart={<ScoreBars scores={val.scores} labels={SCORE_LABEL} />} table={<ScoreTable scores={val.scores} labels={SCORE_LABEL} />} />
      )}
      {val.issues.length > 0 && (
        <Disclosure summary="Issues raised by the judge agent" aside={val.issues.length}>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th scope="col">Agent</th>
                  <th scope="col">Issue</th>
                </tr>
              </thead>
              <tbody>
                {val.issues.map((i, n) => (
                  <tr key={n}>
                    <td className="nowrap">{humanize(i.target ?? '')}</td>
                    <td className="secondary">{i.problem}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Disclosure>
      )}
      <Disclosure summary="Deterministic rule checks" aside={failed ? `${failed} of ${val.rule_checks.length} failed` : `all ${val.rule_checks.length} passed`}>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th scope="col">Result</th>
                <th scope="col">Rule</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {val.rule_checks.map((c) => (
                <tr key={c.rule}>
                  <td className="nowrap">{c.passed ? <Mark sev="ok">Passed</Mark> : <Mark sev={c.critical ? 'critical' : 'medium'}>Failed</Mark>}</td>
                  <td>
                    {humanize(c.rule)}
                    {c.critical && <span className="muted small"> (critical)</span>}
                  </td>
                  <td className="secondary">{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Disclosure>
      {pr && (
        <Disclosure summary="Priority reasoning" aside={`score ${pr.score.toFixed(2)}`}>
          <p className="val-verdict">
            <PriorityMark level={pr.level} />
            <span className="muted num">{Object.entries(pr.components).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(', ')}</span>
          </p>
          {(reasons.length > 0 || pr.overrides.length > 0) && (
            <ul className="foot-list" style={{ marginTop: 'var(--s2)' }}>
              {reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
              {pr.overrides.map((r, i) => (
                <li key={`o${i}`}>Override: {r}</li>
              ))}
            </ul>
          )}
          <p className="muted small fact-note">KPI-based reasons are shown on the KPI rulers.</p>
        </Disclosure>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- data and sources: segment statistics and runbooks
export function DataSourcesPanel({ resp, onCase }: { resp: TroubleshootResponse; onCase: () => void }) {
  const s = resp.segment_stats
  const runbooks = resp.sources.filter((x) => x.type === 'runbook')
  const nCases = resp.sources.filter((x) => x.type === 'case').length
  const mix = s ? Object.entries(s.priority_mix) : []
  return (
    <div>
      <h3 className="subhead" style={{ marginTop: 0 }}>
        Historical segment
      </h3>
      {!s || !s.count ? (
        <p className="muted">No historical segment matches these filters and symptoms.</p>
      ) : (
        <>
          <p>
            <b className="num">{fmtNum(s.count)}</b> historical records share these symptoms. Median fault occurrence rate <span className="num">{s.median_fault_rate ?? 'n/a'}%</span>.
          </p>
          <Disclosure summary="Factors that co-occur with this segment" aside={s.top_lifts.length}>
            <div className="tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th scope="col">Factor</th>
                    <th scope="col" className="r">In segment</th>
                    <th scope="col" className="r">In all records</th>
                    <th scope="col" className="r">Lift</th>
                  </tr>
                </thead>
                <tbody>
                  {s.top_lifts.map((x) => (
                    <tr key={x.factor}>
                      <td>{factorLabel(x.factor)}</td>
                      <td className="r">{fmtPct(x.segment_rate)}</td>
                      <td className="r">{fmtPct(x.corpus_rate)}</td>
                      <td className="r">{x.lift ? `${x.lift.toFixed(2)}x` : 'n/a'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted small fact-note">
              Lift is how much more often a factor co-occurs in this segment than overall. Co-occurrence is not causation.
              {mix.length > 0 && ` Priority mix: ${joinList(mix.map(([k, v]) => `${k} ${fmtPct(v)}`))}.`}
            </p>
          </Disclosure>
        </>
      )}
      <h3 className="subhead">
        Runbook sections cited <span className="muted num">{runbooks.length}</span>
      </h3>
      {runbooks.length ? (
        runbooks.map((r) => (
          <Disclosure key={r.id} summary={<span className="id">{r.id}</span>} aside={r.title}>
            <p className="source-snippet">{r.snippet}</p>
          </Disclosure>
        ))
      ) : (
        <p className="muted">No runbook sections.</p>
      )}
      {nCases > 0 && (
        <p className="muted small fact-note">
          {nCases} historical cases were also used as sources:{' '}
          <button type="button" className="btn-link" onClick={onCase}>
            see Similar cases
          </button>
          .
        </p>
      )}
    </div>
  )
}
