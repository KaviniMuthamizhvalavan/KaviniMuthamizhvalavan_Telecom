// Per-viewer conveniences: theme and demo mode. Stored in localStorage when available; the app works without it.
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark' | 'system'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    /* storage unavailable: keep the in-memory value */
  }
}

interface Prefs {
  theme: Theme
  resolvedTheme: 'light' | 'dark'
  setTheme: (t: Theme) => void
  demo: boolean
  setDemo: (d: boolean) => void
}

const Ctx = createContext<Prefs | null>(null)

const systemDark = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    const t = read('nt-theme')
    return t === 'light' || t === 'dark' ? t : 'system'
  })
  const [demo, setDemoState] = useState(() => read('nt-demo') === '1')
  const [sysDark, setSysDark] = useState(systemDark)

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const on = (e: MediaQueryListEvent) => setSysDark(e.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') delete root.dataset.theme
    else root.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    document.documentElement.dataset.demo = demo ? 'on' : 'off'
  }, [demo])

  const value: Prefs = {
    theme,
    resolvedTheme: theme === 'system' ? (sysDark ? 'dark' : 'light') : theme,
    setTheme: (t) => {
      setThemeState(t)
      write('nt-theme', t === 'system' ? null : t)
    },
    demo,
    setDemo: (d) => {
      setDemoState(d)
      write('nt-demo', d ? '1' : null)
    },
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function usePrefs(): Prefs {
  const v = useContext(Ctx)
  if (!v) throw new Error('usePrefs outside PrefsProvider')
  return v
}
