// Read-only server state. /health refreshes every 20 s, /metadata is fetched once per session.
import { useQuery } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import type { Health } from '../api/types'

export type Mode = 'full' | 'reduced' | 'offline' | 'loading'

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: () => api.health(), refetchInterval: 20_000, retry: false })
}

export function useMetadata() {
  return useQuery({ queryKey: ['metadata'], queryFn: api.metadata, staleTime: Infinity, retry: 1 })
}

export function useCase(caseId: string | null) {
  return useQuery({
    queryKey: ['case', caseId],
    queryFn: () => api.getCase(caseId as string),
    enabled: !!caseId,
    staleTime: Infinity,
    retry: (n, err) => !(err instanceof ApiError && err.code === 'NOT_FOUND') && n < 1,
  })
}

/** Mode from /health: no new API fields, same rule as the Streamlit app. */
export function modeFrom(data: Health | undefined, isError: boolean, isPending: boolean): Mode {
  if (isPending) return 'loading'
  if (isError || !data) return 'offline'
  const llm = data.components.llm
  if (!llm.configured || llm.reachable === false) return 'reduced'
  return 'full'
}

export function useMode() {
  const h = useHealth()
  return { mode: modeFrom(h.data, h.isError, h.isPending), health: h }
}
