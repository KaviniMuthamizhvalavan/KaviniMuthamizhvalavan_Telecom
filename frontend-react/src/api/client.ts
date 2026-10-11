// The app's only HTTP layer. Every call goes to /api/v1 on the same origin (Vite proxies it to FastAPI) and
// either resolves with the parsed body or rejects with an ApiError. Connection failures map to API_OFFLINE and
// timeouts to TIMEOUT; backend errors come from the {"error": {code, message, details, request_id}} envelope.
import type {
  CaseDetail,
  EvaluationResponse,
  FaultRiskResponse,
  FeedbackRequest,
  FeedbackResponse,
  FeedbackSummary,
  Health,
  KpiSnapshot,
  Metadata,
  PerformanceResponse,
  PrioritizeResponse,
  SearchFilters,
  SearchResponse,
  TroubleshootRequest,
  TroubleshootResponse,
} from './types'

const PREFIX = '/api/v1'
export const FAST_TIMEOUT_MS = 15_000
// Full AI mode: median about 30-100 s depending on the model, up to about 3 min with a judge revision.
export const ANALYSIS_TIMEOUT_MS = 240_000

export class ApiError extends Error {
  code: string
  details: Record<string, unknown>
  requestId: string
  status: number | null

  constructor(code: string, message: string, details: Record<string, unknown> = {}, requestId = '', status: number | null = null) {
    super(message)
    this.code = code
    this.details = details
    this.requestId = requestId
    this.status = status
  }
}

async function call<T>(method: 'GET' | 'POST', path: string, opts: { body?: unknown; params?: Record<string, string | number>; timeoutMs?: number; signal?: AbortSignal } = {}): Promise<T> {
  const timeoutMs = opts.timeoutMs ?? FAST_TIMEOUT_MS
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort('timeout'), timeoutMs)
  opts.signal?.addEventListener('abort', () => ctrl.abort('cancelled'))
  const qs = opts.params ? '?' + new URLSearchParams(Object.entries(opts.params).map(([k, v]) => [k, String(v)])).toString() : ''
  let res: Response
  try {
    res = await fetch(PREFIX + path + qs, {
      method,
      headers: opts.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: ctrl.signal,
    })
  } catch (err) {
    if (ctrl.signal.aborted && ctrl.signal.reason === 'timeout') {
      throw new ApiError('TIMEOUT', `No response after ${Math.round(timeoutMs / 1000)} s`)
    }
    if (ctrl.signal.aborted) throw new ApiError('CANCELLED', 'Request cancelled')
    throw new ApiError('API_OFFLINE', err instanceof Error ? err.message : 'Network error')
  } finally {
    clearTimeout(timer)
  }
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  if (res.ok) return body as T
  const rid = res.headers.get('X-Request-ID') ?? ''
  const err = body && typeof body === 'object' && 'error' in body ? (body as { error: Record<string, unknown> }).error : null
  if (err) {
    throw new ApiError(String(err.code ?? 'INTERNAL_ERROR'), String(err.message ?? ''), (err.details as Record<string, unknown>) ?? {}, String(err.request_id ?? rid), res.status)
  }
  // The Vite proxy answers 502/504 with no envelope when the backend is down.
  if (res.status === 502 || res.status === 503 || res.status === 504) throw new ApiError('API_OFFLINE', `HTTP ${res.status}`, {}, rid, res.status)
  throw new ApiError('INTERNAL_ERROR', `HTTP ${res.status}`, {}, rid, res.status)
}

export const api = {
  health: (deep = false) => call<Health>('GET', '/health', { params: deep ? { deep: 'true' } : undefined, timeoutMs: deep ? 30_000 : FAST_TIMEOUT_MS }),
  metadata: () => call<Metadata>('GET', '/metadata'),
  search: (body: { query: string; filters?: SearchFilters; top_k: number; mode: string }) => call<SearchResponse>('POST', '/search', { body }),
  getCase: (caseId: string) => call<CaseDetail>('GET', `/cases/${encodeURIComponent(caseId)}`),
  troubleshoot: (body: TroubleshootRequest, signal?: AbortSignal) => call<TroubleshootResponse>('POST', '/troubleshoot', { body, timeoutMs: ANALYSIS_TIMEOUT_MS, signal }),
  prioritize: (kpis: KpiSnapshot) => call<PrioritizeResponse>('POST', '/prioritize', { body: { kpis } }),
  faultRisk: (kpis: KpiSnapshot) => call<FaultRiskResponse>('POST', '/predict/fault-risk', { body: { kpis } }),
  performance: (kpis: KpiSnapshot) => call<PerformanceResponse>('POST', '/predict/performance', { body: { kpis } }),
  feedback: (body: FeedbackRequest) => call<FeedbackResponse>('POST', '/feedback', { body }),
  feedbackSummary: (days: number) => call<FeedbackSummary>('GET', '/feedback/summary', { params: { days } }),
  evaluation: (days: number) => call<EvaluationResponse>('GET', '/evaluation/latest', { params: { days } }),
}
