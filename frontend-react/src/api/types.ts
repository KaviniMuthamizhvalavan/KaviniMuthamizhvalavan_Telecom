// Response shapes of the FastAPI backend (/api/v1), mirrored from src/api/schemas.py. The UI renders only these
// fields; it never computes a new number of its own beyond formatting.

export type Band = 'normal' | 'degraded' | 'critical'
export type RiskBand = 'Low' | 'Medium' | 'High'
export type Priority = 'P1' | 'P2' | 'P3' | 'P4'
export type Verdict = 'pass' | 'fail' | 'unvalidated'

export interface ApiEnvelope {
  request_id: string
  warnings: string[]
}

export interface Health {
  status: 'ok' | 'not_ready'
  ready: boolean
  data_source: string
  components: {
    llm: { provider: string; model: string; configured: boolean; reachable: boolean | null }
    vector_store?: { ok: boolean; cases_count?: number; kb_count?: number }
    missing?: string[]
    [key: string]: unknown
  }
  versions: Record<string, string>
}

export interface KpiInfo {
  name: string
  label: string
  unit: string
  direction: number
  min: number
  max: number
  p25: number
  p50: number
  p75: number
  p90: number
}

export interface Metadata extends ApiEnvelope {
  states: { code: string; name: string; count: number }[]
  seasons: string[]
  weather: string[]
  categories: { code: string; name: string; description: string; count: number }[]
  symptoms: { code: string; kpi: string; direction: number; label: string }[]
  kpis: KpiInfo[]
  priorities: string[]
  corpus_size: number
}

export interface SearchFilters {
  state?: string[]
  city?: string
  season?: string[]
  weather?: string[]
  priority?: string[]
  categories?: string[]
  symptoms?: string[]
}

export type KpiSnapshot = Record<string, number | string>

export interface Anomaly {
  kpi: string
  label: string
  value: number
  unit: string
  band: Band
  percentile: number
  worse_than_pct?: number
  imputed?: boolean
}

export interface CaseResult {
  rank: number
  case_id: string
  final_score: number
  score_breakdown: {
    dense_rank: number | null
    bm25_rank: number | null
    rrf: number
    symptom_overlap: number
    feedback_prior: number
  }
  state: string
  city: string
  season: string
  weather: string
  primary_category: string
  secondary_categories: string[]
  priority: string
  fault_risk_band: RiskBand
  anomalies: Anomaly[]
  summary: string
}

export interface SearchResponse extends ApiEnvelope {
  query: string
  mode: string
  parsed: { symptoms: string[]; filters: Record<string, string[]> }
  applied_filters: Record<string, unknown>
  expansion_terms: string[]
  total_candidates: number
  timings_ms: Record<string, number>
  results: CaseResult[]
}

export interface PerKpi {
  kpi: string
  label: string
  value: number
  unit: string
  percentile: number
  band: Band
}

export interface CaseDetail extends ApiEnvelope {
  case_id: string
  raw: Record<string, unknown>
  normalized: Record<string, number | string | boolean | null>
  assessment: { per_kpi: PerKpi[] }
  symptoms: string[]
  env_tags: string[]
  category_scores: Record<string, number>
  primary_category: string
  secondary_categories: string[]
  priority: { level: string; label: string; score: number; components: Record<string, number> }
  fault_risk_prob: number
  fault_risk_band: RiskBand
  narrative: string
}

export interface PriorityDetail {
  level: string
  label: string
  score: number
  components: Record<string, number>
  overrides: string[]
  reasons: string[]
}

export interface Driver {
  feature: string
  importance: number
  value: unknown
  band: string | null
  imputed: boolean
}

export interface PrioritizeResponse extends ApiEnvelope {
  priority: PriorityDetail
  anomalies: Anomaly[]
  fault_risk_prob: number
  imputed_fields: string[]
}

export interface FaultRiskResponse extends ApiEnvelope {
  probability: number
  band: RiskBand
  definition: string
  top_drivers: Driver[]
  imputed_fields: string[]
  model: { version?: string; roc_auc: number }
}

export interface PerformanceResponse extends ApiEnvelope {
  expected_throughput_mbps: number
  observed_throughput_mbps: number | null
  deficit_pct: number | null
  assessment: 'below_expected' | 'as_expected' | 'above_expected' | null
  model: { version?: string; r2: number; mae?: number }
  imputed_fields: string[]
}

export interface Classification {
  primary_category: string
  secondary_categories: string[]
  symptoms: string[]
  filters: { state: string[]; city: string | null; season: string[]; weather: string[] }
  severity_hint: string
  in_scope: boolean
  needs_clarification: boolean
  clarification_question: string | null
  confidence: number
  rationale: string
  source: 'llm' | 'rules' | 'merged'
}

export interface Hypothesis {
  cause: string
  likelihood: 'high' | 'medium' | 'low'
  evidence_type: 'data' | 'knowledge' | 'both'
  supporting_evidence: string[]
  citations: string[]
}

export interface ContributingFactor {
  factor: string
  direction: string
  evidence: string
  citation: string
}

export interface Recommendation {
  step: number
  action: string
  phase: 'immediate' | 'short_term' | 'preventive'
  rationale: string
  expected_kpi_effect: string
  verification: string
  risk_level: 'low' | 'medium' | 'high'
  requires_change_approval: boolean
  citations: string[]
}

export interface RuleCheck {
  rule: string
  passed: boolean
  critical: boolean
  target: string
  detail: string
}

export interface Validation {
  verdict: Verdict
  scores: Record<string, number>
  issues: { target?: string; problem?: string; fix_instruction?: string }[]
  revisions: number
  rule_checks: RuleCheck[]
  summary: string
}

export interface TraceEntry {
  node: string
  ms: number
  llm_calls: number
  tokens_in: number
  tokens_out: number
  tool_calls: string[]
  status: string
}

export interface Source {
  id: string
  type: 'case' | 'runbook'
  title: string
  snippet: string
  score: number | null
}

export interface RunMeta {
  model: string
  judge_model: string
  prompt_version: string
  latency_ms: number
  llm_calls: number
  tokens_in: number
  tokens_out: number
  cached_calls: number
}

export interface TroubleshootResponse extends ApiEnvelope {
  run_id: string
  status: 'ok' | 'degraded' | 'needs_clarification'
  classification: Classification
  applied_filters: Record<string, unknown>
  similar_cases: CaseResult[]
  kpi_assessment: { basis: 'provided_kpis' | 'similar_cases_median'; anomalies: Anomaly[]; imputed_fields: string[] } | null
  segment_stats: {
    count: number
    top_lifts: { factor: string; segment_rate: number; corpus_rate: number; lift: number | null }[]
    priority_mix: Record<string, number>
    median_fault_rate: number | null
  } | null
  root_cause_analysis: {
    hypotheses: Hypothesis[]
    contributing_factors: ContributingFactor[]
    data_limitations: string[]
  } | null
  impact: {
    level: string | null
    affected_services: string[]
    users_served: number | null
    data_gb: number | null
    narrative: string
  } | null
  fault_risk: { probability: number; band: RiskBand; top_drivers: Driver[]; basis: string } | null
  performance_prediction: {
    expected_throughput_mbps: number
    observed: number | null
    deficit_pct: number | null
    model_r2: number
  } | null
  priority: PriorityDetail | null
  recommendations: Recommendation[]
  escalation: { needed: boolean; team: string; reason: string } | null
  validation: Validation | null
  sources: Source[]
  trace: TraceEntry[]
  meta: RunMeta
}

export interface TroubleshootRequest {
  query: string
  top_k?: number
  filters?: SearchFilters
  kpis?: KpiSnapshot
  options?: { max_revisions?: 0 | 1; include_trace?: boolean }
}

export interface FeedbackRequest {
  run_id: string
  rating?: number
  helpful?: boolean
  corrected_category?: string
  comment?: string
  case_feedback?: { case_id: string; relevant: boolean }[]
}

export interface FeedbackResponse extends ApiEnvelope {
  feedback_id: number
  accepted: boolean
  effects: Record<string, unknown>
}

export interface FeedbackSummary extends ApiEnvelope {
  total_runs: number
  total_feedback: number
  avg_rating: number | null
  helpful_rate: number | null
  by_category: { category: string; n: number; avg_rating: number | null }[]
  most_downvoted_cases: { case_id: string; category: string; up: number; down: number }[]
  corrections_count: number
  trend: { date: string; n: number; avg_rating: number | null }[]
}

export interface OfflineEvaluation {
  /** Folder id; set on additional configurations only. */
  id?: string
  generated_utc?: string
  totals?: Record<string, number>
  models?: { runtime?: string; runtime_provider?: string; eval_judge?: string; eval_judge_provider?: string }
  dataset?: { cases?: number }
  headline: { component: string; metric: string; value: number | string; target: string; status: string }[]
  deepeval?: { label: string; system: string; mean: number; pass_rate: number }[]
  judge_usage?: { llm_calls?: number; cached_calls?: number }
  end_to_end?: {
    n?: number
    C_latency_s?: { median?: number; p95?: number }
    C_tokens?: { mean?: number }
    C_repair_calls?: number
    C_runs_final_degraded?: number
    C_verdicts?: Record<string, number>
  }
  judge_meta?: { n_seeded?: number; detection_rate?: number; control_false_alarms?: number; controls?: number }
  report_files?: string[]
}

export interface LiveValidation {
  total: number
  verdicts: { pass: number; fail: number; unvalidated: number; not_judged: number }
  pass_rate: number | null
  by_model: {
    model: string
    runs: number
    pass: number
    fail: number
    unvalidated: number
    avg_latency_s: number | null
    avg_tokens: number | null
  }[]
  avg_scores: Record<string, number> | null
  scored_runs: number
  recent: { created_at: string; query: string; model: string; status: string; verdict: Verdict | null; latency_s: number | null }[]
}

export interface EvaluationResponse extends ApiEnvelope {
  offline: OfflineEvaluation | null
  live: LiveValidation | null
  /** Other saved configurations (2026-10-11); empty until such a run exists. */
  offline_alternatives?: OfflineEvaluation[]
}
