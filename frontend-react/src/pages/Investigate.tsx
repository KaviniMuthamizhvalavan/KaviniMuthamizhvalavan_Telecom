import { useState } from 'react'
import { FIXTURE_MODE, FIXTURE_REDUCED } from '../api/troubleshoot'
import type { Metadata, TroubleshootResponse } from '../api/types'
import { ApiErrorNotice } from '../components/ApiErrorNotice'
import { Guard } from '../components/Guard'
import { PageHead } from '../components/Shell'
import { Notice } from '../components/ui'
import { buildRequest, Composer } from '../report/Composer'
import { Report } from '../report/Report'
import { LiveTimeline } from '../report/Timeline'
import { useInvestigation } from '../state/investigation'
import { usePrefs } from '../state/prefs'
import { useMode } from '../state/queries'

function Clarify({ resp, onAnswer }: { resp: TroubleshootResponse; onAnswer: (a: string) => void }) {
  const [answer, setAnswer] = useState('')
  const q = resp.classification.clarification_question || 'Which symptoms or KPIs are affected?'
  return (
    <section className="clarify" aria-labelledby="clarify-h">
      <h2 id="clarify-h">One more detail needed</h2>
      <p className="secondary">{q}</p>
      <form
        className="clarify-form"
        onSubmit={(e) => {
          e.preventDefault()
          if (answer.trim()) onAnswer(answer.trim())
        }}
      >
        <input className="input" value={answer} onChange={(e) => setAnswer(e.target.value)} aria-label="Your answer" placeholder="Your answer" maxLength={500} />
        <button type="submit" className="btn btn-primary" disabled={!answer.trim()}>
          Continue
        </button>
      </form>
    </section>
  )
}

function Pending({ query, startedAt, reduced }: { query: string; startedAt: number | null; reduced: boolean }) {
  return (
    <div className="pending" aria-busy="true">
      <div className="pending-main">
        <p className="report-meta">Assembling the report</p>
        <p className="pending-query">{query}</p>
        <div className="skeleton" style={{ height: 34, width: '78%', marginTop: 'var(--s4)' }} />
        <div className="pending-cells">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 72 }} />
          ))}
        </div>
        <p className="muted small" role="status">
          {reduced ? 'Reduced mode answers in a few seconds.' : 'Full AI mode takes about 30 seconds to 2 minutes, longer when the judge asks for a revision. Keep this tab open.'}
        </p>
      </div>
      <aside className="report-aside">
        <LiveTimeline startedAt={startedAt} reduced={reduced} />
      </aside>
    </div>
  )
}

function InvestigateBody({ meta }: { meta: Metadata }) {
  const inv = useInvestigation()
  const { mode, health } = useMode()
  const [formError, setFormError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const llmConfigured = !!health.data?.components.llm.configured

  const newAnalysis = () => {
    inv.reset()
    inv.setComposer({ ...inv.composer, query: '' })
    setEditing(false)
    window.scrollTo({ top: 0 })
  }

  const run = (query?: string) => {
    const body = buildRequest(meta, inv.composer, query)
    if (typeof body === 'string') {
      setFormError(body)
      return
    }
    setFormError(null)
    setEditing(false)
    inv.run(body)
  }

  return (
    <>
      {FIXTURE_MODE && <Notice kind="warn">Development fixture: analyses replay a recorded Claude Haiku run from 2026-10-09 and make no API call.</Notice>}
      <Composer
        meta={meta}
        state={inv.composer}
        onChange={inv.setComposer}
        onRun={run}
        onCancel={inv.cancel}
        running={inv.running}
        mode={mode}
        error={formError}
        collapsed={!editing && (inv.running || !!inv.result)}
        onExpand={() => setEditing(true)}
        onNew={newAnalysis}
      />
      <div className="investigation">
        {inv.running && inv.request && <Pending query={inv.request.query} startedAt={inv.startedAt} reduced={FIXTURE_MODE ? FIXTURE_REDUCED : mode === 'reduced'} />}
        {!inv.running && inv.error && <ApiErrorNotice error={inv.error} retry={inv.request ? () => inv.run(inv.request!) : undefined} />}
        {!inv.running && inv.result?.status === 'needs_clarification' && (
          <Clarify
            resp={inv.result}
            onAnswer={(a) => {
              const q = `${inv.request?.query ?? ''} ${a}`.slice(0, 1000)
              inv.setComposer({ ...inv.composer, query: q })
              run(q)
            }}
          />
        )}
        {!inv.running && inv.result && inv.result.status !== 'needs_clarification' && (
          <Report
            resp={inv.result}
            meta={meta}
            llmConfigured={llmConfigured}
          />
        )}
        {!inv.running && !inv.result && !inv.error && (
          <p className="empty">The report appears here: diagnosis, priority, likely cause and escalation on top, then the worst KPIs and the next three actions. Causes, KPIs, similar cases, validation, sources and the agent trace sit in tabs below.</p>
        )}
      </div>
    </>
  )
}

export default function Investigate() {
  const { demo } = usePrefs()
  return (
    <div className="page">
      <PageHead
        title="Investigate"
        lead={demo ? 'Pick an incident (keys 1 to 5) or describe one. The report leads with the diagnosis, priority, likely cause and the next three actions.' : 'Describe a network problem to get a diagnosis, likely causes and ordered actions, grounded in similar historical cases and the runbooks.'}
      />
      <Guard>{(meta) => <InvestigateBody meta={meta} />}</Guard>
    </div>
  )
}
