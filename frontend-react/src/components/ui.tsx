import { CaretRight, CheckCircle, Info, WarningCircle, Warning, X } from '@phosphor-icons/react'
import { useId, useState, type ReactNode } from 'react'
import { PRIORITY_LABEL } from '../lib/copy'

// ---------------------------------------------------------------- marks: a square plus a word, never colour alone
type Sev = 'critical' | 'high' | 'medium' | 'low'

export function Mark({ sev, children, hollow }: { sev: Sev | 'ok' | 'neutral'; children: ReactNode; hollow?: boolean }) {
  const cls = sev === 'ok' ? 'st-ok' : sev === 'neutral' ? 'st-neutral' : `sev-${sev}`
  return <span className={`mark ${cls}${hollow ? ' hollow' : ''}`}>{children}</span>
}

const PRIORITY_SEV: Record<string, Sev> = { P1: 'critical', P2: 'high', P3: 'medium', P4: 'low' }
export const priorityText = (level: string) => `${level} ${PRIORITY_LABEL[level] ?? ''}`.trim()
export const PriorityMark = ({ level }: { level: string }) => <Mark sev={PRIORITY_SEV[level] ?? 'low'}>{priorityText(level)}</Mark>

export const BandMark = ({ band }: { band: string }) =>
  band === 'critical' ? <Mark sev="critical">Critical</Mark> : band === 'degraded' ? <Mark sev="medium">Degraded</Mark> : <Mark sev="neutral" hollow>Normal</Mark>

const RISK_SEV: Record<string, Sev> = { High: 'high', Medium: 'medium', Low: 'low' }
export const RiskMark = ({ band, prefix = '' }: { band: string; prefix?: string }) => <Mark sev={RISK_SEV[band] ?? 'low'}>{prefix + band}</Mark>

const IMPACT_SEV: Record<string, Sev> = { Severe: 'critical', High: 'high', Moderate: 'medium', Low: 'low' }
export const ImpactMark = ({ level }: { level: string | null | undefined }) =>
  level ? <Mark sev={IMPACT_SEV[level] ?? 'low'}>{level}</Mark> : <span className="muted">n/a</span>

export function VerdictMark({ verdict }: { verdict: string | null | undefined }) {
  if (verdict === 'pass') return <Mark sev="ok">Validated</Mark>
  if (verdict === 'fail') return <Mark sev="high">Low confidence</Mark>
  if (verdict === 'unvalidated') return <Mark sev="neutral" hollow>Not validated</Mark>
  return <Mark sev="neutral" hollow>Not judged</Mark>
}

// ---------------------------------------------------------------- notices
export function Notice({ kind = 'info', title, children, items, actions }: { kind?: 'info' | 'warn' | 'error' | 'ok'; title?: ReactNode; children?: ReactNode; items?: string[]; actions?: ReactNode }) {
  const Icon = kind === 'error' ? WarningCircle : kind === 'warn' ? Warning : kind === 'ok' ? CheckCircle : Info
  return (
    <div className={`notice ${kind === 'info' ? '' : kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <Icon size={18} weight="regular" aria-hidden />
      <div>
        {title && <b>{title} </b>}
        {children}
        {items && items.length > 0 && (
          <ul>
            {items.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        )}
        {actions && <div className="actions">{actions}</div>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- section with a ruled head
export function Section({ id, title, meta, children, className = '' }: { id?: string; title: ReactNode; meta?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`section ${className}`} aria-labelledby={id ? `${id}-h` : undefined} id={id}>
      <div className="section-head">
        <h2 id={id ? `${id}-h` : undefined}>{title}</h2>
        {meta && <div className="meta">{meta}</div>}
      </div>
      {children}
    </section>
  )
}

export const Empty = ({ children }: { children: ReactNode }) => <p className="empty">{children}</p>

// ---------------------------------------------------------------- tabs (WAI-ARIA tabs, arrow keys move focus)
export interface TabDef {
  id: string
  label: ReactNode
  count?: number
  render: () => ReactNode
}

export function Tabs({ tabs, label, initial, active: controlled, onChange }: { tabs: TabDef[]; label: string; initial?: string; active?: string; onChange?: (id: string) => void }) {
  const [own, setOwn] = useState(initial ?? tabs[0]?.id)
  const active = controlled ?? own
  const setActive = (id: string) => {
    setOwn(id)
    onChange?.(id)
  }
  const base = useId()
  const current = tabs.find((t) => t.id === active) ?? tabs[0]
  const onKey = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]
    setActive(next.id)
    document.getElementById(`${base}-${next.id}`)?.focus()
  }
  return (
    <div>
      <div className="tabs" role="tablist" aria-label={label}>
        {tabs.map((t, i) => (
          <button
            key={t.id}
            id={`${base}-${t.id}`}
            role="tab"
            className="tab"
            aria-selected={t.id === current.id}
            aria-controls={`${base}-${t.id}-panel`}
            tabIndex={t.id === current.id ? 0 : -1}
            onClick={() => setActive(t.id)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {t.label}
            {t.count != null && <span className="count">{t.count}</span>}
          </button>
        ))}
      </div>
      <div className="tabpanel" role="tabpanel" id={`${base}-${current.id}-panel`} aria-labelledby={`${base}-${current.id}`}>
        {current.render()}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- disclosure
export function Disclosure({ summary, aside, children, defaultOpen }: { summary: ReactNode; aside?: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  return (
    <details className="disclosure" open={defaultOpen}>
      <summary>
        <CaretRight size={14} weight="bold" className="caret" aria-hidden />
        {summary}
        {aside && <span className="aside">{aside}</span>}
      </summary>
      <div className="disclosure-body">{children}</div>
    </details>
  )
}

// ---------------------------------------------------------------- fact strip
export function Facts({ items }: { items: { label: string; value: ReactNode; sub?: ReactNode; text?: boolean }[] }) {
  return (
    <dl className="facts">
      {items.map((f) => (
        <div className="fact" key={f.label}>
          <dt>{f.label}</dt>
          <dd className={f.text ? 'text' : undefined}>{f.value}</dd>
          {f.sub && <dd className="sub">{f.sub}</dd>}
        </div>
      ))}
    </dl>
  )
}

// ---------------------------------------------------------------- segmented control
export function Seg<T extends string | number>({ options, value, onChange, label }: { options: { label: string; value: T }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button type="button" key={String(o.value)} aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- multi-select as a select plus removable tokens
export function TokenSelect({ label, options, value, onChange, hint }: { label: string; options: { label: string; value: string }[]; value: string[]; onChange: (v: string[]) => void; hint?: string }) {
  const id = useId()
  const remaining = options.filter((o) => !value.includes(o.value))
  const byValue = Object.fromEntries(options.map((o) => [o.value, o.label]))
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className="select"
        value=""
        onChange={(e) => {
          if (e.target.value) onChange([...value, e.target.value])
        }}
      >
        <option value="">{value.length ? 'Add another' : 'Any'}</option>
        {remaining.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {value.length > 0 && (
        <div className="tokens">
          {value.map((v) => (
            <span className="token" key={v}>
              {byValue[v] ?? v}
              <button type="button" aria-label={`Remove ${byValue[v] ?? v}`} onClick={() => onChange(value.filter((x) => x !== v))}>
                <X size={12} weight="bold" />
              </button>
            </span>
          ))}
        </div>
      )}
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  )
}

/** Short ids (CASE-nnnnnn, KB-...) in mono, as a quiet list. */
export function CiteList({ ids }: { ids: string[] }) {
  if (!ids.length) return null
  return (
    <ul className="cite-list" aria-label="Sources">
      {ids.map((c) => (
        <li key={c} className="id secondary">
          {c}
        </li>
      ))}
    </ul>
  )
}
