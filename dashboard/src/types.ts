export type ModelMix = {
  model: string;
  provider: string;
  tokens: number;
  spend_usd: number;
};

export type AlertRow = {
  metric: string;
  threshold: string;
  message: string;
};

export type TeamSummary = {
  id: string;
  name: string;
  residency: string;
  rpm_limit: number;
  tpm_limit: number;
  tokens_used: number;
  token_budget: number;
  spend_usd: number;
  usd_budget: number;
  requests: number;
  rate_limit_hits: number;
  guardrail_blocks: number;
  errors: number;
  error_rate: number;
  avg_latency_ms: number;
  model_mix: ModelMix[];
  alerts: AlertRow[];
};

export type DashboardSummary = {
  month: string;
  generated_at: string;
  teams: TeamSummary[];
};
