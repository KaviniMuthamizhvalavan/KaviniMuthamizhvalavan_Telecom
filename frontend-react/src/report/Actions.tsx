// Next actions: the top three in priority order (the recommender lists immediate steps first), one line each.
// Verification, reasoning, expected effect and sources open per action; the rest on demand.
import { CaretDown, CaretRight, ShieldWarning } from '@phosphor-icons/react'
import { useState } from 'react'
import type { Recommendation } from '../api/types'
import { CiteList, Mark } from '../components/ui'
import { PHASE_LABEL } from '../lib/copy'

export const TOP_ACTIONS = 3

/** Split into what shows by default and what waits behind "Show more". */
export function splitActions(recs: Recommendation[], n = TOP_ACTIONS): [Recommendation[], Recommendation[]] {
  return [recs.slice(0, n), recs.slice(n)]
}

function ActionItem({ r, first }: { r: Recommendation; first: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <li className={`action${open ? ' open' : ''}${first ? ' first' : ''}`}>
      <span className="action-n num" aria-hidden>
        {r.step}
      </span>
      <div className="action-body">
        <p className="action-text">
          <span className="visually-hidden">Step {r.step}. </span>
          {r.action}
        </p>
        <p className="action-tags">
          <span className="muted">{PHASE_LABEL[r.phase]}</span>
          {r.requires_change_approval && (
            <span className="flag">
              <ShieldWarning size={14} aria-hidden /> Needs change approval
            </span>
          )}
          {r.risk_level !== 'low' && <Mark sev={r.risk_level === 'high' ? 'high' : 'medium'}>{r.risk_level === 'high' ? 'High' : 'Medium'} change risk</Mark>}
        </p>
        {open && (
          <dl className="action-more">
            {r.verification && (
              <>
                <dt>Verify</dt>
                <dd>{r.verification}</dd>
              </>
            )}
            {r.rationale && (
              <>
                <dt>Why</dt>
                <dd>{r.rationale}</dd>
              </>
            )}
            {r.expected_kpi_effect && (
              <>
                <dt>Expected effect</dt>
                <dd>{r.expected_kpi_effect}</dd>
              </>
            )}
            {r.citations.length > 0 && (
              <>
                <dt>Sources</dt>
                <dd>
                  <CiteList ids={r.citations} />
                </dd>
              </>
            )}
          </dl>
        )}
      </div>
      <button type="button" className="btn-link action-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? 'Hide details' : 'Details'}
      </button>
    </li>
  )
}

export function Actions({ recs }: { recs: Recommendation[] }) {
  const [all, setAll] = useState(false)
  if (!recs.length) return <p className="muted">No actions were produced.</p>
  const [top, rest] = splitActions(recs)
  const shown = all ? recs : top
  const counts: Record<string, number> = {}
  for (const r of rest) counts[r.phase] = (counts[r.phase] ?? 0) + 1
  const restByPhase = Object.entries(counts).map(([p, n]) => `${n} ${PHASE_LABEL[p]?.toLowerCase() ?? p}`)
  return (
    <div className="actions-block">
      <ol className="action-list">
        {shown.map((r) => (
          <ActionItem key={r.step} r={r} first={r.step === recs[0].step} />
        ))}
      </ol>
      {rest.length > 0 && (
        <button type="button" className="btn btn-ghost more-actions" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? <CaretDown size={14} weight="bold" aria-hidden /> : <CaretRight size={14} weight="bold" aria-hidden />}
          {all ? 'Show the top 3 only' : `Show ${rest.length} more action${rest.length > 1 ? 's' : ''} (${restByPhase.join(', ')})`}
        </button>
      )}
    </div>
  )
}
