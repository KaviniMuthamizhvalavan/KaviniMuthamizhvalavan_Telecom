// Quality: how the assistant is checked. Live validation of recent analyses by the judge agent, the engineer
// feedback loop, and the saved offline evaluation. Reads saved results only (no AI model, no cost).
import { ArrowClockwise } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { EvaluationResponse, FeedbackSummary, LiveValidation, Metadata, OfflineEvaluation } from '../api/types'
import { ApiErrorNotice } from '../components/ApiErrorNotice'
import { categoryNames } from '../components/CaseTable'
import { ChartBlock, Dumbbell, ScoreBars, ScoreTable } from '../components/charts'
import { Guard } from '../components/Guard'
import { PageHead } from '../components/Shell'
import { Empty, Facts, Mark, Notice, Section, Seg, Tabs, VerdictMark } from '../components/ui'
import { SCORE_LABEL } from '../lib/copy'
import { fmtNum, fmtPct, fmtStamp, humanize, joinList, modelName, runLabel } from '../lib/format'
import { useHealth } from '../state/queries'

const PERIODS = [
  { label: '7 days', value: 7 },
  { label: '30 days', value: 30 },
  { label: '90 days', value: 90 },
]

const n0 = (v: number | null | undefined) => fmtNum(v ?? null)
const fmtMetric = (v: number | string) => (typeof v === 'number' ? (Math.abs(v) <= 1 && !Number.isInteger(v) ? v.toFixed(3) : fmtNum(v, Number.isInteger(v) ? 0 : 2)) : v)

// ---------------------------------------------------------------- live validation
const scoreLabels = (scores: Record<string, number>) => Object.fromEntries(Object.keys(scores).map((k) => [k, SCORE_LABEL[k] ?? humanize(k)]))

function Live({ live }: { live: LiveValidation | null }) {
  if (!live) return <Empty>Live validation is unavailable.</Empty>
  if (!live.total) return <Empty>No analyses in this period yet. Run one on Investigate.</Empty>
  const v = live.verdicts
  return (
    <div>
      <Facts
        items={[
          { label: 'Analyses', value: n0(live.total) },
          { label: 'Validated', value: n0(v.pass), sub: 'passed the judge agent' },
          { label: 'Low confidence', value: n0(v.fail), sub: 'failed validation' },
          { label: 'Not validated', value: n0(v.unvalidated), sub: 'no AI model' },
          { label: 'Pass rate', value: fmtPct(live.pass_rate), sub: 'of validated analyses' },
        ]}
      />
      <p className="muted small fact-note">
        Every Investigate analysis is checked by the judge agent: pass, one revision, or fail (shown as low confidence). Analyses run without an AI model are not validated. Includes runs made by the
        evaluation scripts, which share the database.
      </p>
      <Section title="Average judge scores" meta={live.avg_scores ? `over ${n0(live.scored_runs)} validated analyses` : undefined}>
        {live.avg_scores ? (
          <>
            <ChartBlock
              chart={<ScoreBars scores={live.avg_scores} labels={scoreLabels(live.avg_scores)} />}
              table={<ScoreTable scores={live.avg_scores} labels={scoreLabels(live.avg_scores)} />}
              caption="A pass needs groundedness 0.70 and the other scores 0.60. The tick on each bar is its pass mark."
            />
          </>
        ) : (
          <p className="muted">No validated analyses in this period.</p>
        )}
      </Section>
      <Section title="By model">
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col" className="r">Analyses</th>
                <th scope="col" className="r">Validated</th>
                <th scope="col" className="r">Low confidence</th>
                <th scope="col" className="r">Not validated</th>
                <th scope="col" className="r">Avg time</th>
                <th scope="col" className="r">Avg tokens</th>
              </tr>
            </thead>
            <tbody>
              {live.by_model.map((m) => (
                <tr key={m.model}>
                  <td>
                    <span className="id">{m.model}</span>
                  </td>
                  <td className="r">{n0(m.runs)}</td>
                  <td className="r">{n0(m.pass)}</td>
                  <td className="r">{n0(m.fail)}</td>
                  <td className="r">{n0(m.unvalidated)}</td>
                  <td className="r nowrap">{m.avg_latency_s ?? 'n/a'} s</td>
                  <td className="r">{n0(m.avg_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <Section title="Recent analyses">
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th scope="col">When (UTC)</th>
                <th scope="col">Query</th>
                <th scope="col">Model</th>
                <th scope="col">Validation</th>
                <th scope="col" className="r">Time</th>
              </tr>
            </thead>
            <tbody>
              {live.recent.map((r, i) => (
                <tr key={i}>
                  <td className="nowrap num">{fmtStamp(r.created_at)}</td>
                  <td>{r.query}</td>
                  <td>
                    <span className="id">{r.model}</span>
                  </td>
                  <td className="nowrap">
                    <VerdictMark verdict={r.verdict} />
                  </td>
                  <td className="r nowrap">{r.latency_s ?? 'n/a'} s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  )
}

// ---------------------------------------------------------------- feedback loop
function Bars({ rows, max, unit }: { rows: { label: string; value: number }[]; max: number; unit?: string }) {
  return (
    <ul className="bars">
      {rows.map((r) => (
        <li key={r.label}>
          <span className="bar-label">{r.label}</span>
          <span className="bar-track" aria-hidden>
            <span className="bar-fill" style={{ width: `${(r.value / max) * 100}%` }} />
          </span>
          <span className="bar-value num">
            {r.value % 1 ? r.value.toFixed(1) : r.value}
            {unit}
          </span>
        </li>
      ))}
    </ul>
  )
}

function FeedbackLoop({ s, meta }: { s: FeedbackSummary; meta: Metadata }) {
  const names = categoryNames(meta)
  const rated = s.by_category.filter((r) => r.avg_rating != null)
  return (
    <div>
      <Facts
        items={[
          { label: 'Analyses run', value: n0(s.total_runs) },
          { label: 'Feedback received', value: n0(s.total_feedback) },
          { label: 'Average rating', value: s.avg_rating == null ? 'n/a' : `${s.avg_rating.toFixed(1)} of 5` },
          { label: 'Found helpful', value: fmtPct(s.helpful_rate) },
          { label: 'Category corrections', value: n0(s.corrections_count) },
        ]}
      />
      {!s.total_feedback ? (
        <Empty>No feedback yet. Rate an analysis on Investigate to start the loop.</Empty>
      ) : (
        <div className="two-col">
          <Section title="Average rating by incident type">
            {rated.length ? <Bars rows={rated.map((r) => ({ label: names[r.category] ?? r.category, value: r.avg_rating as number }))} max={5} /> : <p className="muted">No ratings yet, only other feedback.</p>}
          </Section>
          <Section title="Most down-voted cases">
            {s.most_downvoted_cases.length ? (
              <>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th scope="col">Case</th>
                      <th scope="col">Incident type</th>
                      <th scope="col" className="r">Relevant</th>
                      <th scope="col" className="r">Not relevant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.most_downvoted_cases.map((r) => (
                      <tr key={r.case_id}>
                        <td>
                          <span className="id">{r.case_id}</span>
                        </td>
                        <td>{names[r.category] ?? r.category}</td>
                        <td className="r">{r.up}</td>
                        <td className="r">{r.down}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted small fact-note">These cases now rank lower for similar problems of the same incident type.</p>
              </>
            ) : (
              <p className="muted">No cases were marked not relevant.</p>
            )}
          </Section>
          {s.trend.length >= 2 && (
            <Section title="Feedback per day">
              <Bars rows={s.trend.map((t) => ({ label: t.date, value: t.n }))} max={Math.max(...s.trend.map((t) => t.n))} />
            </Section>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- offline evaluation report
function Report({ off, currentModel, currentRun }: { off: OfflineEvaluation | null; currentModel?: string; currentRun?: { label: string; show: () => void } }) {
  if (!off) return <Empty>No saved evaluation results yet. Run: python -m evaluation.run_all --suite all</Empty>
  const passed = off.totals?.PASS ?? 0
  const failed = off.totals?.FAIL ?? 0
  // contextual precision and recall have a known structural explanation (report section 6.1); name only those missed
  const missedContext = off.headline.filter((r) => r.status === 'FAIL' && /^contextual_(precision|recall)$/.test(r.metric)).map((r) => r.metric.replace('contextual_', 'contextual '))
  const models = off.models ?? {}
  const e2e = off.end_to_end
  const meta = off.judge_meta
  const byLabel: Record<string, Record<string, { mean: number; pass_rate: number }>> = {}
  for (const r of off.deepeval ?? []) (byLabel[r.label] ??= {})[r.system] = r
  return (
    <div>
      <Facts
        items={[
          { label: 'Evaluated on', value: (off.generated_utc ?? 'n/a').slice(0, 10), text: true },
          { label: 'Targets met', value: `${passed} of ${passed + failed}` },
          { label: "Agents' model", value: <span className="id">{models.runtime ?? 'n/a'}</span>, text: true },
          { label: 'Evaluation judge', value: <span className="id">{models.eval_judge ?? 'n/a'}</span>, text: true },
          { label: 'Historical cases', value: n0(off.dataset?.cases) },
        ]}
      />
      {currentModel && models.runtime && modelName(currentModel) !== modelName(models.runtime) && (
        <Notice>
          These results were measured with <span className="id">{models.runtime}</span> (agents) and <span className="id">{models.eval_judge}</span> (evaluation judge). The app now runs{' '}
          <span className="id">{currentModel}</span>
          {currentRun ? (
            <>
              , measured with the full suite in a separate run:{' '}
              <button type="button" className="btn-link" onClick={currentRun.show}>
                show {currentRun.label}
              </button>
              .
            </>
          ) : (
            ', which has not been measured with the full suite.'
          )}
        </Notice>
      )}
      <Section title="Headline metrics against targets">
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th scope="col">Component</th>
                <th scope="col">Metric</th>
                <th scope="col" className="r">Value</th>
                <th scope="col">Target</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {off.headline.map((r, i) => (
                <tr key={i}>
                  <td>{r.component}</td>
                  <td>{r.metric}</td>
                  <td className="r">{fmtMetric(r.value)}</td>
                  <td className="nowrap secondary">{r.target}</td>
                  <td className="nowrap">{r.status === 'PASS' ? <Mark sev="ok">Met</Mark> : r.status === 'FAIL' ? <Mark sev="critical">Not met</Mark> : <Mark sev="neutral">{humanize(r.status.toLowerCase())}</Mark>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {missedContext.length > 0 && (
          <p className="muted small fact-note">
            The missed {joinList(missedContext)} target{missedContext.length > 1 ? 's' : ''} measure{missedContext.length > 1 ? '' : 's'} how the evaluation's context list is ordered and a runbook section the agents never
            retrieve, not answer quality. See the evaluation report, section 6.1.
          </p>
        )}
      </Section>
      {Object.keys(byLabel).length > 0 && (
        <Section title="Answer quality: basic RAG against the multi-agent pipeline" meta="DeepEval">
          <ChartBlock
            chart={
              <Dumbbell
                aLabel="Basic RAG (one call)"
                cLabel="Multi-agent"
                rows={Object.entries(byLabel).map(([label, sys]) => ({ label, a: sys.A?.mean ?? null, c: sys.C?.mean ?? null }))}
              />
            }
            table={
            <table className="tbl">
              <thead>
                <tr>
                  <th scope="col">Metric</th>
                  <th scope="col" className="r">Basic RAG (one call)</th>
                  <th scope="col" className="r">Multi-agent</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(byLabel).map(([label, sys]) => (
                  <tr key={label}>
                    <td>{label}</td>
                    {(['A', 'C'] as const).map((k) => (
                      <td key={k} className="r nowrap">
                        {sys[k] ? (
                          <>
                            {sys[k].mean.toFixed(2)} <span className="muted small">({fmtPct(sys[k].pass_rate)} pass)</span>
                          </>
                        ) : (
                          'n/a'
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            }
          />
          {off.judge_usage && (
            <p className="muted small fact-note">
              Scored by <span className="id">{models.eval_judge ?? 'the evaluation judge'}</span>: {n0(off.judge_usage.llm_calls)} judge calls, {n0(off.judge_usage.cached_calls)} served from cache.
            </p>
          )}
        </Section>
      )}
      <div className="two-col">
        {e2e && (
          <Section title="End-to-end runs (multi-agent)">
            <Facts
              items={[
                { label: 'Median latency', value: `${e2e.C_latency_s?.median?.toFixed(1) ?? 'n/a'} s`, sub: `p95 ${e2e.C_latency_s?.p95?.toFixed(1) ?? 'n/a'} s` },
                { label: 'Tokens per run', value: n0(e2e.C_tokens?.mean != null ? Math.round(e2e.C_tokens.mean) : null) },
                { label: 'Repair calls', value: n0(e2e.C_repair_calls) },
                { label: 'Degraded runs', value: n0(e2e.C_runs_final_degraded) },
              ]}
            />
            <p className="muted small fact-note">
              {e2e.n ?? 0} test queries; judge verdicts:{' '}
              {Object.entries(e2e.C_verdicts ?? {})
                .map(([k, v]) => `${k} ${v}`)
                .join(', ')}
              .
            </p>
          </Section>
        )}
        {meta && (
          <Section title="Validator accuracy on planted errors">
            <Facts
              items={[
                { label: 'Errors caught', value: `${Math.round((meta.detection_rate ?? 0) * (meta.n_seeded ?? 0))} of ${meta.n_seeded ?? 0}` },
                { label: 'False alarms', value: `${meta.control_false_alarms ?? 0} of ${meta.controls ?? 0}`, sub: 'clean controls' },
              ]}
            />
            <p className="muted small fact-note">Known errors (invented case IDs, wrong KPI numbers, uncited actions and more) were planted in real diagnoses to check that the judge agent catches them.</p>
          </Section>
        )}
      </div>
      {off.report_files && off.report_files.length > 0 && (
        <p className="muted small fact-note">
          Full report:{' '}
          {off.report_files.map((f) => (
            <span key={f} className="id" style={{ marginRight: 'var(--s3)' }}>
              {f}
            </span>
          ))}
        </p>
      )}
    </div>
  )
}

/** The saved configurations, the final results first; each named by its models. */
export function evaluationRuns(data: Pick<EvaluationResponse, 'offline' | 'offline_alternatives'>): { id: string; label: string; off: OfflineEvaluation }[] {
  const all = [...(data.offline ? [{ ...data.offline, id: 'final' }] : []), ...(data.offline_alternatives ?? [])]
  return all.map((off) => ({ id: off.id ?? 'final', label: runLabel(off.models), off }))
}

function Reports({ data, currentModel, selected, onSelect }: { data: EvaluationResponse; currentModel?: string; selected: string; onSelect: (id: string) => void }) {
  const runs = evaluationRuns(data)
  if (runs.length < 2) return <Report off={data.offline} currentModel={currentModel} />
  const run = runs.find((r) => r.id === selected) ?? runs[0]
  const judges = [...new Set(runs.map((r) => modelName(r.off.models?.eval_judge)))]
  // the run that measured the model the app runs now, if any
  const measured = currentModel ? runs.find((r) => modelName(r.off.models?.runtime) === modelName(currentModel)) : undefined
  return (
    <div>
      <div className="run-switch">
        <span className="field-label">Configuration</span>
        <Seg label="Evaluated configuration" options={runs.map((r) => ({ label: r.label, value: r.id }))} value={run.id} onChange={onSelect} />
      </div>
      {judges.length > 1 && (
        <Notice>
          The configurations were scored by different evaluation judges ({judges.join(' and ')}), so judge-based scores are on different scales: compare them within one configuration, not across. Retrieval, ML, guardrail and
          prioritization results do not use a model and match across configurations.
        </Notice>
      )}
      <Report off={run.off} currentModel={currentModel} currentRun={measured && measured.id !== run.id ? { label: measured.label, show: () => onSelect(measured.id) } : undefined} />
    </div>
  )
}

function QualityBody({ meta }: { meta: Metadata }) {
  const [days, setDays] = useState(30)
  const [run, setRun] = useState('final')
  const health = useHealth()
  const ev = useQuery({ queryKey: ['evaluation', days], queryFn: () => api.evaluation(days) })
  const fb = useQuery({ queryKey: ['feedback-summary', days], queryFn: () => api.feedbackSummary(days) })
  const llm = health.data?.components.llm
  const refresh = () => {
    ev.refetch()
    fb.refetch()
  }
  return (
    <>
      <div className="quality-controls">
        <Seg label="Period" options={PERIODS} value={days} onChange={setDays} />
        <button type="button" className="btn" onClick={refresh} disabled={ev.isFetching || fb.isFetching}>
          <ArrowClockwise size={14} aria-hidden /> Refresh
        </button>
      </div>
      <Tabs
        label="Quality"
        tabs={[
          {
            id: 'live',
            label: 'Live validation',
            render: () => (ev.isError ? <ApiErrorNotice error={ev.error} retry={refresh} /> : ev.data ? <Live live={ev.data.live} /> : <div className="skeleton" style={{ height: 160 }} />),
          },
          {
            id: 'feedback',
            label: 'Feedback',
            render: () => (fb.isError ? <ApiErrorNotice error={fb.error} retry={refresh} /> : fb.data ? <FeedbackLoop s={fb.data} meta={meta} /> : <div className="skeleton" style={{ height: 160 }} />),
          },
          {
            id: 'report',
            label: 'Evaluation report',
            render: () =>
              ev.isError ? <ApiErrorNotice error={ev.error} retry={refresh} /> : ev.data ? <Reports data={ev.data} currentModel={llm?.configured ? llm.model : undefined} selected={run} onSelect={setRun} /> : <div className="skeleton" style={{ height: 160 }} />,
          },
        ]}
      />
      {ev.data?.warnings.map((w, i) => (
        <p key={i} className="muted small fact-note">
          {w}
        </p>
      ))}
    </>
  )
}

export default function Quality() {
  return (
    <div className="page">
      <PageHead title="Quality" lead="How the assistant is checked: the judge agent's verdicts on recent analyses, engineer feedback, and the saved offline evaluation." />
      <Guard>{(meta) => <QualityBody meta={meta} />}</Guard>
    </div>
  )
}
