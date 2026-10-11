// Root-cause hypotheses as compact rows, most likely first; evidence and sources open per row. Contributing
// factors and data limitations stay collapsed.
import { useState } from 'react'
import type { Hypothesis, TroubleshootResponse } from '../api/types'
import { CiteList, Disclosure } from '../components/ui'
import { EVIDENCE_LABEL } from '../lib/copy'
import { factorLabel } from '../lib/format'

const LEVEL = { high: 3, medium: 2, low: 1 } as const

export function Likelihood({ level }: { level: Hypothesis['likelihood'] }) {
  const n = LEVEL[level] ?? 1
  return (
    <span className="likelihood" aria-label={`${level} likelihood`}>
      <span className="meter" aria-hidden>
        {[1, 2, 3].map((i) => (
          <span key={i} className={i <= n ? 'on' : ''} />
        ))}
      </span>
      <span className="likelihood-word">{level[0].toUpperCase() + level.slice(1)} likelihood</span>
    </span>
  )
}

function HypothesisItem({ h, n }: { h: Hypothesis; n: number }) {
  const [open, setOpen] = useState(false)
  return (
    <li className={`hyp${n === 1 ? ' lead' : ''}`}>
      <span className="hyp-n num" aria-hidden>
        {n}
      </span>
      <div className="hyp-body">
        <p className="hyp-cause">{h.cause}</p>
        <p className="hyp-meta">
          <Likelihood level={h.likelihood} />
          <span className="muted">Evidence: {EVIDENCE_LABEL[h.evidence_type] ?? h.evidence_type}</span>
        </p>
        {open && (
          <div className="hyp-evidence">
            <ul className="foot-list">
              {h.supporting_evidence.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
            <CiteList ids={h.citations} />
          </div>
        )}
      </div>
      {(h.supporting_evidence.length > 0 || h.citations.length > 0) && (
        <button type="button" className="btn-link action-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Hide evidence' : `Evidence (${h.supporting_evidence.length})`}
        </button>
      )}
    </li>
  )
}

export function Causes({ resp }: { resp: TroubleshootResponse }) {
  const rca = resp.root_cause_analysis
  if (!rca) return <p className="muted">No root-cause analysis was produced.</p>
  return (
    <div>
      <ol className="hyp-list">
        {rca.hypotheses.map((h, i) => (
          <HypothesisItem key={i} h={h} n={i + 1} />
        ))}
      </ol>
      {rca.contributing_factors.length > 0 && (
        <Disclosure summary="Contributing factors" aside={rca.contributing_factors.length}>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th scope="col">Factor</th>
                  <th scope="col">Effect</th>
                  <th scope="col">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {rca.contributing_factors.map((f, i) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 550, minWidth: 160 }}>{factorLabel(f.factor)}</td>
                    <td className="nowrap secondary">{f.direction}</td>
                    <td className="secondary">{f.evidence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Disclosure>
      )}
      {rca.data_limitations.length > 0 && (
        <Disclosure summary="Data limitations" aside={rca.data_limitations.length}>
          <ul className="foot-list">
            {rca.data_limitations.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </Disclosure>
      )}
    </div>
  )
}
