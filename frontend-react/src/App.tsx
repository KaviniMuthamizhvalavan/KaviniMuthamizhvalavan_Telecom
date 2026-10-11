import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Shell } from './components/Shell'
import { PRODUCT } from './lib/copy'
import Investigate from './pages/Investigate'

const Cases = lazy(() => import('./pages/Cases'))
const Simulate = lazy(() => import('./pages/Simulate'))
const Quality = lazy(() => import('./pages/Quality'))

const TITLES: Record<string, string> = { '/': 'Investigate', '/cases': 'Cases', '/simulate': 'Simulate', '/quality': 'Quality' }

export default function App() {
  const { pathname } = useLocation()
  useEffect(() => {
    document.title = `${TITLES[pathname] ?? 'Not found'} - ${PRODUCT}`
  }, [pathname])
  return (
    <Shell>
      <Suspense fallback={<div className="skeleton" style={{ height: 200 }} />}>
        <Routes>
          <Route path="/" element={<Investigate />} />
          <Route path="/cases" element={<Cases />} />
          <Route path="/simulate" element={<Simulate />} />
          <Route path="/quality" element={<Quality />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Shell>
  )
}
