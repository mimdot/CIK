// Dashboard API client (Sprint 04, Track B2).
// Wraps every backend endpoint; throws ApiError with the backend's message.

import type {
  AdminMetrics,
  AnomalySnapshot,
  ApiKey,
  AuthConfig,
  ApiKeyCreateResult,
  ApiKeyUsage,
  AssistantDraft,
  AssistantUsage,
  Bookmark,
  DeadLetterJob,
  DriftAlert,
  FeedbackIntel,
  Health,
  Invite,
  InviteList,
  Opportunity,
  CvAnalysis,
  DepartmentList,
  FieldCatalogue,
  FieldDetail,
  NameSuggestion,
  PositionTypeCatalogue,
  OpportunityFilters,
  Paginated,
  PipelineStatus,
  SourceHealthSnapshot,
  Supervisor,
  TokenResponse,
  User,
  UserProfile,
  WorkerHeartbeat,
} from "@/types";

// Resolve the API base per call (so late injection is picked up).
//
// The desktop shell picks a free port for the sidecar and injects the resolved
// base as `window.__CIK_API_BASE__`. That global is the authority whenever it
// is present: it only ever exists in the desktop shell, and it names the port
// the sidecar actually bound.
//
// It is deliberately NOT gated behind a `window.__TAURI__` check. Tauri v2
// only defines `__TAURI__` when `app.withGlobalTauri` is set, which this app
// does not set — so that check was always false, the injected base was never
// read, and the desktop app silently used the web default instead. Every bit
// of the shell's port-picking was dead code on the frontend side.
export function apiBase(): string {
  if (typeof window !== "undefined") {
    const injected = (window as unknown as { __CIK_API_BASE__?: string })
      .__CIK_API_BASE__;
    if (typeof injected === "string" && injected) return injected;
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

/**
 * Why the desktop backend is unavailable, straight from the Rust shell.
 *
 * The shell health-checks the sidecar before handing the page a base URL. When
 * it cannot start one — port conflict, missing bundled file, a Python import
 * error — it publishes the real reason (with the tail of the backend log) here.
 * Without this the UI could only ever say "is it running?", which is the one
 * thing the user cannot answer: the shell is what starts it.
 */
export function apiStartupError(): string | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    __CIK_API_ERROR__?: string | null;
    __CIK_API_READY__?: boolean;
  };
  if (w.__CIK_API_READY__ === false && w.__CIK_API_ERROR__) {
    return w.__CIK_API_ERROR__;
  }
  return null;
}

const TOKEN_KEY = "cik_token";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// The JWT lives in an httpOnly cookie (set by the API) so it is out of reach
// of XSS. JS cannot read an httpOnly cookie, so we keep the token from the
// login response in memory for the lifetime of the tab; getToken() falls back
// to reading the cookie for setups that expose it to JS (non-httpOnly).
let _sessionToken: string | null = null;

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const escaped = name.replace(/([.*+?^=!:${}()|[\]/\\])/g, "\\$1");
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${escaped}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

export function getToken(): string | null {
  if (_sessionToken) return _sessionToken;
  return readCookie(TOKEN_KEY);
}

export function setToken(token: string): void {
  _sessionToken = token;
}

export function clearToken(): void {
  _sessionToken = null;
}

// Sprint 07 (B3): the API sets a non-httpOnly csrf_token cookie on login; the
// CSRF middleware requires mutating requests that use cookie auth to echo it
// back in X-CSRF-Token (double-submit). Bearer-authenticated requests bypass
// the check, but we send the header anyway for defense-in-depth.
function csrfToken(): string | null {
  return readCookie("csrf_token");
}

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function request<T>(
  path: string,
  options: RequestInit = {},
  auth = true,
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
    "Content-Type": "application/json",
  };
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  if (MUTATING_METHODS.has(method)) {
    const csrf = csrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, {
      ...options,
      headers,
      credentials: "include",
    });
  } catch {
    throw new ApiError("Cannot reach the API server. Is it running?", 0);
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    // FastAPI validation errors return detail as an array of {loc, msg, ...}
    // objects; String()-ing that array yields "[object Object]". Normalize to
    // a human-readable message whether detail is a string, a list, or absent.
    const rawDetail = (data as { detail?: unknown })?.detail;
    let message: string;
    if (typeof rawDetail === "string") {
      message = rawDetail;
    } else if (Array.isArray(rawDetail)) {
      message = rawDetail
        .map((entry) => {
          if (entry && typeof entry === "object" && "msg" in entry) {
            return String((entry as { msg: unknown }).msg);
          }
          return String(entry);
        })
        .filter(Boolean)
        .join("; ");
    } else if (typeof data === "string") {
      message = data;
    } else {
      message = `Request failed (${res.status})`;
    }
    throw new ApiError(message || `Request failed (${res.status})`, res.status);
  }
  return data as T;
}

// --- meta --------------------------------------------------------------------
export function fetchHealth(): Promise<Health> {
  return request<Health>("/health", {}, false);
}

export function fetchFields(): Promise<FieldCatalogue> {
  return request<FieldCatalogue>("/api/fields", {}, false);
}

/**
 * One field in full, including every subfield's curated keyword list. Backs
 * the subfield multi-select and the keyword picker — the keywords are the same
 * vocabulary the relevance engine scores against, so a picked term cannot fail
 * to match the way a free-text guess can.
 */
export function fetchField(name: string): Promise<FieldDetail> {
  return request<FieldDetail>(
    `/api/fields/${encodeURIComponent(name)}`,
    {},
    false,
  );
}

/**
 * The curated department list for a field — the manual alternative to the slow
 * exhaustive sweep. Instant: no crawling, just the list to browse and open.
 */
export function fetchFieldDepartments(
  name: string,
  opts: { country?: string; q?: string } = {},
): Promise<DepartmentList> {
  const params = new URLSearchParams();
  if (opts.country) params.set("country", opts.country);
  if (opts.q) params.set("q", opts.q);
  const qs = params.toString();
  return request<DepartmentList>(
    `/api/fields/${encodeURIComponent(name)}/departments${qs ? `?${qs}` : ""}`,
    {},
    false,
  );
}

/**
 * Whether this installation reads CVs at all, and which file types.
 *
 * `enabled` is the prior question: CV reading is behind CV_PARSING_ENABLED and
 * is off by default in the desktop build, so the UI must ask before offering
 * an upload control it would only have to retract.
 */
export function fetchParserSupport(): Promise<{
  txt: boolean;
  pdf: boolean;
  docx: boolean;
  enabled: boolean;
}> {
  return request("/api/profile/parser-support", {}, false);
}

/**
 * Read a CV WITHOUT any AI service: matches it against the vocabulary the
 * relevance engine already ships, and returns editable suggestions that
 * PRE-FILL the keyword picker. Never fails wholesale — an unrecognised CV
 * comes back with a `reason` explaining which case applies.
 */
export function analyseCv(
  rawText: string,
  field?: string,
): Promise<CvAnalysis> {
  const qs = field ? `?field=${encodeURIComponent(field)}` : "";
  return request<CvAnalysis>(`/api/profile/analyse-cv${qs}`, {
    method: "POST",
    body: JSON.stringify({ raw_text: rawText }),
  });
}

/**
 * The position types a user may search for, plus the planned ones. Driven by
 * position_types.yaml, so Master's and Scholarships appear as real options the
 * moment they are enabled server-side — no frontend change needed.
 */
export function fetchPositionTypes(): Promise<PositionTypeCatalogue> {
  return request<PositionTypeCatalogue>("/api/fields/position-types", {}, false);
}

/**
 * Auto-correct a country or institution the user typed. Resolves against the
 * full ISO-3166 list and a curated institution table, tolerating misspellings
 * and abbreviations, so the UI can offer "did you mean Germany?" rather than
 * searching for a country that does not exist.
 */
export function normalizeName(
  params: { country?: string; institution?: string },
): Promise<{ country?: NameSuggestion | null; institution?: NameSuggestion | null }> {
  const qs = new URLSearchParams();
  if (params.country) qs.set("country", params.country);
  if (params.institution) qs.set("institution", params.institution);
  return request(`/api/fields/normalize?${qs.toString()}`, {}, false);
}

// --- auth ---------------------------------------------------------------------
export async function login(email: string, password: string): Promise<string> {
  const data = await request<TokenResponse>(
    "/api/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
    false,
  );
  setToken(data.access_token);
  return data.access_token;
}

export function fetchMe(): Promise<User> {
  return request<User>("/api/auth/me");
}

/**
 * How this deployment expects people to sign in.
 *
 * Asked, never inferred from the platform: the same frontend is served by the
 * desktop sidecar (shared access code) and by a server (email + password), and
 * it is the API's configuration that decides which.
 */
export function fetchAuthConfig(): Promise<AuthConfig> {
  return request<AuthConfig>("/api/auth/config", undefined, false);
}

/** Sign in with an email and the shared access code. No password involved. */
export async function signInWithAccessCode(
  email: string,
  code: string,
): Promise<string> {
  const data = await request<TokenResponse>(
    "/api/auth/access",
    { method: "POST", body: JSON.stringify({ email, code }) },
    false,
  );
  setToken(data.access_token);
  return data.access_token;
}

/** Drop the session. The cookie is httpOnly, so only the API can clear it. */
export async function logout(): Promise<void> {
  try {
    await request<{ status: string }>("/api/auth/logout", { method: "POST" });
  } finally {
    clearToken();
  }
}

// --- profile ------------------------------------------------------------------
export function fetchProfile(): Promise<UserProfile> {
  return request<UserProfile>("/api/profile");
}

export async function buildProfile(rawText: string): Promise<UserProfile> {
  return request<UserProfile>("/api/profile/build", {
    method: "POST",
    body: JSON.stringify({ raw_text: rawText }),
  });
}

// Upload a CV file (PDF/DOCX/TXT) for local, server-side text extraction.
// Sent as base64 JSON (no multipart dep); the file never leaves the backend
// and is not stored. Returns the extracted text for the user to review/edit.
export async function extractCv(
  file: File,
): Promise<{ filename: string; chars: number; raw_text: string }> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const CHUNK = 0x8000; // avoid arg-count limits on fromCharCode
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  const content_b64 = btoa(binary);
  return request("/api/profile/extract-cv", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, content_b64 }),
  });
}

export async function updateProfile(
  patch: Partial<UserProfile>,
): Promise<UserProfile> {
  return request<UserProfile>("/api/profile", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

// --- matches ------------------------------------------------------------------
export function fetchMatches(
  minScore?: number,
  limit = 50,
  field?: string,
): Promise<Paginated<Opportunity & { match_score?: number; match_explanation?: string }>> {
  const params = new URLSearchParams();
  if (minScore !== undefined) params.set("min_score", String(minScore));
  params.set("limit", String(limit));
  if (field) params.set("field", field);
  return request<Paginated<Opportunity>>(`/api/matches?${params.toString()}`);
}

export function submitMatchFeedback(
  matchId: number,
  helpful: boolean,
  comment?: string,
): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/matches/${matchId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ helpful, comment: comment ?? null }),
  });
}

// --- assistant (Sprint 09, A2) --------------------------------------------------
export function generateCoverLetter(
  opportunityId: number,
  opts: { tone?: string; length?: string } = {},
): Promise<AssistantDraft> {
  return request<AssistantDraft>("/api/assistant/cover-letter", {
    method: "POST",
    body: JSON.stringify({ opportunity_id: opportunityId, ...opts }),
  });
}

export function generateApplicationEmail(
  opportunityId: number,
): Promise<AssistantDraft> {
  return request<AssistantDraft>("/api/assistant/application-email", {
    method: "POST",
    body: JSON.stringify({ opportunity_id: opportunityId }),
  });
}

export function suggestCvImprovements(): Promise<AssistantDraft> {
  return request<AssistantDraft>("/api/assistant/cv-improvements", {
    method: "POST",
    body: "{}",
  });
}

export function fetchAssistantUsage(): Promise<AssistantUsage> {
  return request<AssistantUsage>("/api/assistant/usage");
}

// --- opportunities ------------------------------------------------------------
export function fetchOpportunities(
  filters: OpportunityFilters = {},
): Promise<Paginated<Opportunity>> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  return request(`/api/opportunities?${params.toString()}`, {}, false);
}

export function fetchOpportunity(id: number): Promise<Opportunity> {
  return request<Opportunity>(`/api/opportunities/${id}`, {}, false);
}

// --- supervisors --------------------------------------------------------------
export function fetchSupervisors(
  country?: string,
  field?: string,
  q?: string,
): Promise<Paginated<Supervisor>> {
  const params = new URLSearchParams();
  if (country) params.set("country", country);
  if (field) params.set("field", field);
  if (q) params.set("q", q);
  params.set("limit", "500");
  return request<Paginated<Supervisor>>(`/api/supervisors?${params.toString()}`);
}

export function fetchSupervisor(id: number): Promise<Supervisor> {
  return request<Supervisor>(`/api/supervisors/${id}`, {}, false);
}

// --- supervisor search (desktop "run online search") ---------------------------
export function triggerSupervisorSearch(
  body: { country: string | string[]; field?: string },
): Promise<{ status: string; run_id: string }> {
  return request("/api/supervisors/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function jobStatus(runId: string): Promise<PipelineStatus> {
  return request<PipelineStatus>(`/api/jobs/${encodeURIComponent(runId)}`);
}

/**
 * Stop a running search. Sources still in flight finish their current request
 * and everything already found is kept — the app stays usable, nothing is
 * killed, no restart is needed. Resolves once the request has landed; the run
 * reports "cancelled" when it has finished saving its partial results.
 */
export function cancelJob(runId: string): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/api/jobs/${encodeURIComponent(runId)}`,
    { method: "DELETE" },
  );
}

// --- bookmarks ----------------------------------------------------------------
export function fetchBookmarks(): Promise<Paginated<Bookmark>> {
  return request<Paginated<Bookmark>>("/api/bookmarks");
}

export function createBookmark(opportunityId: number): Promise<Bookmark> {
  return request<Bookmark>("/api/bookmarks", {
    method: "POST",
    body: JSON.stringify({ opportunity_id: opportunityId }),
  });
}

export function deleteBookmark(bookmarkId: number): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/bookmarks/${bookmarkId}`, {
    method: "DELETE",
  });
}

// --- preferences -------------------------------------------------------------
export interface DigestPreferences {
  digest_enabled: boolean;
  frequency: string | null;
}

export function fetchPreferences(): Promise<DigestPreferences> {
  return request<DigestPreferences>("/api/preferences");
}

export function updateDigestPreference(
  digestEnabled: boolean,
): Promise<DigestPreferences> {
  return request<DigestPreferences>("/api/preferences", {
    method: "POST",
    body: JSON.stringify({ digest_enabled: digestEnabled }),
  });
}

// --- pipeline -----------------------------------------------------------------
export function triggerPipeline(
  body: {
    sources?: string[];
    country?: string;
    field?: string;
    /** Subfield ids; their keywords boost matching positions. */
    subfields?: string[];
    /** Opt in to the slow university-department sweep. */
    include_slow?: boolean;
    /** Which kinds of position to hunt, e.g. ["phd"]. */
    position_types?: string[];
  },
): Promise<{ status: string; run_id: string }> {
  return request("/api/pipeline/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function pipelineStatus(runId: string): Promise<PipelineStatus> {
  return request(`/api/pipeline/status?run_id=${runId}`);
}

// --- invites (Sprint 06, C1) ---------------------------------------------------
export function validateInvite(code: string): Promise<{ valid: boolean; code: string }> {
  return request(`/api/invites/${encodeURIComponent(code)}/redeem`, {
    method: "POST",
  });
}

export async function registerWithInvite(
  email: string,
  password: string,
  inviteCode?: string,
): Promise<User> {
  return request<User>(
    "/api/auth/register",
    {
      method: "POST",
      body: JSON.stringify({ email, password, invite_code: inviteCode ?? null }),
    },
    false,
  );
}

export function createInvite(): Promise<Invite> {
  return request<Invite>("/api/invites", { method: "POST", body: "{}" });
}

export function fetchInvites(): Promise<InviteList> {
  return request<InviteList>("/api/invites");
}

// --- admin (Sprint 06, C4) -------------------------------------------------------
export function fetchAdminMetrics(): Promise<AdminMetrics> {
  return request<AdminMetrics>("/api/admin/metrics");
}

// --- admin ops intelligence (Sprint 09, B1-B4) ------------------------------------
export function fetchSourceHealth(): Promise<SourceHealthSnapshot> {
  return request<SourceHealthSnapshot>("/api/admin/source-health");
}

export function runDriftCheck(): Promise<{ alerts: DriftAlert[]; count: number }> {
  return request<{ alerts: DriftAlert[]; count: number }>(
    "/api/admin/source-health/check-drift",
    { method: "POST", body: "{}" },
  );
}

export function fetchFeedbackIntel(): Promise<FeedbackIntel> {
  return request<FeedbackIntel>("/api/admin/feedback-intel");
}

export function fetchDeadLetters(): Promise<{ jobs: DeadLetterJob[] }> {
  return request<{ jobs: DeadLetterJob[] }>("/api/admin/tasks/dead-letters");
}

export function retryDeadLetter(jobId: string): Promise<{ retried: boolean; job_id: string; new_job_id: string }> {
  return request<{ retried: boolean; job_id: string; new_job_id: string }>(
    `/api/admin/tasks/${encodeURIComponent(jobId)}/retry`,
    { method: "POST", body: "{}" },
  );
}

export function fetchWorkerHeartbeat(): Promise<WorkerHeartbeat> {
  return request<WorkerHeartbeat>("/api/admin/tasks/worker-heartbeat");
}

export function fetchAnomalies(): Promise<AnomalySnapshot> {
  return request<AnomalySnapshot>("/api/admin/anomalies");
}

export function runAnomalyDetect(): Promise<AnomalySnapshot> {
  return request<AnomalySnapshot>("/api/admin/anomalies/detect", {
    method: "POST",
    body: "{}",
  });
}

// --- API keys (Sprint 08, A3) ----------------------------------------------------
// v1 endpoints return an envelope; errors use {"error": {code, message}}.
interface V1List<T> {
  data: T[];
  meta: { page?: number; limit?: number | null; total: number; pages?: number };
}

export async function fetchKeys(): Promise<ApiKey[]> {
  const body = await request<V1List<ApiKey>>("/api/v1/apikeys");
  return body.data;
}

export async function createKey(body: {
  name: string;
  scopes?: string[];
}): Promise<ApiKeyCreateResult> {
  return request<ApiKeyCreateResult>("/api/v1/apikeys", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateKey(
  id: number,
  patch: { name?: string; scopes?: string[] },
): Promise<ApiKey> {
  return request<ApiKey>(`/api/v1/apikeys/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function revokeKey(id: number): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/v1/apikeys/${id}`, {
    method: "DELETE",
  });
}

export async function rotateKey(id: number): Promise<ApiKeyCreateResult> {
  return request<ApiKeyCreateResult>(`/api/v1/apikeys/${id}/rotate`, {
    method: "POST",
  });
}

export async function fetchKeyUsage(id: number, days = 30): Promise<ApiKeyUsage> {
  return request<ApiKeyUsage>(`/api/v1/apikeys/${id}/usage?days=${days}`);
}
