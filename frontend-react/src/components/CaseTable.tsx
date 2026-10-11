// Similar or searched cases as one scannable line each: identity, type, priority, risk, match and the two worst
// KPIs (with "+N"). Selecting a row expands it in place to everything: all abnormal KPIs on the shared ruler,
// location and conditions, other incident types, the record text and, on Cases, why it ranked there.
import { CaretDown, CaretRight } from '@phosphor-icons/react'
import { Fragment, useState } from 'react'
import type { Anomaly, CaseResult, KpiInfo, Metadata } from '../api/types'
import { fmtPct, fmtValue, location } from '../lib/format'
import { useCase } from '../state/queries'
import { ApiErrorNotice } from './ApiErrorNotice'
import { worstKpis } from './charts'
import { KpiRulers } from './Ruler'
import { PriorityMark, RiskMark } from './ui'

export const categoryNames = (meta?: Metadata) => Object.fromEntries((meta?.categories ?? []).map((c) => [c.code, c.name]))

const KEY_KPIS_PER_ROW = 2

function CaseDetailPanel({ caseId, row, showBreakdown, names, kpis }: { caseId: string; row: CaseResult; showBreakdown: boolean; names: Record<string, string>; kpis?: KpiInfo[] }) {
  const q = useCase(caseId)
  if (q.isPending) return <div className="skeleton" style={{ height: 120 }} />
  if (q.isError) return <ApiErrorNotice error={q.error} retry={() => q.refetch()} />
  const c = q.data
  const flagged = c.assessment.per_kpi.filter((p) => p.band !== 'normal')
  const b = row.score_breakdown
  return (
    <div className="case-detail">
      <dl className="kv case-kv">
        <dt>Location</dt>
        <dd>
          {location(row.state, row.city)}, {row.season}, {row.weather}
        </dd>
        <dt>Incident types</dt>
        <dd>{[c.primary_category, ...c.secondary_categories].map((x) => names[x] ?? x).join(', ')}</dd>
        <dt>Case priority</dt>
        <dd>
          <PriorityMark level={c.priority.level} /> <span className="muted">score {c.priority.score.toFixed(2)}</span>
        </dd>
        <dt>Fault risk</dt>
        <dd>
          <RiskMark band={c.fault_risk_band} /> <span className="muted">{fmtPct(c.fault_risk_prob)}</span>
        </dd>
      </dl>
      {flagged.length > 0 && (
        <>
          <h4 className="subhead">Abnormal KPIs in this case</h4>
          <KpiRulers rows={flagged} kpis={kpis} />
        </>
      )}
      <p className="case-narrative">{c.narrative}</p>
      {showBreakdown && (
        <>
          <h4 className="subhead">Why it ranked here</h4>
          <dl className="kv">
            <dt>Semantic rank</dt>
            <dd>{b.dense_rank ?? 'not in top 50'}</dd>
            <dt>Keyword rank</dt>
            <dd>{b.bm25_rank ?? 'not in top 50'}</dd>
            <dt>Fused score</dt>
            <dd>{b.rrf.toFixed(4)}</dd>
            <dt>Symptom overlap</dt>
            <dd>{fmtPct(b.symptom_overlap)}</dd>
            <dt>Feedback adjustment</dt>
            <dd>
              {b.feedback_prior.toFixed(2)} <span className="muted">(0.50 means none)</span>
            </dd>
            <dt>Final score</dt>
            <dd>{row.final_score.toFixed(3)}</dd>
          </dl>
        </>
      )}
    </div>
  )
}

function KeyKpis({ anomalies }: { anomalies: Anomaly[] }) {
  if (!anomalies.length) return <span className="muted">None abnormal</span>
  const top = worstKpis(anomalies, KEY_KPIS_PER_ROW)
  const more = anomalies.length - top.length
  return (
    <span className="case-kpis">
      {top.map((a, i) => (
        <span key={a.kpi} className={`case-kpi band-${a.band}`}>
          <span className="case-kpi-sq" aria-hidden />
          {a.label} <span className="num">{fmtValue(a.value)}</span> <span className="muted">{a.unit}</span>
          <span className="visually-hidden"> ({a.band})</span>
          {i < top.length - 1 ? ', ' : ''}
        </span>
      ))}
      {more > 0 && <span className="muted"> +{more}</span>}
    </span>
  )
}

export function CaseTable({ cases, meta, showBreakdown = false }: { cases: CaseResult[]; meta?: Metadata; showBreakdown?: boolean }) {
  const [open, setOpen] = useState<string | null>(null)
  const names = categoryNames(meta)
  return (
    <div className="tbl-wrap">
      <table className="tbl case-tbl">
        <thead>
          <tr>
            <th scope="col" style={{ width: 28 }}>
              <span className="visually-hidden">Expand</span>
            </th>
            <th scope="col">Case</th>
            <th scope="col">Incident type</th>
            <th scope="col">Priority</th>
            <th scope="col">Fault risk</th>
            <th scope="col">Worst KPIs</th>
            <th scope="col" className="r">
              Match
            </th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => {
            const isOpen = open === c.case_id
            const toggle = () => setOpen(isOpen ? null : c.case_id)
            return (
              <Fragment key={c.case_id}>
                <tr className={`case-row${isOpen ? ' open' : ''}`} onClick={toggle}>
                  <td>
                    <button type="button" className="row-toggle" aria-expanded={isOpen} aria-label={`${isOpen ? 'Collapse' : 'Expand'} ${c.case_id}`} onClick={(e) => (e.stopPropagation(), toggle())}>
                      {isOpen ? <CaretDown size={14} weight="bold" /> : <CaretRight size={14} weight="bold" />}
                    </button>
                  </td>
                  <td className="nowrap">
                    <span className="id">{c.case_id}</span>
                  </td>
                  <td>{names[c.primary_category] ?? c.primary_category}</td>
                  <td className="nowrap">
                    <PriorityMark level={c.priority} />
                  </td>
                  <td className="nowrap">
                    <RiskMark band={c.fault_risk_band} />
                  </td>
                  <td>
                    <KeyKpis anomalies={c.anomalies} />
                  </td>
                  <td className="r" title="Symptom overlap (Jaccard): symptoms shared by the query and this case, divided by the symptoms in either">
                    {fmtPct(c.score_breakdown.symptom_overlap)}
                  </td>
                </tr>
                {isOpen && (
                  <tr className="case-expanded">
                    <td />
                    <td colSpan={6}>
                      <CaseDetailPanel caseId={c.case_id} row={c} showBreakdown={showBreakdown} names={names} kpis={meta?.kpis} />
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
