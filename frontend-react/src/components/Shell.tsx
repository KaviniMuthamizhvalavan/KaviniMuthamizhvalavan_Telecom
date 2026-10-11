import { Archive, Crosshair, Desktop, Moon, SealCheck, SlidersHorizontal, Sun } from '@phosphor-icons/react'
import { useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { api } from '../api/client'
import { FIXTURE_MODE } from '../api/troubleshoot'
import { PRODUCT } from '../lib/copy'
import { usePrefs, type Theme } from '../state/prefs'
import { useMode } from '../state/queries'
import { useInvestigation } from '../state/investigation'
import { Mark } from './ui'

const NAV = [
  { to: '/', label: 'Investigate', icon: Crosshair, end: true },
  { to: '/cases', label: 'Cases', icon: Archive },
  { to: '/simulate', label: 'Simulate', icon: SlidersHorizontal },
  { to: '/quality', label: 'Quality', icon: SealCheck },
]

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Desktop },
]

function ModeStatus() {
  const { mode, health } = useMode()
  const qc = useQueryClient()
  const [deep, setDeep] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const llm = health.data?.components.llm
  const label =
    mode === 'full' ? <Mark sev="ok">Full AI mode</Mark> : mode === 'reduced' ? <Mark sev="medium">Reduced mode</Mark> : mode === 'offline' ? <Mark sev="critical">API offline</Mark> : <span className="muted">Checking</span>
  const testModel = async () => {
    setTesting(true)
    try {
      const h = await api.health(true)
      setDeep(h.components.llm.reachable ? 'AI model reachable.' : 'AI model not reachable; analyses run in reduced mode.')
    } catch {
      setDeep('API offline.')
    } finally {
      setTesting(false)
    }
  }
  return (
    <div className="mode-status">
      <div className="mode-line">{label}</div>
      {llm && (
        <div className="mode-model" title="Model used by the agents">
          {llm.configured ? <span className="id">{llm.model}</span> : 'No AI model configured'}
        </div>
      )}
      {health.data && <div className="mode-model">{health.data.data_source === 'full' ? 'Full dataset' : 'Sample dataset'}</div>}
      {FIXTURE_MODE && <div className="mode-fixture">Development fixtures on: analyses replay a recorded run.</div>}
      <div className="mode-actions">
        <button type="button" className="btn btn-ghost" onClick={() => qc.invalidateQueries({ queryKey: ['health'] })}>
          Check status
        </button>
        <button type="button" className="btn btn-ghost" onClick={testModel} disabled={testing || mode === 'offline'} title="Makes one small request to the AI model provider.">
          {testing ? 'Testing' : 'Test AI model'}
        </button>
      </div>
      {deep && (
        <p className="mode-deep" role="status">
          {deep}
        </p>
      )}
    </div>
  )
}

export function Shell({ children }: { children: ReactNode }) {
  const { theme, setTheme, demo, setDemo } = usePrefs()
  const inv = useInvestigation()
  return (
    <div className="shell">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="rail" aria-label="Application">
        <div className="brand">
          <span className="brand-name">{PRODUCT}</span>
          <span className="brand-sub">Network incident analysis</span>
        </div>
        <nav className="nav" aria-label="Areas">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className="nav-item">
              <Icon size={18} weight="regular" aria-hidden />
              <span>{label}</span>
              {to === '/' && inv.running && <span className="nav-live" aria-label="Analysis running" />}
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">
          <ModeStatus />
          <div className="rail-controls">
            <div className="seg seg-icons" role="radiogroup" aria-label="Theme">
              {THEMES.map(({ value, label, icon: Icon }) => (
                <button type="button" key={value} role="radio" aria-checked={theme === value} title={label} aria-label={label} onClick={() => setTheme(value)}>
                  <Icon size={16} aria-hidden />
                </button>
              ))}
            </div>
            <label className="switch">
              <input type="checkbox" role="switch" aria-label="Demo mode" checked={demo} onChange={(e) => setDemo(e.target.checked)} />
              <span className="switch-track" aria-hidden />
              <span>Demo mode</span>
            </label>
          </div>
        </div>
      </aside>
      <main id="main" className="main" tabIndex={-1}>
        {children}
      </main>
    </div>
  )
}

/** Page title row: heading plus one line of purpose. */
export function PageHead({ title, lead, aside }: { title: string; lead: ReactNode; aside?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        <p className="page-lead">{lead}</p>
      </div>
      {aside && <div className="page-aside">{aside}</div>}
    </header>
  )
}
