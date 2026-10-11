// Page-level guard: offline or not-ready APIs and metadata loading. Children render only with metadata in hand.
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Metadata } from '../api/types'
import { COPY } from '../lib/copy'
import { useHealth, useMetadata } from '../state/queries'
import { ApiErrorNotice } from './ApiErrorNotice'
import { Notice } from './ui'

export function Guard({ children }: { children: (meta: Metadata) => ReactNode }) {
  const health = useHealth()
  const meta = useMetadata()
  const qc = useQueryClient()
  const retry = () => {
    qc.invalidateQueries({ queryKey: ['health'] })
    qc.invalidateQueries({ queryKey: ['metadata'] })
  }
  if (health.isError) return <ApiErrorNotice error={health.error} retry={retry} />
  if (health.data && !health.data.ready) return <Notice kind="error" title="Not ready.">{COPY.notReady}</Notice>
  if (meta.isError) return <ApiErrorNotice error={meta.error} retry={retry} />
  if (!meta.data) return <div className="skeleton" style={{ height: 160 }} aria-label="Loading" />
  return <>{children(meta.data)}</>
}
