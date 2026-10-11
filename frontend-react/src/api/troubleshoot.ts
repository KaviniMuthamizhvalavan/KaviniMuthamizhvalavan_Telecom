// /troubleshoot with an optional development fixture. With VITE_FIXTURES=1 in a dev server, the call returns a
// recorded response (tests/test_cases/api_examples.json) after a short delay instead of calling the backend, so the
// UI can be built and screenshotted without spending money on the AI model. The branch is removed from production
// builds because import.meta.env.DEV is statically false there.
import { api } from './client'
import type { TroubleshootRequest, TroubleshootResponse } from './types'

export const FIXTURE_MODE = import.meta.env.DEV && import.meta.env.VITE_FIXTURES === '1'
export const FIXTURE_REDUCED = FIXTURE_MODE && import.meta.env.VITE_FIXTURE_VARIANT === 'reduced'

export async function runTroubleshoot(body: TroubleshootRequest, signal?: AbortSignal): Promise<TroubleshootResponse> {
  if (FIXTURE_MODE) {
    const mod = await import('../dev/troubleshoot.fixture.json')
    const rec = (FIXTURE_REDUCED ? mod.default.reduced : mod.default.full).response as unknown as TroubleshootResponse
    await new Promise<void>((resolve, reject) => {
      const t = setTimeout(resolve, Number(import.meta.env.VITE_FIXTURE_DELAY_MS ?? 6000))
      signal?.addEventListener('abort', () => {
        clearTimeout(t)
        reject(new DOMException('Aborted', 'AbortError'))
      })
    })
    return { ...rec, run_id: `fixture-${rec.run_id}` }
  }
  return api.troubleshoot(body, signal)
}
