// User-facing strings that recur across screens. Sentence case, plain verbs, numbers always from the API.

export const PRODUCT = 'NetOps Triage'

export const EXAMPLES: { label: string; query: string }[] = [
  {
    label: 'Latency, loss, low throughput',
    query: 'A cell is experiencing high latency, packet loss, and reduced throughput. What similar network conditions have occurred before?',
  },
  {
    label: 'Poor quality, rising alarms',
    query: 'Multiple cells are experiencing poor service quality and increasing alarm counts. What factors could be contributing to the problem?',
  },
  {
    label: 'Faults and handover decline',
    query: 'A network region has increasing fault occurrence and declining handover success. What corrective actions should be considered?',
  },
  { label: 'Drops when moving', query: 'Calls drop when users move between cells, handover failures are rising' },
  { label: 'Authentication failures', query: 'Spike in authentication failures and security incidents' },
]

// KPI inputs shown first; the rest sit under "More KPIs and context".
export const KEY_KPIS = [
  'latency_ms',
  'packet_loss_pct',
  'throughput_mbps',
  'alarm_count',
  'cell_availability_pct',
  'signal_strength_dbm',
  'user_count',
  'data_usage_gb',
  'security_incidents',
]
export const CONTEXT_FIELDS = ['temperature_c', 'humidity_pct']

export const PRIORITY_LABEL: Record<string, string> = { P1: 'Critical', P2: 'High', P3: 'Medium', P4: 'Low' }
export const PHASE_LABEL: Record<string, string> = { immediate: 'Immediate', short_term: 'Short-term', preventive: 'Preventive' }
export const EVIDENCE_LABEL: Record<string, string> = { data: 'Data', knowledge: 'Runbook', both: 'Data and runbook' }
export const SCORE_LABEL: Record<string, string> = {
  groundedness: 'Groundedness',
  kpi_consistency: 'KPI consistency',
  actionability: 'Actionability',
  completeness: 'Completeness',
}
export const RETRIEVAL_MODES: { label: string; value: string }[] = [
  { label: 'Hybrid + rerank', value: 'hybrid_rerank' },
  { label: 'Hybrid', value: 'hybrid' },
  { label: 'Semantic only', value: 'dense' },
  { label: 'Keyword only', value: 'bm25' },
]

// Pipeline steps as the backend names them in the trace (src/agents/graph.py), with readable labels.
export const STEP_LABEL: Record<string, string> = {
  gate: 'Check the input',
  rules: 'Classify with keyword rules',
  classify: 'Classify the incident',
  retrieve: 'Retrieve similar cases',
  gather_evidence: 'Compute KPIs, risk, impact and priority',
  analyze: 'Analyze likely causes',
  recommend: 'Recommend actions',
  judge: 'Validate the diagnosis',
  reduced: 'Draft actions from runbooks',
  finalize: 'Assemble the report',
}

export const COPY = {
  severityNote: "Severity is relative to this network's history: degraded is worse than 75% of records, critical worse than 90%.",
  basisProvided: 'Measured: the KPI values you entered.',
  basisCases: (k: number) => `Estimated: the median of the ${k} most similar cases. No KPI values were entered.`,
  reducedNoKey:
    'Reduced mode. No AI model is configured, so classification uses keyword rules and actions come straight from the runbooks. Similar cases, risk, priority and impact are unaffected.',
  reducedDown: 'The AI model was unavailable for this analysis, so it used rule-based steps. Try again in a few minutes for the full analysis.',
  partial: (steps: string) => `Some steps fell back to rule-based output: ${steps}.`,
  lowConfidence: 'Low confidence. The validator found issues it could not resolve.',
  OUT_OF_SCOPE: 'This assistant handles telecom network problems. Describe symptoms such as latency, packet loss or dropped calls.',
  PROMPT_INJECTION: "This request was blocked because it tries to change the assistant's instructions. Describe the network problem instead.",
  GIBBERISH: 'The description could not be understood. Write a sentence about the network problem.',
  notReady: 'The backend has no data yet. Run: python -m scripts.bootstrap --source full',
  offline: 'Cannot reach the API. Start it with: uvicorn src.main:app --reload --reload-dir src',
  timeout:
    'No response after 240 seconds. The model provider may be rate limiting. Wait a minute, then run again.',
  internal: (rid: string) => `Unexpected server error. Quote request ID ${rid || 'n/a'} when reporting it.`,
  fbSaved: 'Feedback saved. Cases you marked not relevant now rank lower for similar problems.',
  cityNote: 'City names in this dataset are synthetic, so most match one record.',
}
