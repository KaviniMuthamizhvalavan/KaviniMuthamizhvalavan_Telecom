// Rate this analysis as one compact bar (rating, helpful, submit). Per-case relevance (re-ranks future searches),
// category correction and comment sit under "More feedback". Locks after a successful submit.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { api } from '../api/client'
import { FIXTURE_MODE } from '../api/troubleshoot'
import type { FeedbackRequest, Metadata, TroubleshootResponse } from '../api/types'
import { ApiErrorNotice } from '../components/ApiErrorNotice'
import { Disclosure, Notice, Seg } from '../components/ui'
import { COPY } from '../lib/copy'
import { useInvestigation } from '../state/investigation'

type Vote = 'none' | 'yes' | 'no'

export function FeedbackForm({ resp, meta }: { resp: TroubleshootResponse; meta: Metadata }) {
  const inv = useInvestigation()
  const qc = useQueryClient()
  const [rating, setRating] = useState<number | null>(null)
  const [helpful, setHelpful] = useState<Vote>('none')
  const [votes, setVotes] = useState<Record<string, Vote>>({})
  const [corrected, setCorrected] = useState('')
  const [comment, setComment] = useState('')
  const [warn, setWarn] = useState<string | null>(null)
  const ids = { cat: useId(), comment: useId() }
  const m = useMutation({
    mutationFn: (body: FeedbackRequest) => api.feedback(body),
    onSuccess: () => {
      inv.markFeedbackSent(resp.run_id)
      qc.invalidateQueries({ queryKey: ['feedback-summary'] })
    },
  })

  if (inv.feedbackSent.has(resp.run_id)) return <Notice kind="ok">{COPY.fbSaved}</Notice>

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const body: FeedbackRequest = { run_id: resp.run_id }
    if (rating) body.rating = rating
    if (helpful !== 'none') body.helpful = helpful === 'yes'
    if (corrected) body.corrected_category = corrected
    if (comment.trim()) body.comment = comment.trim()
    const cf = Object.entries(votes)
      .filter(([, v]) => v !== 'none')
      .map(([case_id, v]) => ({ case_id, relevant: v === 'yes' }))
    if (cf.length) body.case_feedback = cf
    if (Object.keys(body).length === 1) {
      setWarn('Add a rating, a helpful vote, a case judgment, a correction or a comment first.')
      return
    }
    setWarn(null)
    m.mutate(body)
  }

  const judged = Object.values(votes).filter((v) => v !== 'none').length + (corrected ? 1 : 0) + (comment.trim() ? 1 : 0)

  return (
    <form className="feedback" onSubmit={submit}>
      <div className="fb-bar">
        <div className="fb-item">
          <span className="field-label" id="fb-rating">
            Rating
          </span>
          <div className="seg rating" role="radiogroup" aria-labelledby="fb-rating" title="1 is poor, 5 is excellent">
            {[1, 2, 3, 4, 5].map((n) => (
              <button type="button" key={n} role="radio" aria-checked={rating === n} onClick={() => setRating(rating === n ? null : n)}>
                {n}
              </button>
            ))}
          </div>
        </div>
        <div className="fb-item">
          <span className="field-label">Helpful?</span>
          <Seg
            label="Was this helpful?"
            value={helpful}
            onChange={(v) => setHelpful(v === helpful ? 'none' : v)}
            options={[
              { label: 'Yes', value: 'yes' },
              { label: 'No', value: 'no' },
            ]}
          />
        </div>
        <button type="submit" className="btn btn-primary" disabled={m.isPending || FIXTURE_MODE}>
          {m.isPending ? 'Saving' : 'Submit feedback'}
        </button>
      </div>

      <Disclosure summary="More feedback" aside={judged ? `${judged} added` : 'case relevance, correction, comment'}>
        {resp.similar_cases.length > 0 && (
          <div className="field">
            <span className="field-label">Were the similar cases relevant?</span>
            <span className="field-hint">Cases marked not relevant rank lower for similar problems of the same incident type.</span>
            <ul className="fb-cases">
              {resp.similar_cases.map((c) => (
                <li key={c.case_id}>
                  <span className="id">{c.case_id}</span>
                  <Seg
                    label={`Relevance of ${c.case_id}`}
                    value={votes[c.case_id] ?? 'none'}
                    onChange={(v) => setVotes({ ...votes, [c.case_id]: v })}
                    options={[
                      { label: 'Not judged', value: 'none' },
                      { label: 'Relevant', value: 'yes' },
                      { label: 'Not relevant', value: 'no' },
                    ]}
                  />
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="fb-row">
          <div className="field">
            <label className="field-label" htmlFor={ids.cat}>
              Correct incident type
            </label>
            <select id={ids.cat} className="select" value={corrected} onChange={(e) => setCorrected(e.target.value)}>
              <option value="">No correction</option>
              {meta.categories.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor={ids.comment}>
              Comment
            </label>
            <input id={ids.comment} className="input" value={comment} maxLength={1000} onChange={(e) => setComment(e.target.value)} placeholder="Optional" />
          </div>
        </div>
      </Disclosure>

      {warn && <Notice kind="warn">{warn}</Notice>}
      {m.isError && <ApiErrorNotice error={m.error} />}
      {FIXTURE_MODE && <Notice>Feedback is disabled while the development fixture replays a recorded run.</Notice>}
    </form>
  )
}
