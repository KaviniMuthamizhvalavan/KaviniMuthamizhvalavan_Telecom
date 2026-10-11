// The current investigation survives switching between areas: the request, its result or error, and timing.
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import { runTroubleshoot } from '../api/troubleshoot'
import type { TroubleshootRequest, TroubleshootResponse } from '../api/types'
import { EMPTY_COMPOSER, type ComposerState } from '../report/Composer'

export interface Investigation {
  request: TroubleshootRequest | null
  result: TroubleshootResponse | null
  error: ApiError | null
  running: boolean
  startedAt: number | null
  elapsedMs: number | null
  feedbackSent: Set<string>
}

interface Ctx extends Investigation {
  composer: ComposerState
  setComposer: (s: ComposerState) => void
  run: (body: TroubleshootRequest) => void
  cancel: () => void
  reset: () => void
  markFeedbackSent: (runId: string) => void
}

const InvCtx = createContext<Ctx | null>(null)

const EMPTY: Investigation = { request: null, result: null, error: null, running: false, startedAt: null, elapsedMs: null, feedbackSent: new Set() }

export function InvestigationProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Investigation>(EMPTY)
  const [composer, setComposer] = useState<ComposerState>(EMPTY_COMPOSER)
  const ctrl = useRef<AbortController | null>(null)

  const run = useCallback((body: TroubleshootRequest) => {
    ctrl.current?.abort()
    const c = new AbortController()
    ctrl.current = c
    const startedAt = performance.now()
    setState((s) => ({ ...s, request: body, result: null, error: null, running: true, startedAt, elapsedMs: null }))
    runTroubleshoot(body, c.signal)
      .then((result) => {
        if (c.signal.aborted) return
        setState((s) => ({ ...s, result, running: false, elapsedMs: performance.now() - startedAt }))
      })
      .catch((err: unknown) => {
        if (c.signal.aborted) return
        const error = err instanceof ApiError ? err : new ApiError('INTERNAL_ERROR', String(err))
        setState((s) => ({ ...s, error, running: false, elapsedMs: performance.now() - startedAt }))
      })
  }, [])

  const cancel = useCallback(() => {
    ctrl.current?.abort()
    setState((s) => ({ ...s, running: false, startedAt: null }))
  }, [])

  const reset = useCallback(() => {
    ctrl.current?.abort()
    setState((s) => ({ ...EMPTY, feedbackSent: s.feedbackSent }))
  }, [])

  const markFeedbackSent = useCallback((runId: string) => {
    setState((s) => ({ ...s, feedbackSent: new Set(s.feedbackSent).add(runId) }))
  }, [])

  return <InvCtx.Provider value={{ ...state, composer, setComposer, run, cancel, reset, markFeedbackSent }}>{children}</InvCtx.Provider>
}

export function useInvestigation(): Ctx {
  const v = useContext(InvCtx)
  if (!v) throw new Error('useInvestigation outside InvestigationProvider')
  return v
}
