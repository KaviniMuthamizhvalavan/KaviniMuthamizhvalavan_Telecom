import fixture from '../dev/troubleshoot.fixture.json'
import type { Anomaly, Metadata, RunMeta, TroubleshootResponse } from '../api/types'
import { worstKpis } from '../components/charts'
import { worseThan } from '../components/Ruler'
import { EMPTY_FILTERS, kpiError, toFilters, toSnapshot } from '../components/forms'
import { factorLabel, firstFilter, fmtPct, fmtSignedPct, fmtValue, joinList, location, modelName, runLabel } from '../lib/format'
import { evaluationRuns } from '../pages/Quality'
import { splitActions, TOP_ACTIONS } from '../report/Actions'
import { buildRequest, EMPTY_COMPOSER } from '../report/Composer'
import { diagnosisSentence } from '../report/Report'
import { cacheNote } from '../report/Timeline'

const kpi = { name: 'latency_ms', label: 'Latency', unit: 'ms', direction: 1, min: 0, max: 2000, p25: 49, p50: 77, p75: 105, p90: 130 }
const meta = {
  categories: [
    { code: 'TRANSPORT_QOS', name: 'Transport and QoS', description: '', count: 1 },
    { code: 'CONGESTION_CAPACITY', name: 'Congestion and capacity', description: '', count: 1 },
  ],
  symptoms: [
    { code: 'high_latency', kpi: 'latency_ms', direction: 1, label: 'high latency' },
    { code: 'high_packet_loss', kpi: 'packet_loss_pct', direction: 1, label: 'high packet loss' },
    { code: 'low_throughput', kpi: 'throughput_mbps', direction: -1, label: 'low throughput' },
  ],
  kpis: [kpi],
} as unknown as Metadata

describe('formatting', () => {
  it('formats numbers the same way as the Streamlit app', () => {
    expect(fmtPct(0.784)).toBe('78%')
    expect(fmtPct(null)).toBe('n/a')
    expect(fmtValue(14.25)).toBe('14.25')
    expect(fmtValue(9500)).toBe('9,500')
    expect(fmtSignedPct(-39.1)).toBe('-39%')
    expect(location('TX', 'new michael')).toBe('New Michael, TX')
    expect(factorLabel('weather=Snow')).toBe('Weather: Snow')
    expect(factorLabel('adverse_weather')).toBe('Adverse weather')
    expect(joinList(['a', 'b', 'c'])).toBe('a, b and c')
    expect(firstFilter({ season: ['Winter'], state: ['TX'] })).toBe('state')
  })
})

describe('report logic', () => {
  const resp = fixture.full.response as unknown as TroubleshootResponse
  it('builds the diagnosis sentence from the classification only', () => {
    expect(diagnosisSentence(resp, meta)).toBe('Transport and QoS incident with high latency, high packet loss and low throughput')
  })
  it('places KPIs on the shared worse-than ruler', () => {
    expect(worseThan({ percentile: 0.1409, worse_than_pct: 85.9 })).toBe(85.9)
    expect(worseThan({ percentile: 0.8971 })).toBeCloseTo(89.71)
  })
  it('counts cached calls separately from billed calls', () => {
    const m = { llm_calls: 0, cached_calls: 4 } as RunMeta
    expect(cacheNote(m)).toMatch(/All 4 model calls/)
    expect(cacheNote({ ...m, llm_calls: 2, cached_calls: 1 })).toMatch(/1 model call was/)
    expect(cacheNote({ ...m, cached_calls: 0 })).toBeNull()
  })
  it('shows the top three actions first and keeps the rest in order', () => {
    const recs = resp.recommendations
    const [top, rest] = splitActions(recs)
    expect(top).toHaveLength(Math.min(TOP_ACTIONS, recs.length))
    expect([...top, ...rest].map((r) => r.step)).toEqual(recs.map((r) => r.step))
    expect(splitActions(recs.slice(0, 2))[1]).toHaveLength(0)
  })
  it('ranks the worst KPIs critical first, then by worse-than share', () => {
    const a = (kpi: string, band: string, pct: number) => ({ kpi, label: kpi, band, worse_than_pct: pct, percentile: 0, value: 0, unit: '' }) as unknown as Anomaly
    const rows = [a('x', 'degraded', 88), a('y', 'critical', 91), a('z', 'degraded', 80), a('w', 'critical', 99), a('v', 'degraded', 76)]
    expect(worstKpis(rows).map((r) => r.kpi)).toEqual(['w', 'y', 'x', 'z'])
    expect(worstKpis(rows, 2).map((r) => r.kpi)).toEqual(['w', 'y'])
    const real = resp.kpi_assessment!.anomalies
    expect(worstKpis(real, real.length)).toHaveLength(real.length)
  })
})

describe('request building', () => {
  it('rejects short descriptions and invalid KPI values', () => {
    expect(buildRequest(meta, { ...EMPTY_COMPOSER, query: 'abc' })).toMatch(/at least 5/)
    expect(kpiError(kpi, '5000')).toMatch(/Allowed/)
    expect(toSnapshot(meta, { latency_ms: 'x' })).toBeNull()
  })
  it('sends only filled filters and only used KPIs', () => {
    expect(toFilters(EMPTY_FILTERS)).toBeUndefined()
    const body = buildRequest(meta, { ...EMPTY_COMPOSER, query: 'high latency in Texas', filters: { ...EMPTY_FILTERS, state: ['TX'] }, kpis: { latency_ms: '150' } })
    expect(body).toEqual({ query: 'high latency in Texas', top_k: 5, options: { include_trace: true }, filters: { state: ['TX'] } })
    const withKpis = buildRequest(meta, { ...EMPTY_COMPOSER, query: 'high latency in Texas', useKpis: true, kpis: { latency_ms: '150', weather: 'Snow' } })
    expect(withKpis).toMatchObject({ kpis: { latency_ms: 150, weather: 'Snow' } })
  })
})

describe('evaluation configurations', () => {
  it('names each run by its models', () => {
    expect(modelName('claude-sonnet-5-5')).toBe('Claude Sonnet 5.5')
    expect(modelName('anthropic/claude-haiku-5.5')).toBe('Claude Haiku 5.5')
    expect(modelName('openai/gpt-oss-120b')).toBe('gpt-oss-120b')
    expect(runLabel({ runtime: 'claude-sonnet-5-5', eval_judge: 'claude-opus-5-5' })).toBe('Claude Sonnet 5.5, judged by Claude Opus 5.5')
    expect(runLabel({ runtime: 'anthropic/claude-haiku-5.5', runtime_provider: 'aicredits', eval_judge: 'openai/gpt-oss-120b' })).toBe(
      'Claude Haiku 5.5 via AICredits, judged by gpt-oss-120b',
    )
  })
  it('keeps the final results first and adds other runs only when they exist', () => {
    const final = { headline: [], models: { runtime: 'claude-sonnet-5-5', eval_judge: 'claude-opus-5-5' } }
    const demo = { id: 'aicredits_haiku_demo', headline: [], models: { runtime: 'anthropic/claude-haiku-5.5', eval_judge: 'openai/gpt-oss-120b' } }
    expect(evaluationRuns({ offline: final, offline_alternatives: [] }).map((r) => r.id)).toEqual(['final'])
    expect(evaluationRuns({ offline: final, offline_alternatives: [demo] }).map((r) => r.id)).toEqual(['final', 'aicredits_haiku_demo'])
    expect(evaluationRuns({ offline: final }).map((r) => r.id)).toEqual(['final'])
  })
})
