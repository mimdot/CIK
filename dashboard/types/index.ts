// Types mirroring the FastAPI backend (Sprint 04, Track B2).
// Keep in sync with api/serializers.py and core/profile_schema.py.

export interface UserProfile {
  domain: string;
  subfield?: string | null;
  methods: string[];
  tools: string[];
  skills: string[];
  experience_level: string;
  target_roles: string[];
  countries_preferred: string[];
  funding_requirement?: string | null;
  constraints: string[];
  confidence: number;
  raw_text: string;
}

export interface Opportunity {
  id: number;
  source: string;
  title: string;
  institution?: string | null;
  department?: string | null;
  country?: string | null;
  city?: string | null;
  url?: string | null;
  type?: string | null;
  field?: string | null;
  subfield?: string | null;
  topics: string[];
  deadline?: string | null;
  posted_date?: string | null;
  effective_date?: string | null;
  freshness?: string | null;
  relevance_score?: number | null;
  short_description?: string | null;
  position_type?: string | null;
  is_new: boolean;
}

export interface Match extends Opportunity {
  match_score: number;
  match_explanation: string;
  topic_score: number;
  method_score: number;
  location_score: number;
  confidence: number;
  percentile?: number;
  suggestions?: string[];
  next_actions?: string[];
}

export interface Supervisor {
  id: number;
  source?: string | null;
  name: string;
  institution?: string | null;
  department?: string | null;
  country?: string | null;
  profile_url?: string | null;
  email?: string | null;
  orcid?: string | null;
  topics: string[];
  methods: string[];
  recent_papers?: string[];
  fit_score?: number | null;
  confidence?: number | null;
}

export interface Bookmark {
  id: number;
  opportunity_id: number;
  created_at?: string | null;
  opportunity: Opportunity | null;
}

export interface Fields {
  default: string;
  profiles: string[];
}

export interface User {
  user_id: number;
  email: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page?: number;
  limit?: number;
  pages?: number;
}

export interface OpportunityFilters {
  country?: string;
  source?: string;
  type?: string;
  page?: number;
  limit?: number;
}

export interface PipelineStatus {
  run_id: string;
  status: "running" | "completed" | "failed";
  records?: number;
  error?: string;
}

export interface Health {
  status: string;
  version: string;
}

export interface Invite {
  id: number;
  code: string;
  created_by: number;
  used_by?: number | null;
  used_at?: string | null;
  used: boolean;
}

export interface InviteList {
  items: Invite[];
  created: number;
  redeemed: number;
  pending: number;
}

export interface AdminMetrics {
  users: { total: number; active: number; profiles_built: number };
  content: {
    opportunities: number;
    supervisors: number;
    matches: number;
    sources: {
      source: string;
      records: number;
      last_posted?: string | null;
    }[];
    feedback: { total: number; helpful: number };
  };
  api: {
    requests: number;
    errors: number;
    error_rate: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
    median_latency_ms: number;
  };
  jobs: {
    backend: string;
    pending: number;
    running: number;
    completed: number;
    failed: number;
    total: number;
    error?: string;
  };
  invites: { created: number; redeemed: number; pending: number };
  updated_at: string;
  // Sprint 09 (C2) — LLM ledger + source-health drift summary.
  llm?: {
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    estimated_spend_usd: number;
  };
  source_health?: { sources: number; drifted: number; erroring: number };
}

// --- Sprint 09: assistant + ops intelligence ---------------------------------
export interface AssistantDraft {
  text: string;
  model: string;
  token_count: number;
}

export interface AssistantUsage {
  limit: number;
  used: number;
  remaining: number;
}

export interface SourceHealthRow {
  source: string;
  runs: number;
  errors: number;
  last_result: number | null;
  mean: number | null;
  std: number | null;
  zscore: number | null;
  drift: boolean;
  updated_ts?: number | null;
}

export interface SourceHealthSnapshot {
  sources: SourceHealthRow[];
}

export interface DriftAlert {
  source: string;
  reason: string;
  zscore?: number | null;
  last_result?: number | null;
  mean?: number | null;
}

export interface FeedbackIntel {
  summary: { total: number; helpful: number; unhelpful: number; rate: number | null };
  brackets: { key: string; total: number; helpful: number; rate: number | null }[];
  sources: { key: string; total: number; helpful: number; rate: number | null }[];
  comments: { keywords: { keyword: string; count: number }[]; samples: { comment: string; score: number | null; source: string | null }[] };
}

export interface DeadLetterJob {
  job_id: string;
  status: string;
  error: string;
  created_at?: number | string | null;
  attempts?: number;
}

export interface WorkerHeartbeat {
  backend: string;
  workers: Record<string, number> | Record<string, never>;
  now_ts?: number;
  error?: string;
}

export interface AnomalyBucket {
  ts: number;
  requests: number;
  errors: number;
  latency_ms: number;
}

export interface AnomalySnapshot {
  slot_s: number;
  slots: AnomalyBucket[];
  current: AnomalyBucket | null;
  summaries: { requests: number; errors: number; error_rate: number; avg_latency_ms: number };
  anomalies: {
    kind: string;
    ts: number;
    id: string;
    message: string;
    value?: number;
    baseline?: number;
    rate?: number;
    rate_baseline?: number;
    z?: number;
    expected?: number;
  }[];
}

// --- API keys (Sprint 08) -----------------------------------------------------
export interface ApiKey {
  id: number;
  name: string;
  key_prefix: string;
  scopes: string[];
  quota_limit: number | null;
  rate_limit: number | null;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ApiKeyCreateResult extends ApiKey {
  raw_key: string;
}

export interface ApiKeyUsage {
  key_id: number;
  quota_limit: number | null;
  rate_limit: number | null;
  items: { date: string; requests: number; rate_limited: number }[];
  total: number;
}
