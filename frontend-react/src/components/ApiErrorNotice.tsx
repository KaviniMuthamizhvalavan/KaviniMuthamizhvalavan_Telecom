import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import { COPY } from '../lib/copy'
import { Notice } from './ui'

/** An API error in the state the frontend plan prescribes: what went wrong and how to recover. */
export function ApiErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error instanceof ApiError ? error : new ApiError('INTERNAL_ERROR', String(error))
  const retryBtn: ReactNode = retry ? (
    <button type="button" className="btn" onClick={retry}>
      Retry
    </button>
  ) : undefined
  switch (e.code) {
    case 'API_OFFLINE':
      return <Notice kind="error" title="API offline." actions={retryBtn}>{COPY.offline}</Notice>
    case 'TIMEOUT':
      return <Notice kind="warn" title="Timed out." actions={retryBtn}>{COPY.timeout}</Notice>
    case 'NOT_READY':
      return <Notice kind="error" title="Not ready.">{COPY.notReady}</Notice>
    case 'OUT_OF_SCOPE':
    case 'PROMPT_INJECTION':
    case 'GIBBERISH':
      return <Notice kind="error">{COPY[e.code]} Or pick an example.</Notice>
    case 'INVALID_FILTER': {
      const allowed = e.details.allowed as unknown[] | undefined
      return <Notice kind="error">{e.message}.{allowed ? ` Allowed values: ${allowed.slice(0, 20).join(', ')}.` : ''}</Notice>
    }
    case 'INVALID_INPUT': {
      const errs = (e.details.errors as { field?: string; message?: string }[] | undefined) ?? []
      return <Notice kind="error" items={errs.map((x) => `${x.field}: ${x.message}`)}>{e.message || 'Check the highlighted values.'}</Notice>
    }
    case 'NOT_FOUND':
      return <Notice kind="error">{e.message}</Notice>
    default:
      return <Notice kind="error" actions={retryBtn}>{COPY.internal(e.requestId)}</Notice>
  }
}
