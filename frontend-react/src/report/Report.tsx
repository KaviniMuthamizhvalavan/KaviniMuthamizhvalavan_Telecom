// The incident report, summary first: diagnosis, a four-cell summary, the worst KPIs, the top three actions.
// Everything else waits behind detail tabs, and each fact appears once.
import { useRef, useState } from 'react'
import type { Metadata, TroubleshootResponse } from '../api/types'
import { CaseTable, categoryNames } from '../components/CaseTable'
import { ChartBlock, PercentileStrip, PercentileTable, TraceTable, TraceWaterfall } from '../components/charts'
import { BandMark, Disclosure, ImpactMark, Notice, PriorityMark, Section, Tabs, VerdictMark } from '../components/ui'
import { COPY, STEP_LABEL } from '../lib/copy'
import { firstFilter, fmtNum, fmtPct, fmtSeconds, joinList } from '../lib/format'
import { Actions } from './Actions'
import { Causes, Likelihood } from './Causes'
import { DataSourcesPanel, KpiPanel, ValidationPanel } from './Evidence'
import { FeedbackForm } from './FeedbackForm'
import { cacheNote } from './Timeline'

const CLASSIFIED_BY: Record<string, string> = { llm: 'the AI model', rules: 'keyword rules', merged: 'the AI model and keyword rules' }

export function diagnosisSentence(resp: TroubleshootResponse, meta: Metadata): string {
  const names = categoryNames(meta)
  const labels = Object.fromEntries(meta.symptoms.map((s) => [s.code, s.label]))
  const cat = names[resp.classification.primary_category] ?? resp.classification.primary_category
  const syms = resp.classification.symptoms.map((s) => labels[s] ?? s.replace(/_/g, ' '))
  return syms.length ? `${cat} incident with ${joinList(syms)}` : `${cat} incident`
}

/** Reduced, partial and low-confidence stay visible; other notes fold away. */
function Notices({ resp, llmConfigured }: { resp: TroubleshootResponse; llmConfigured: boolean }) {
  let warnings = [...resp.warnings]
  const out = []
  if (resp.meta.model === 'none') {
    out.push(
      <Notice key="reduced" kind="warn">
        {llmConfigured ? COPY.reducedDown : COPY.reducedNoKey}
      </Notice>,
    )
    warnings = warnings.filter((w) => !w.startsWith('Reduced mode'))
  } else if (resp.status === 'degraded') {
    const steps = [...new Set(resp.trace.filter((t) => t.status === 'fallback').map((t) => (STEP_LABEL[t.node] ?? t.node).toLowerCase()))]
    out.push(
      <Notice key="partial" kind="warn">
        {COPY.partial(steps.join(', ') || 'see the notes below')}
      </Notice>,
    )
  }
  if (resp.validation?.verdict === 'fail') {
    out.push(<Notice key="low" kind="warn" title={COPY.lowConfidence} items={resp.validation.issues.map((i) => i.problem ?? '').filter(Boolean)} />)
    warnings = warnings.filter((w) => !w.startsWith('Low-confidence'))
  }
  if (!out.length && !warnings.length) return null
  return (
    <div className="notices">
      {out}
      {warnings.length > 0 && (
        <Disclosure summary="Notes on this analysis" aside={warnings.length}>
          <ul className="foot-list">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Disclosure>
      )}
    </div>
  )
}

/** KPI severity for the summary row: worst band and counts. */
function Severity({ resp }: { resp: TroubleshootResponse }) {
  const a = resp.kpi_assessment
  if (!a) return <>No KPI assessment.</>
  const crit = a.anomalies.filter((x) => x.band === 'critical').length
  const deg = a.anomalies.filter((x) => x.band === 'degraded').length
  return (
    <span className="sev-line">
      {crit ? <BandMark band="critical" /> : deg ? <BandMark band="degraded" /> : <BandMark band="normal" />}
      <span>
        {deg} KPI{deg === 1 ? '' : 's'} degraded, {crit} critical
      </span>
    </span>
  )
}

type TabId = 'causes' | 'kpis' | 'cases' | 'validation' | 'data' | 'trace'

export function Report({ resp, meta, llmConfigured }: { resp: TroubleshootResponse; meta: Metadata; llmConfigured: boolean }) {
  const [tab, setTab] = useState<TabId>('causes')
  const detailRef = useRef<HTMLElement>(null)
  const names = categoryNames(meta)
  const cls = resp.classification
  const pr = resp.priority
  const hyps = resp.root_cause_analysis?.hypotheses ?? []
  const hyp = hyps[0]
  const impact = resp.impact
  const esc = resp.escalation
  const also = cls.secondary_categories.map((c) => names[c] ?? c)
  const cases = resp.similar_cases
  const flt = firstFilter(resp.applied_filters)
  const cache = cacheNote(resp.meta)
  const a = resp.kpi_assessment
  const measured = a?.basis === 'provided_kpis'

  const open = (id: TabId) => {
    setTab(id)
    detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <article className="report" aria-label="Incident report">
      <header className="report-head">
        <p className="report-meta">
          <span className="id" title={resp.run_id}>
            {resp.run_id.replace('fixture-', '').slice(0, 8)}
          </span>
          <VerdictMark verdict={resp.validation?.verdict} />
          <button type="button" className="btn-link trace-link" onClick={() => open('trace')}>
            <span className="num">{fmtSeconds(resp.meta.latency_ms)} s</span>, {resp.meta.llm_calls} model call{resp.meta.llm_calls === 1 ? '' : 's'}, view trace
          </button>
          {cache && <span className="cache-note">{cache}</span>}
        </p>
        <h1 className="diagnosis">{diagnosisSentence(resp, meta)}</h1>
        <p className="diagnosis-sub">
          {also.length > 0 && <>Also involves {joinList(also)}. </>}
          Classified by {CLASSIFIED_BY[cls.source] ?? cls.source} with {fmtPct(cls.confidence)} confidence.
        </p>
      </header>

      <dl className="summary-row">
        <div className="summary-cell">
          <dt>Priority and severity</dt>
          <dd className="summary-big">{pr ? <PriorityMark level={pr.level} /> : 'n/a'}</dd>
          <dd className="summary-sub">
            <Severity resp={resp} />
          </dd>
        </div>
        <div className="summary-cell">
          <dt>Impact</dt>
          <dd className="summary-big">
            <ImpactMark level={impact?.level} />
          </dd>
          {impact && (
            <dd className="summary-sub">
              {fmtNum(impact.users_served)} users. {impact.affected_services.length ? `Affects ${joinList(impact.affected_services)}.` : 'No service-affecting KPI.'}
            </dd>
          )}
        </div>
        <div className="summary-cell">
          <dt>Likely cause</dt>
          <dd className="summary-text">{hyp ? hyp.cause : 'No hypothesis produced'}</dd>
          {hyp && (
            <dd className="summary-sub">
              <Likelihood level={hyp.likelihood} />
              {hyps.length > 1 && (
                <button type="button" className="btn-link" onClick={() => open('causes')}>
                  {hyps.length - 1} alternative{hyps.length > 2 ? 's' : ''}
                </button>
              )}
            </dd>
          )}
        </div>
        <div className={`summary-cell${esc?.needed ? ' escalate' : ''}`}>
          <dt>Escalation</dt>
          {esc?.needed ? (
            <>
              <dd className="summary-text">Escalate to {esc.team}</dd>
              {esc.reason && <dd className="summary-sub">{esc.reason}</dd>}
            </>
          ) : (
            <dd className="summary-text muted">No escalation needed</dd>
          )}
        </div>
      </dl>

      <Notices resp={resp} llmConfigured={llmConfigured} />

      {a && a.anomalies.length > 0 && (
        <Section
          id="key-kpis"
          title="Key KPIs"
          meta={
            <>
              <span className={`basis-tag ${measured ? 'measured' : 'estimated'}`}>{measured ? 'Measured' : 'Estimated from similar cases'}</span>
              {a.anomalies.length > 4 && (
                <button type="button" className="btn-link" onClick={() => open('kpis')}>
                  All {a.anomalies.length} abnormal KPIs
                </button>
              )}
            </>
          }
        >
          <ChartBlock chart={<PercentileStrip anomalies={a.anomalies} />} table={<PercentileTable anomalies={a.anomalies} />} caption={COPY.severityNote} />
        </Section>
      )}

      <Section id="actions" title="Next actions" meta={`${resp.recommendations.length} steps, most urgent first`}>
        <Actions recs={resp.recommendations} />
      </Section>

      <section className="section report-detail" ref={detailRef} aria-label="Report detail">
        <Tabs
          label="Report detail"
          active={tab}
          onChange={(id) => setTab(id as TabId)}
          tabs={[
            { id: 'causes', label: 'Causes', count: hyps.length, render: () => <Causes resp={resp} /> },
            { id: 'kpis', label: 'KPIs', render: () => <KpiPanel resp={resp} meta={meta} /> },
            {
              id: 'cases',
              label: 'Similar cases',
              count: cases.length,
              render: () =>
                cases.length ? (
                  <CaseTable cases={cases} meta={meta} />
                ) : (
                  <p className="muted">{flt ? `No historical cases match these filters. Remove the ${flt} filter and run again.` : 'No historical cases matched this description.'}</p>
                ),
            },
            { id: 'validation', label: 'Validation', render: () => <ValidationPanel val={resp.validation} resp={resp} /> },
            { id: 'data', label: 'Data and sources', render: () => <DataSourcesPanel resp={resp} onCase={() => open('cases')} /> },
            {
              id: 'trace',
              label: 'Agent trace',
              render: () => (
                <ChartBlock
                  title="Time spent per step"
                  chart={<TraceWaterfall trace={resp.trace} />}
                  table={<TraceTable trace={resp.trace} meta={resp.meta} />}
                  caption={`${fmtSeconds(resp.meta.latency_ms)} s in total, ${resp.meta.llm_calls} model calls.${cache ? ` ${cache}` : ''}`}
                />
              ),
            },
          ]}
        />
      </section>

      <Section id="feedback" title="Rate this analysis">
        <FeedbackForm resp={resp} meta={meta} />
      </Section>
    </article>
  )
}
