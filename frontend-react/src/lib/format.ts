// One number style everywhere (ported from frontend/formatting.py so both frontends read the same).

export const fmtPct = (p: number | null | undefined, digits = 0) => (p == null ? 'n/a' : `${(p * 100).toFixed(digits)}%`)

export const fmtNum = (v: number | null | undefined, digits = 0) =>
  v == null ? 'n/a' : v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })

/** KPI value: integers without decimals, others with up to 2. */
export function fmtValue(v: number | null | undefined): string {
  if (v == null) return 'n/a'
  if (Number.isInteger(v)) return v.toLocaleString('en-US')
  return v.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

export const fmtMbps = (v: number | null | undefined) => (v == null ? 'n/a' : `${fmtNum(v)} Mbps`)
export const fmtSeconds = (ms: number | null | undefined, digits = 1) => (ms == null ? 'n/a' : (ms / 1000).toFixed(digits))
export const fmtSignedPct = (v: number | null | undefined) => (v == null ? 'n/a' : `${v > 0 ? '+' : ''}${v.toFixed(0)}%`)

export function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase())
}

export const location = (state: string, city?: string | null) => (city ? `${titleCase(city)}, ${state}` : state)

/** 'weather=Snow' -> 'Weather: Snow', 'adverse_weather' -> 'Adverse weather'; LLM-written prose stays as is. */
export function factorLabel(factor: string): string {
  if (factor.includes('=')) {
    const [k, v] = factor.split('=', 2)
    return `${capitalize(k.replace(/_/g, ' '))}: ${v}`
  }
  if (!factor.includes('_')) return factor
  return capitalize(factor.replace(/_/g, ' ').trim())
}

export const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s)
export const humanize = (s: string) => capitalize(s.replace(/_/g, ' '))

export function joinList(items: string[]): string {
  if (items.length <= 1) return items.join('')
  if (items.length === 2) return `${items[0]} and ${items[1]}`
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** The most restrictive-looking filter to suggest removing. */
export function firstFilter(applied: Record<string, unknown>): string | null {
  for (const key of ['symptoms', 'city', 'state', 'weather', 'season', 'categories', 'priority', 'kpi_ranges']) {
    const v = applied[key]
    if (v && (!Array.isArray(v) || v.length)) return ({ categories: 'incident type', kpi_ranges: 'KPI range' } as Record<string, string>)[key] ?? key
  }
  return null
}

export const CITATION_RE = /\b(?:CASE-\d{6}|KB-[A-Z_]+-[a-z0-9-]+)\b/g

/** Utc ISO timestamp -> 'YYYY-MM-DD HH:MM'. */
export const fmtStamp = (iso: string) => iso.slice(0, 16).replace('T', ' ')

/** Counts are integers in the inputs; everything else keeps two decimals. */
export const COUNT_UNITS = new Set(['users', 'alarms', 'incidents', 'failures', 'changes'])

// ---------------------------------------------------------------- model names for evaluation runs
const PROVIDER_NAME: Record<string, string> = { aicredits: 'AICredits', anthropic: 'the Claude API', openai_compatible: 'NVIDIA' }

/** "anthropic/claude-haiku-5.5" or "claude-sonnet-5-5" -> "Claude Haiku 5.5"; other ids lose only the provider prefix. */
export function modelName(id: string | undefined | null): string {
  if (!id) return 'n/a'
  const bare = id.replace(/^[a-z0-9-]+\//i, '')
  const m = /^claude-([a-z]+)-(\d+)[-.](\d+)$/i.exec(bare)
  return m ? `Claude ${capitalize(m[1])} ${m[2]}.${m[3]}` : bare
}

/** An evaluation configuration named by its models: "Claude Haiku 5.5 via AICredits, judged by gpt-oss-120b". */
export function runLabel(models: { runtime?: string; runtime_provider?: string; eval_judge?: string } | undefined): string {
  const via = models?.runtime_provider ? PROVIDER_NAME[models.runtime_provider] : undefined
  return `${modelName(models?.runtime)}${via ? ` via ${via}` : ''}, judged by ${modelName(models?.eval_judge)}`
}
