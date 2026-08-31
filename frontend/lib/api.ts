export interface BatchSummary {
  total_cases: number;
  recovered_count: number;
  escalated_count: number;
  abandoned_count: number;
  recovery_rate_pct: number;
  total_amount_at_risk: number;
  total_amount_recovered: number;
  dollar_recovery_rate_pct: number;
  avg_time_to_recovery_hours: number;
  median_time_to_recovery_hours: number;
  by_resolution_source: { real: number; simulated: number };
}

export interface Funnel {
  detected: number;
  diagnosed: number;
  intervention_decided: number;
  executed: number;
  queued_for_human_review: number;
  resolved: { recovered: number; escalated: number; abandoned: number };
}

export interface BreakdownRow {
  dimension: string;
  count: number;
  recovered_count: number;
  recovery_rate_pct: number;
  amount_at_risk: number;
  amount_recovered: number;
  dollar_recovery_rate_pct: number;
}

export interface ExceptionCase {
  case_id: string;
  transaction_id?: string;
  risk_status: string;
  root_cause: string;
  action_type: string;
  outcome: 'escalated' | 'abandoned';
  amount_at_risk: number;
  simulated_attempts: number | null;
  is_awaiting_due_date: boolean;
  reason: string;
}

export interface ExceptionList {
  total: number;
  real_note_used: number;
  fallback_used: number;
  cases: ExceptionCase[];
}

export interface CaseEvent {
  event_type: string;
  occurred_at: string;
  payload: Record<string, unknown>;
}

export interface AuditTrail {
  case_id: string;
  events: CaseEvent[];
}

export interface CaseSummary {
  case_id: string;
  risk_status: string;
  root_cause: string;
  action_type: string;
  outcome: 'recovered' | 'escalated' | 'abandoned';
  amount_inr: number;
}

export interface CaseList {
  total: number;
  limit: number;
  offset: number;
  cases: CaseSummary[];
}

const base = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${base}${path}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

export const api = {
  summary: () => get<BatchSummary>('/api/metrics/summary'),
  funnel: () => get<Funnel>('/api/metrics/funnel'),
  breakdown: (by: 'risk_status' | 'root_cause') => get<BreakdownRow[]>(`/api/metrics/breakdown?by=${by}`),
  exceptions: () => get<ExceptionList>('/api/cases/exceptions'),
  cases: (outcome: string) => get<CaseList>(`/api/cases?limit=200${outcome ? '&outcome=' + outcome : ''}`),
  audit: (id: string) => get<AuditTrail>(`/api/cases/${encodeURIComponent(id)}/audit-trail`),
};
