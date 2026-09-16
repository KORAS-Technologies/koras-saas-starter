/**
 * The typed client for the JSON APIs this product reads on a caller's behalf.
 *
 * One place that knows how such a call is made: where the base URL comes from,
 * how the caller's credentials are attached, how long to wait, and what a
 * failure looks like. The alternative — a `fetch` in whichever component needed
 * the data — is how five call sites end up with four opinions about timeouts
 * and none about errors.
 *
 * Two APIs are read this way and each function names which: `services/api`,
 * which is this product's own, and the Control Plane's **portal** surface,
 * which is the customer's. Neither takes an organization identifier, and that
 * is the property that makes one client safe for both — every call resolves the
 * caller's own tenant from the caller's own token.
 *
 * Deliberately free of React, of `next/*` and of the branding package. It is
 * called from server components and from server actions, and a client that
 * imported a framework could only be used from one of them.
 *
 * It also carries no types from `@<slug>/branding`, which is why this file
 * needs no template rendering: the API's response shape is the API's, and the
 * browser tier's parsers are what turn it into brand tokens. Keeping the two
 * separate is what lets the parser reject a value the API happily returned.
 */

/** How long any call may take before it is abandoned. */
const DEFAULT_TIMEOUT_MS = 5_000

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /**
     * The API's own name for the refusal, where it gave one.
     *
     * The assistant's routes answer a refusal as `{ code, message }` so the
     * page can say *why* in the reader's language -- a spent allowance and an
     * unreachable model are both errors and are different sentences. Other
     * routes answer a plain detail, and this is undefined for them.
     */
    readonly code?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** The `code` an error body carries, when it is the assistant's shape. */
async function errorCode(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    const detail = body.detail
    if (detail !== null && typeof detail === 'object' && 'code' in detail) {
      const code = (detail as { code?: unknown }).code
      return typeof code === 'string' ? code : undefined
    }
  } catch {
    // Not JSON, or not this shape. The status is still the answer.
  }
  return undefined
}

/**
 * A customer's own tenant, as the API returns it.
 *
 * `branding` and `features` are deliberately `unknown`. They are customer-
 * controlled `jsonb`, so typing them as anything more specific here would be a
 * claim this client cannot support — and the callers already pass both through
 * validating parsers before either reaches a stylesheet or a navigation gate.
 */
export interface TenantSettings {
  name: string
  slug: string
  branding: unknown
  features: unknown
  /**
   * The language the organisation's members start in, or null for none.
   *
   * A string rather than a `Locale`: the API holds it to the catalogues that
   * exist, and the caller holds it again to the list the product offers
   * before it reaches `lang`. This client makes no claim in between.
   */
  locale: string | null
  /** The caller's own stored choice, read under their own subject. Null until they choose. */
  member_locale: string | null
}

export interface RequestOptions {
  /** Origin of the API being called. Named by each function below. */
  baseUrl: string
  /**
   * The caller's own provider token.
   *
   * Not the session cookie this application signed: the API verifies against
   * ZITADEL and deliberately does not trust the browser tier to have done so.
   * And not a service credential — a call made on behalf of a person should be
   * attributed to that person.
   */
  token: string
  timeoutMs?: number
  /** Injectable for tests. Defaults to the global. */
  fetchImpl?: typeof fetch
}

interface Call {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  /** Sent as JSON. */
  body?: unknown
  /** True for a 204. */
  empty?: boolean
}

async function request<T>(path: string, options: RequestOptions, call: Call = {}): Promise<T> {
  const base = options.baseUrl.replace(/\/$/, '')
  if (!base) throw new ApiError('no API base URL is configured', 0)

  // An abort rather than a bare await. A page rendering on the server has no
  // user to cancel it, so a hung API call is a hung page render — and the
  // symptom is a timeout somewhere upstream that names the wrong thing.
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS)

  try {
    const response = await (options.fetchImpl ?? fetch)(`${base}${path}`, {
      method: call.method ?? 'GET',
      headers: {
        Authorization: `Bearer ${options.token}`,
        Accept: 'application/json',
        ...(call.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      ...(call.body !== undefined ? { body: JSON.stringify(call.body) } : {}),
      // Never cached at this layer. The response is per-tenant and per-caller,
      // and a shared cache keyed on a URL that carries neither is how one
      // customer is served another's settings. A caller that wants caching
      // should ask for it where it knows the key.
      cache: 'no-store',
      signal: controller.signal,
    })

    if (!response.ok) {
      throw new ApiError(
        `${path} answered ${response.status}`,
        response.status,
        await errorCode(response),
      )
    }
    if (call.empty) return undefined as T
    return (await response.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

/**
 * This caller's own tenant settings.
 *
 * Takes no tenant identifier, and there is nowhere to put one: the API resolves
 * the tenant from the token and scopes the read with row-level security. A
 * client that could name a tenant would be a client somebody could point at
 * another one.
 */
export function fetchTenantSettings(options: RequestOptions): Promise<TenantSettings> {
  return request<TenantSettings>('/api/v1/tenant/settings', options)
}

/**
 * Remember the language this caller chose, for every device they sign in on.
 *
 * No user identifier, and there is nowhere to put one: the API keys the row
 * on the subject of the token it verified. `null` clears the choice, so the
 * cookie and the organisation's default apply again.
 */
export function updateMyLocale(options: RequestOptions & { locale: string | null }): Promise<void> {
  return request<void>('/api/v1/me/locale', options, {
    method: 'PUT',
    body: { locale: options.locale },
    empty: true,
  })
}

/**
 * Set the language this caller's organisation starts its members in.
 *
 * Refused with 403 for a caller without `settings.manage`; the page hides
 * the form for the same people, and the API decides again with the token.
 */
export function updateTenantLocale(
  options: RequestOptions & { locale: string | null },
): Promise<void> {
  return request<void>('/api/v1/tenant/settings/locale', options, {
    method: 'PUT',
    body: { locale: options.locale },
    empty: true,
  })
}

/**
 * What this caller's organization may do in this product, from the Control Plane.
 *
 * `baseUrl` is the platform's, not this product's, and the token is the same
 * one every other call here carries: the customer's own, verified by the
 * platform against ZITADEL. Sign-in asks for the platform's project in the
 * token's audience so that verification can succeed — without that scope the
 * token is addressed to this product alone and the platform answers 401.
 *
 * `productCode` is in the path and the organization is not, which is the whole
 * of the authorisation argument. A customer can only ever resolve their own
 * plan, because there is nowhere in the request to name somebody else's.
 *
 * A `404` means this organization holds no subscription to the product — and
 * means exactly the same thing when the product code is wrong, which is why the
 * caller treats it as unresolved and says so in the log rather than reporting a
 * plan of nothing.
 */
export function fetchEntitlements(
  options: RequestOptions & { productCode: string },
): Promise<unknown> {
  return request<unknown>(
    `/api/portal/v1/products/${encodeURIComponent(options.productCode)}/entitlements`,
    options,
  )
}

/**
 * How this caller's organization wants this product to look, from the Control Plane.
 *
 * The platform's portal surface again, and the same argument as
 * `fetchEntitlements`: the product code is in the path and the organization is
 * not, so a customer can only ever read their own branding. Their own token
 * authorises it, with the platform's project already in its audience.
 *
 * This is the read that makes white labelling real. The portal is where a
 * customer sets their colours, the platform stores them, and until a product
 * fetches them here they are stored and unused. The platform's machine-only
 * tenant endpoint exists for the same values, but a product holds no machine
 * credential at runtime -- that is the F2b argument -- and this route needs
 * none.
 *
 * A customer who has set nothing is answered with a record of nulls, not a
 * `404`; a `404` means the organization holds no such product, which is the
 * same thing it means for a wrong product code.
 */
export function fetchBranding(options: RequestOptions & { productCode: string }): Promise<unknown> {
  return request<unknown>(
    `/api/portal/v1/products/${encodeURIComponent(options.productCode)}/branding`,
    options,
  )
}

/* -------------------------------------------------------------------------- */
/* Files                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * The Files surface of this product's own API.
 *
 * Tickets, not bytes: the API answers with signed URLs and the browser moves
 * the file itself. Every call is scoped by the token -- there is no tenant
 * and no organization to name -- and a file id from another tenant is a 404,
 * because the row is invisible to this caller's session before any code runs.
 */
export interface FileRow {
  id: string
  name: string
  size_bytes: number
  content_type: string
  uploaded_by: string
  uploaded_at: string
  /** When the assistant's index took the file's text; null while pending or when it could not. */
  indexed_at: string | null
  /** Why it was not indexed, or how many chunks it became. */
  index_note: string | null
  /** The SHA-256 the browser computed over the bytes it sent, if it sent one. */
  checksum_sha256: string | null
  /**
   * Whether the provider's own digest agreed with that claim. False does not
   * mean a mismatch -- most objects have no comparable provider digest -- so
   * this is "corroborated" rather than "correct".
   */
  checksum_verified: boolean
  /** pending, clean, infected or skipped. Withheld files are refused server-side. */
  scan_status: string
}

export interface FileList {
  files: FileRow[]
  used_bytes: number
  limit_bytes: number | null
  provider: string
  resolved: boolean
}

export interface UploadTicket {
  file_id: string
  upload_url: string
  method: string
  headers: Record<string, string>
  expires_in: number
}

export interface DownloadTicket {
  url: string
  expires_in: number
}

export function fetchFiles(options: RequestOptions): Promise<FileList> {
  return request<FileList>('/api/v1/files', options)
}

export function requestUpload(
  options: RequestOptions & {
    name: string
    sizeBytes: number
    contentType: string
  },
): Promise<UploadTicket> {
  return request<UploadTicket>('/api/v1/files/uploads', options, {
    method: 'POST',
    body: {
      name: options.name,
      size_bytes: options.sizeBytes,
      content_type: options.contentType,
    },
  })
}

export function completeUpload(
  options: RequestOptions & { fileId: string; checksumSha256?: string | null },
): Promise<FileRow> {
  return request<FileRow>(`/api/v1/files/${encodeURIComponent(options.fileId)}/complete`, options, {
    method: 'POST',
    body: { checksum_sha256: options.checksumSha256 ?? null },
  })
}

export function fetchDownloadUrl(
  options: RequestOptions & { fileId: string },
): Promise<DownloadTicket> {
  return request<DownloadTicket>(
    `/api/v1/files/${encodeURIComponent(options.fileId)}/download`,
    options,
  )
}

export function deleteFile(options: RequestOptions & { fileId: string }): Promise<void> {
  return request<void>(`/api/v1/files/${encodeURIComponent(options.fileId)}`, options, {
    method: 'DELETE',
    empty: true,
  })
}

/* -------------------------------------------------------------------------- */
/* The assistant                                                              */
/* -------------------------------------------------------------------------- */

/**
 * The assistant's surface of this product's own API.
 *
 * Scoped by the token like everything else: there is no tenant, organization
 * or user to name in any call, and a conversation or action id from another
 * tenant is a 404 because the row is invisible to this caller's session
 * before any code runs. A refusal carries a `code` on the `ApiError`, and the
 * page turns it into a sentence.
 */
export interface AiStatus {
  enabled: boolean
  tools_enabled: boolean
  requests_this_month: number
  monthly_limit: number | null
  resolved: boolean
  agents: string[]
  /** Pay as you go beyond the allowance: on, past it this month, charged so far. */
  overage_enabled: boolean
  over_allowance: boolean
  billable_this_month_micros: number
  overage_cap_micros: number | null
}

export interface AiConversation {
  id: string
  title: string
  agent_id: string
  context_type: string | null
  context_id: string | null
  created_at: string
  updated_at: string
}

export interface AiMessage {
  id: string
  role: string
  content: string
  tool_name: string | null
  created_at: string
  /** The passages a document search returned, on the answer that used them. */
  citations: {
    file_id: string
    title: string
    snippet: string
    score: number
  }[]
}

export interface AiAction {
  id: string
  conversation_id: string
  tool_id: string
  /** What it will do, in words, while it waits: "Delete the file x (46 KB, ...)". */
  summary: { title: string; detail: string } | null
  operation: string
  status: string
  input: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string | null
  proposed_by: string
  decided_by: string | null
  created_at: string
  decided_at: string | null
}

export interface AiConversationDetail {
  conversation: AiConversation
  messages: AiMessage[]
  pending: AiAction[]
}

export interface AiUsage {
  input: number
  output: number
  total: number
}

/** One thing the assistant did, or was refused, in this organization. No content. */
export interface AiAuditEvent {
  id: string
  actor_id: string
  action: string
  target_type: string
  target_id: string
  outcome: string
  details: Record<string, unknown>
  at: string
}

export interface AiAuditList {
  events: AiAuditEvent[]
}

export interface AiTurn {
  conversation: AiConversation
  messages: AiMessage[]
  pending: AiAction[]
  usage: AiUsage
}

/** A model call can take a while; the default timeout is for pages, not for this. */
const AI_TIMEOUT_MS = 90_000

export function fetchAiStatus(options: RequestOptions): Promise<AiStatus> {
  return request<AiStatus>('/api/v1/ai/status', options)
}

/** The assistant's recent activity, for those who may approve. 403 for anyone else. */
export function fetchAiAudit(options: RequestOptions, limit = 30): Promise<AiAuditList> {
  return request<AiAuditList>(`/api/v1/ai/audit?limit=${limit}`, options)
}

export function fetchAiConversations(
  options: RequestOptions,
): Promise<{ conversations: AiConversation[] }> {
  return request<{ conversations: AiConversation[] }>('/api/v1/ai/conversations', options)
}

export function startAiConversation(
  options: RequestOptions & {
    title?: string
    agentId?: string
    contextType?: string
    contextId?: string
  },
): Promise<AiConversation> {
  return request<AiConversation>('/api/v1/ai/conversations', options, {
    method: 'POST',
    body: {
      ...(options.title !== undefined ? { title: options.title } : {}),
      ...(options.agentId !== undefined ? { agent_id: options.agentId } : {}),
      ...(options.contextType !== undefined ? { context_type: options.contextType } : {}),
      ...(options.contextId !== undefined ? { context_id: options.contextId } : {}),
    },
  })
}

export function fetchAiConversation(
  options: RequestOptions & { conversationId: string },
): Promise<AiConversationDetail> {
  return request<AiConversationDetail>(
    `/api/v1/ai/conversations/${encodeURIComponent(options.conversationId)}`,
    options,
  )
}

export function sendAiMessage(
  options: RequestOptions & { conversationId: string; text: string },
): Promise<AiTurn> {
  return request<AiTurn>(
    `/api/v1/ai/conversations/${encodeURIComponent(options.conversationId)}/messages`,
    { timeoutMs: AI_TIMEOUT_MS, ...options },
    { method: 'POST', body: { text: options.text } },
  )
}

export function approveAiAction(options: RequestOptions & { actionId: string }): Promise<AiAction> {
  return request<AiAction>(
    `/api/v1/ai/actions/${encodeURIComponent(options.actionId)}/approve`,
    { timeoutMs: AI_TIMEOUT_MS, ...options },
    { method: 'POST' },
  )
}

export function rejectAiAction(options: RequestOptions & { actionId: string }): Promise<AiAction> {
  return request<AiAction>(
    `/api/v1/ai/actions/${encodeURIComponent(options.actionId)}/reject`,
    options,
    { method: 'POST' },
  )
}

/** One event of a streamed turn, in the order the API tells them. */
export type AiStreamEvent =
  | { type: 'delta'; text: string }
  | { type: 'message'; message: AiMessage }
  | { type: 'pending'; actions: AiAction[] }
  | { type: 'done'; turn: AiTurn }
  | { type: 'error'; status: number; code: string | null; message: string }

/**
 * The streamed form of `sendAiMessage`.
 *
 * Resolves once the API has accepted the turn, with a response whose body is
 * server-sent events; read it with `readAiStream`. A refusal before the
 * stream begins is an `ApiError`, as it is for the whole-answer call. No
 * timeout here: the body is read for as long as the model talks, and the
 * API bounds that on its side.
 */
export async function streamAiMessage(
  options: RequestOptions & { conversationId: string; text: string },
): Promise<Response> {
  const base = options.baseUrl.replace(/\/$/, '')
  if (!base) throw new ApiError('no API base URL is configured', 0)
  const path = `/api/v1/ai/conversations/${encodeURIComponent(options.conversationId)}/messages/stream`
  const response = await (options.fetchImpl ?? fetch)(`${base}${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${options.token}`,
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ text: options.text }),
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new ApiError(
      `${path} answered ${response.status}`,
      response.status,
      await errorCode(response),
    )
  }
  return response
}

/**
 * Read a stream of turn events to the end, handing each to `onEvent`.
 *
 * Frames are `event:` and `data:` lines ended by a blank line, as the API
 * writes them. A frame that is not one of the five events, or whose data is
 * not JSON, is skipped rather than ending the read: the `done` or `error`
 * frame that follows is what the caller is waiting for.
 */
export async function readAiStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: AiStreamEvent) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const event = parseStreamFrame(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      if (event !== null) onEvent(event)
      boundary = buffer.indexOf('\n\n')
    }
    if (done) break
  }
}

export function parseStreamFrame(frame: string): AiStreamEvent | null {
  let name = ''
  const data: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  if (name === '' || data.length === 0) return null
  let payload: unknown
  try {
    payload = JSON.parse(data.join('\n'))
  } catch {
    return null
  }
  if (payload === null || typeof payload !== 'object') return null
  switch (name) {
    case 'delta': {
      const text = (payload as { text?: unknown }).text
      return { type: 'delta', text: typeof text === 'string' ? text : '' }
    }
    case 'message':
      return { type: 'message', message: payload as AiMessage }
    case 'pending':
      return {
        type: 'pending',
        actions: Array.isArray(payload) ? (payload as AiAction[]) : [],
      }
    case 'done':
      return { type: 'done', turn: payload as AiTurn }
    case 'error': {
      const refusal = payload as {
        status?: unknown
        code?: unknown
        message?: unknown
      }
      return {
        type: 'error',
        status: typeof refusal.status === 'number' ? refusal.status : 500,
        code: typeof refusal.code === 'string' ? refusal.code : null,
        message: typeof refusal.message === 'string' ? refusal.message : '',
      }
    }
    default:
      return null
  }
}

/* -------------------------------------------------------------------------- */
/* Reporting                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * The reports router's answers, as the API declares them.
 *
 * The same shapes `packages/ui` renders; declared twice so neither package
 * depends on the other, the way the AI types are. Every call takes no tenant
 * and no organization: the API resolves both from the token.
 */
export interface ReportSummary {
  key: string
  name: string
  description: string
  category: string
  visibility: 'available' | 'locked' | 'hidden'
  entitlement: string | null
  default_visualization: 'kpi' | 'line' | 'bar' | 'table'
  sensitive: boolean
  order: number
}

export interface ReportList {
  reports: ReportSummary[]
  resolved: boolean
  plan: string | null
}

export interface ReportFilter {
  key: string
  kind: 'date_range' | 'choice' | 'integer'
  label: string
  options: string[]
  default: string | number | null
  minimum: number | null
  maximum: number | null
}

export interface ReportView extends ReportSummary {
  metrics: string[]
  dimensions: string[]
  filters: ReportFilter[]
  visualizations: ('kpi' | 'line' | 'bar' | 'table')[]
  export_formats: string[]
  can_export: boolean
  can_schedule: boolean
  cache_seconds: number
  status: string
  version: number
}

export type ExportFormat = 'csv' | 'xlsx' | 'pdf'
export type ScheduleCadence = 'daily' | 'weekly' | 'monthly'

export interface ReportSchedule {
  id: string
  report_key: string
  cadence: ScheduleCadence
  format: ExportFormat
  recipients: string[]
  filters: Record<string, string>
  active: boolean
  next_run_at: string
  last_run_at: string | null
  last_error: string | null
  created_by: string
  created_at: string
}

export interface ReportExport {
  id: string
  report_key: string
  format: ExportFormat
  status: 'pending' | 'ready' | 'failed'
  filename: string
  rows: number
  size_bytes: number | null
  error: string | null
  requested_by: string
  created_at: string
  ready_at: string | null
}

export interface ReportExportList {
  exports: ReportExport[]
  retention_days: number
}

/** What the export route answers when the file is written after the response. */
export interface ExportQueued {
  export_id: string
  rows: number
  format: ExportFormat
}

export interface ReportMetric {
  key: string
  label: string
  value: number | null
  unit: 'count' | 'bytes' | 'micros' | 'milliseconds' | 'seconds' | 'percent'
  format: 'integer' | 'decimal' | 'bytes' | 'money' | 'duration' | 'percent'
  kind: 'actual' | 'estimated' | 'derived' | 'unavailable'
  limit: number | null
  previous: number | null
  note: string | null
}

export interface ReportSeries {
  key: string
  label: string
  unit: ReportMetric['unit']
  format: ReportMetric['format']
  points: { x: string; y: number | null }[]
  kind: ReportMetric['kind']
}

export interface ReportTable {
  columns: { key: string; label: string; format: ReportMetric['format'] | null; align: 'left' | 'right' }[]
  rows: Record<string, string | number | null>[]
  truncated: boolean
}

export interface ReportData {
  key: string
  generated_at: string
  range: { start: string; end: string; bucket: 'day' | 'week' | 'month' } | null
  metrics: ReportMetric[]
  series: ReportSeries[]
  table: ReportTable | null
  notes: string[]
  visualization: 'kpi' | 'line' | 'bar' | 'table'
  resolved: boolean
}

export interface MetricDefinition {
  key: string
  name: string
  description: string
  unit: string
  format: string
  aggregation: string
  dimensions: string[]
}

/** The filters a page carries in its URL, as the API receives them. */
export type ReportQuery = Readonly<Record<string, string>>

function reportPath(key: string, suffix = ''): string {
  return `/api/v1/reports/${encodeURIComponent(key)}${suffix}`
}

function withQuery(path: string, query: ReportQuery): string {
  const params = new URLSearchParams()
  for (const [name, value] of Object.entries(query)) {
    if (value !== '') params.set(name, value)
  }
  const encoded = params.toString()
  return encoded === '' ? path : `${path}?${encoded}`
}

export function fetchReports(options: RequestOptions): Promise<ReportList> {
  return request<ReportList>('/api/v1/reports', options)
}

export function fetchReport(options: RequestOptions & { key: string }): Promise<ReportView> {
  return request<ReportView>(reportPath(options.key), options)
}

export function fetchReportData(
  options: RequestOptions & { key: string; query?: ReportQuery },
): Promise<ReportData> {
  return request<ReportData>(withQuery(reportPath(options.key, '/data'), options.query ?? {}), options)
}

export function fetchMetrics(options: RequestOptions): Promise<{ metrics: MetricDefinition[] }> {
  return request<{ metrics: MetricDefinition[] }>('/api/v1/metrics', options)
}

/**
 * A report as a file, as the raw response.
 *
 * Not through `request`, which parses JSON: the body is the file, streamed
 * on to the browser by the route handler that called this. A 202 is not a
 * file: the API is writing it after the response, and the body names the
 * export to look for in the list. A refusal is an `ApiError` with the
 * status the API gave -- 402 for a plan without export, 403 for a caller
 * without the permission -- so the handler can say which.
 */
export async function exportReport(
  options: RequestOptions & {
    key: string
    query?: ReportQuery
    format?: ExportFormat
    background?: boolean
  },
): Promise<Response> {
  const base = options.baseUrl.replace(/\/$/, '')
  if (!base) throw new ApiError('no API base URL is configured', 0)
  const query: Record<string, string> = { ...(options.query ?? {}) }
  if (options.format) query.format = options.format
  if (options.background) query.background = '1'
  const path = withQuery(reportPath(options.key, '/export'), query)
  const response = await (options.fetchImpl ?? fetch)(`${base}${path}`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${options.token}`, Accept: '*/*' },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new ApiError(`${path} answered ${response.status}`, response.status, await errorCode(response))
  }
  return response
}

export function fetchReportSchedules(
  options: RequestOptions & { key: string },
): Promise<{ schedules: ReportSchedule[] }> {
  return request<{ schedules: ReportSchedule[] }>(reportPath(options.key, '/schedules'), options)
}

export function createReportSchedule(
  options: RequestOptions & {
    key: string
    cadence: ScheduleCadence
    format: ExportFormat
    recipients: string[]
    filters?: Record<string, string>
  },
): Promise<ReportSchedule> {
  return request<ReportSchedule>(reportPath(options.key, '/schedules'), options, {
    method: 'POST',
    body: {
      cadence: options.cadence,
      format: options.format,
      recipients: options.recipients,
      filters: options.filters ?? {},
    },
  })
}

export function deleteReportSchedule(
  options: RequestOptions & { scheduleId: string },
): Promise<void> {
  return request<void>(`/api/v1/reports/schedules/${encodeURIComponent(options.scheduleId)}`, options, {
    method: 'DELETE',
    empty: true,
  })
}

export function fetchReportExports(options: RequestOptions): Promise<ReportExportList> {
  return request<ReportExportList>('/api/v1/reports/exports', options)
}

export function fetchExportDownload(
  options: RequestOptions & { exportId: string },
): Promise<{ url: string; expires_in: number }> {
  return request<{ url: string; expires_in: number }>(
    `/api/v1/reports/exports/${encodeURIComponent(options.exportId)}/download`,
    options,
  )
}

/* -------------------------------------------------------------------------- */
/* The platform's images                                                      */
/* -------------------------------------------------------------------------- */

/**
 * One of the platform's images, fetched on a signed-in caller's behalf.
 *
 * The one call here that is not JSON, and in this file for the same reason
 * the JSON ones are: one place that knows how such a fetch is made, how long
 * it may take, and what it refuses, so that the route serving the image holds
 * none of those opinions itself. (Not a sibling module: this package is read
 * from source by the web application's bundler and from `dist/` by its own
 * tests, and a relative import spelled for one is unresolvable by the other.)
 *
 * The URL arrives from the Control Plane's branding answer, already through
 * `isPlatformAssetUrl` in the branding package. This is the second gate, at
 * fetch time, and it repeats the host rules rather than trusting that the
 * first one ran: `https`; no credentials in the URL; not `localhost`, `.local`
 * or `.internal`; and not a raw IPv4 or IPv6 literal, because an address is
 * how a server gets pointed at something it can reach and a browser cannot.
 * Then no redirects, because a redirect is a second URL nobody validated; a
 * size cap, because a logo is not a way to fill a serverless function's
 * memory; and an allowlist of image types, because what is served from this
 * product's origin is trusted by every browser policy this product sets, and
 * an `https` URL a customer typed into a form is not.
 *
 * The rules are stated twice on purpose. `api-client` is a leaf and cannot
 * import `branding`, so the predicate cannot be shared; and a gate that
 * delegates to a caller having checked is not a gate. `platformAssetHostAllowed`
 * below and `isPlatformAssetUrl` there are asserted to agree in
 * `assets.test.ts`.
 *
 * **What this does not stop, stated rather than implied.** A name is resolved
 * by the runtime after this check, so `https://logos.example.com` whose DNS
 * answers 10.0.0.5 passes it. Closing that means resolving the host here,
 * refusing every loopback, RFC1918, link-local and unique-local answer, and
 * connecting to the address rather than the name so the two cannot differ --
 * which needs the socket, not `fetch`. It is not done here, and what stands in
 * front of it is that the platform stores only assets on its own storage, the
 * response must be an image under two megabytes, and no redirect is followed.
 * FOLLOW_UPS F19 carries it as the open box.
 *
 * Decided 2026-09-15 (FOLLOW_UPS F19). `docs/PRODUCT_FRONTEND.md` has the
 * alternative that was not taken and why.
 */

/** A logo is small. Two megabytes is generous for one and hostile to nothing. */
export const PLATFORM_ASSET_MAX_BYTES = 2 * 1024 * 1024

/**
 * Whether this is a host a product will fetch a customer's logo from.
 *
 * The same rules as `isPlatformAssetUrl` in the branding package, which cannot
 * be imported here: `api-client` is a leaf and gains no workspace dependency
 * for one predicate. `assets.test.ts` asserts the two agree on a shared table
 * of cases, so a rule added to one and not the other fails rather than
 * quietly leaving this side open.
 *
 * A name that resolves to a private address still passes; see the note on
 * `fetchPlatformAsset`.
 */
export function platformAssetHostAllowed(url: URL): boolean {
  if (url.username !== '' || url.password !== '') return false
  const host = url.hostname.toLowerCase().replace(/\.$/, '')
  if (host === '' || host === 'localhost' || host.endsWith('.localhost')) return false
  if (host.endsWith('.local') || host.endsWith('.internal')) return false
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.startsWith('[')) return false
  return true
}

/** The same ceiling every JSON call has: a hung fetch is a hung image. */
export const PLATFORM_ASSET_TIMEOUT_MS = 5_000

/**
 * What may be served from this origin as a branding image.
 *
 * SVG is on the list because most logos are SVG, and it is the one entry that
 * is a document rather than a bitmap. It is served with `nosniff` and inline,
 * the middleware's Content-Security-Policy applies to the response, and an
 * `<img>` never runs a document's script in any case -- so the residual is a
 * person navigating to the route directly, in their own product's origin,
 * to an image their own organization's administrator set.
 */
export const PLATFORM_ASSET_TYPES = [
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/avif',
  'image/svg+xml',
  'image/x-icon',
  'image/vnd.microsoft.icon',
] as const

export type PlatformAssetRefusal =
  | 'not-https'
  // A host this product will not fetch from: a raw address, a private suffix,
  // or credentials in the URL. Separate from `not-https` so a refusal says
  // which rule stood between a customer and their logo.
  | 'not-allowed'
  | 'redirect'
  | 'upstream-status'
  | 'content-type'
  | 'too-large'
  | 'timeout'
  | 'network'

export class PlatformAssetError extends Error {
  constructor(
    readonly reason: PlatformAssetRefusal,
    detail: string,
  ) {
    super(`${reason}: ${detail}`)
    this.name = 'PlatformAssetError'
  }
}

export interface PlatformAssetOptions {
  timeoutMs?: number
  maxBytes?: number
  /** The browser's `If-None-Match`, forwarded so an unchanged logo costs nothing. */
  ifNoneMatch?: string
  /** Injectable for tests. Defaults to the global. */
  fetchImpl?: typeof fetch
}

export type PlatformAssetResult =
  | { status: 'ok'; body: ArrayBuffer; contentType: string; etag?: string }
  | { status: 'unchanged'; etag?: string }

export async function fetchPlatformAsset(
  url: string,
  options: PlatformAssetOptions = {},
): Promise<PlatformAssetResult> {
  let target: URL
  try {
    target = new URL(url)
  } catch {
    throw new PlatformAssetError('not-https', 'not a URL')
  }
  if (target.protocol !== 'https:') {
    throw new PlatformAssetError('not-https', `refusing ${target.protocol}`)
  }
  if (!platformAssetHostAllowed(target)) {
    throw new PlatformAssetError('not-allowed', `refusing host ${target.hostname}`)
  }

  const maxBytes = options.maxBytes ?? PLATFORM_ASSET_MAX_BYTES
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? PLATFORM_ASSET_TIMEOUT_MS)

  try {
    let response: Response
    try {
      response = await (options.fetchImpl ?? fetch)(target.toString(), {
        method: 'GET',
        headers: {
          Accept: 'image/*',
          ...(options.ifNoneMatch ? { 'If-None-Match': options.ifNoneMatch } : {}),
        },
        // A redirect is a URL nobody validated. `manual` makes it a status this
        // function sees rather than a request it makes.
        redirect: 'manual',
        // The route serving this sets its own `Cache-Control`; nothing between
        // the platform's storage and here may hold a customer's image for
        // another caller.
        cache: 'no-store',
        signal: controller.signal,
      })
    } catch (error) {
      if (controller.signal.aborted) {
        throw new PlatformAssetError('timeout', `no answer within the time allowed`)
      }
      throw new PlatformAssetError('network', error instanceof Error ? error.message : String(error))
    }

    const etag = response.headers.get('etag') ?? undefined
    if (response.status === 304) return { status: 'unchanged', ...(etag ? { etag } : {}) }
    if (response.status >= 300 && response.status < 400) {
      throw new PlatformAssetError('redirect', `answered ${response.status}`)
    }
    if (!response.ok) {
      throw new PlatformAssetError('upstream-status', `answered ${response.status}`)
    }

    const contentType = (response.headers.get('content-type') ?? '').split(';')[0]?.trim().toLowerCase() ?? ''
    if (!(PLATFORM_ASSET_TYPES as readonly string[]).includes(contentType)) {
      throw new PlatformAssetError('content-type', `refusing ${contentType || 'no content type'}`)
    }

    // Declared length first, so an honest oversize answer costs no read at
    // all. A missing or dishonest header is caught by counting below.
    const declared = Number(response.headers.get('content-length') ?? '')
    if (Number.isFinite(declared) && declared > maxBytes) {
      throw new PlatformAssetError('too-large', `${String(declared)} bytes declared`)
    }

    const body = await readUpTo(response, maxBytes)
    return { status: 'ok', body, contentType, ...(etag ? { etag } : {}) }
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Read a body into memory, and stop the moment it passes the cap.
 *
 * Buffered rather than streamed through to the browser, on purpose. A stream
 * that hits the cap halfway has already sent a 200 and a content type, and
 * what the browser gets is a truncated image with no way to say why. The cap
 * is small enough that holding the whole image is cheaper than explaining a
 * half of one, and it makes "too large" a clean 502 instead.
 */
async function readUpTo(response: Response, maxBytes: number): Promise<ArrayBuffer> {
  const reader = response.body?.getReader()
  if (!reader) return new ArrayBuffer(0)

  const chunks: Uint8Array[] = []
  let total = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    total += value.byteLength
    if (total > maxBytes) {
      await reader.cancel()
      throw new PlatformAssetError('too-large', `more than ${String(maxBytes)} bytes`)
    }
    chunks.push(value)
  }

  const buffer = new ArrayBuffer(total)
  const view = new Uint8Array(buffer)
  let offset = 0
  for (const chunk of chunks) {
    view.set(chunk, offset)
    offset += chunk.byteLength
  }
  return buffer
}

// -- audit ---------------------------------------------------------------------

export interface AuditRow {
  id: string
  action: string
  actor_id: string
  target_type: string
  target_id: string
  outcome: string
  classification: string
  details: Record<string, unknown>
  created_at: string
}

export interface AuditPage {
  events: AuditRow[]
  /** Pass back as `before` to continue. Absent when the page was not full. */
  cursor: string | null
  /** Which classes this caller was allowed to see, so a thin page is explicable. */
  classifications: string[]
}

export interface AuditExportRow {
  id: string
  format: string
  status: string
  rows_exported: number
  size_bytes: number | null
  error: string | null
  expires_at: string | null
  created_at: string
  ready_at: string | null
}

export interface AuditExportList {
  exports: AuditExportRow[]
}

export interface AuditFilters {
  action?: string
  actorId?: string
  outcome?: string
  classification?: string
  since?: string
  before?: string
  limit?: number
}

function auditQuery(filters: AuditFilters): string {
  const search = new URLSearchParams()
  if (filters.action) search.set('action', filters.action)
  if (filters.actorId) search.set('actor_id', filters.actorId)
  if (filters.outcome) search.set('outcome', filters.outcome)
  if (filters.classification) search.set('classification', filters.classification)
  if (filters.since) search.set('since', filters.since)
  if (filters.before) search.set('before', filters.before)
  if (filters.limit) search.set('limit', String(filters.limit))
  const query = search.toString()
  return query ? `?${query}` : ''
}

export function searchAudit(options: RequestOptions & AuditFilters): Promise<AuditPage> {
  return request<AuditPage>(`/api/v1/audit${auditQuery(options)}`, options)
}

export function fetchAuditExports(options: RequestOptions): Promise<AuditExportList> {
  return request<AuditExportList>('/api/v1/audit/exports', options)
}

export function createAuditExport(
  options: RequestOptions & AuditFilters & { format: string },
): Promise<AuditExportRow> {
  return request<AuditExportRow>('/api/v1/audit/exports', options, {
    method: 'POST',
    body: {
      format: options.format,
      action: options.action ?? null,
      actor_id: options.actorId ?? null,
      outcome: options.outcome ?? null,
      classification: options.classification ?? null,
      since: options.since ?? null,
      before: options.before ?? null,
    },
  })
}

export function fetchAuditExportUrl(
  options: RequestOptions & { exportId: string },
): Promise<DownloadTicket> {
  return request<DownloadTicket>(
    `/api/v1/audit/exports/${encodeURIComponent(options.exportId)}/download`,
    options,
  )
}
