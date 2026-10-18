/**
 * Typed client for every REST and SSE endpoint in SPEC §7.14.
 *
 * Behavior:
 *     Every network call in the UI goes through this module. With
 *     `VITE_PAM_MOCK=1` the same functions are served by `./mocks`; otherwise
 *     they call `/api/*` on the current origin (the Vite proxy or nginx).
 */
import { EventStreamContentType, fetchEventSource } from '@microsoft/fetch-event-source'
import type {
  AgentManifest,
  ChatEvent,
  ChatRequest,
  Connector,
  ConnectorResult,
  ContextBundle,
  ContextRequest,
  GraphData,
  JobStatus,
  ModelEntry,
  Persona,
  SearchQuery,
  SearchResponse,
  Source,
  SyncReport,
  WorkingMemory,
  WriteResult,
} from '../types/generated'

export const MOCK = import.meta.env.VITE_PAM_MOCK === '1'

const BASE = '/api'

/** `GET /health` response (inline shape in §7.14, not a schema contract). */
export interface Health {
  ok: boolean
  vault: string
  index_ok: boolean
}

/** Providers whose value the Settings page can set (CHG-0023). */
export type KeyProvider = 'anthropic' | 'openrouter' | 'ollama'

/** `GET /settings/keys` row: never the key itself, only whether it is set and its last 4 characters. */
export interface KeyStatus {
  provider: KeyProvider
  is_set: boolean
  last4: string | null
  source: 'settings' | 'env' | 'none'
  /** Only the Ollama base URL, which is not a secret. */
  value: string | null
}

/** `POST /models/check` row. */
export interface CheckResult {
  id: string
  ok: boolean
  latency_ms: number
  error?: string | null
}

/** `GET /vault/tree` response. */
export interface VaultTree {
  paths: string[]
}

/** `GET /vault/file` response. */
export interface VaultFile {
  path: string
  frontmatter: Record<string, unknown>
  body: string
}

/** `GET /agents/{name}` response. */
export interface AgentDetail {
  manifest: AgentManifest
  persona: Persona
}

/** `POST /agents` and `PUT /agents/{name}` request body. */
export interface AgentUpsert {
  manifest: AgentManifest
  identity_custom: string
  rules_custom: string
  style_custom: string
}

/** Options for `POST /imports`. */
export interface ImportOptions {
  source?: Source
  agent?: string
}

/**
 * Error raised for any non-2xx response, carrying the §7.14 error body.
 *
 * Behavior:
 *     `code` and `message` come from `{"error": {"code", "message"}}`. A body in
 *     another shape keeps the HTTP status with code `HTTP_<status>`.
 * Parameters:
 *     status: HTTP status, or 0 for network failures.
 *     code: Machine-readable error code from the backend.
 *     message: Human-readable message.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

const CHAT_EVENT_TYPES = new Set(['context', 'token', 'tool_call', 'done', 'error'])

type Method = 'GET' | 'POST' | 'PUT'
type Query = Record<string, string | number | boolean | undefined | null>

function withQuery(path: string, query?: Query): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = `HTTP_${response.status}`
  let message = response.statusText || 'Request failed'
  try {
    const payload = (await response.json()) as { error?: { code?: unknown; message?: unknown } }
    if (typeof payload.error?.code === 'string') code = payload.error.code
    if (typeof payload.error?.message === 'string') message = payload.error.message
  } catch {
    // Non-JSON error body: keep the status-based fallback.
  }
  return new ApiError(response.status, code, message)
}

async function request<T>(method: Method, path: string, body?: unknown, query?: Query): Promise<T> {
  const url = withQuery(path, query)
  if (MOCK) {
    const { mockRequest } = await import('./mocks')
    return (await mockRequest(method, url, body)) as T
  }
  const init: RequestInit = { method, headers: { accept: 'application/json' } }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { ...init.headers, 'content-type': 'application/json' }
  }
  let response: Response
  try {
    response = await fetch(`${BASE}${url}`, init)
  } catch (err) {
    throw new ApiError(0, 'NETWORK', err instanceof Error ? err.message : 'Network error')
  }
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

const enc = encodeURIComponent

export const api = {
  health: () => request<Health>('GET', '/health'),

  createImport(file: File, options: ImportOptions = {}) {
    const form = new FormData()
    form.append('file', file)
    if (options.source) form.append('source', options.source)
    if (options.agent) form.append('agent', options.agent)
    return request<JobStatus>('POST', '/imports', form)
  },
  getImport: (jobId: string) => request<JobStatus>('GET', `/imports/${enc(jobId)}`),

  vaultTree: (agent?: string) => request<VaultTree>('GET', '/vault/tree', undefined, { agent }),
  vaultFile: (path: string, agent?: string) =>
    request<VaultFile>('GET', '/vault/file', undefined, { path, agent }),

  search: (query: SearchQuery) => request<SearchResponse>('POST', '/search', query),
  context: (req: ContextRequest) => request<ContextBundle>('POST', '/context', req),

  graph: (agent?: string, facts?: boolean) =>
    request<GraphData>('GET', '/graph', undefined, { agent, facts: facts ? 'true' : undefined }),

  listAgents: () => request<AgentManifest[]>('GET', '/agents'),
  getAgent: (name: string) => request<AgentDetail>('GET', `/agents/${enc(name)}`),
  createAgent: (body: AgentUpsert) => request<AgentManifest>('POST', '/agents', body),
  updateAgent: (name: string, body: AgentUpsert) =>
    request<AgentManifest>('PUT', `/agents/${enc(name)}`, body),

  models: () => request<ModelEntry[]>('GET', '/models'),
  saveModels: (models: ModelEntry[]) => request<ModelEntry[]>('PUT', '/models', models),
  checkModels: (id?: string) => request<CheckResult[]>('POST', '/models/check', id ? { id } : {}),
  keyStatus: () => request<KeyStatus[]>('GET', '/settings/keys'),
  setKey: (provider: KeyProvider, value: string | null) =>
    request<KeyStatus>('PUT', '/settings/keys', { provider, value }),

  getSession: (id: string) => request<WorkingMemory>('GET', `/sessions/${enc(id)}`),
  endSession: (id: string) => request<WriteResult>('POST', `/sessions/${enc(id)}/end`),

  sync: () => request<SyncReport>('POST', '/sync'),
  syncStatus: () => request<SyncReport>('GET', '/sync/status'),

  listConnectors: (includeArchived = false) =>
    request<Connector[]>('GET', '/connectors', undefined, { include_archived: includeArchived ? 'true' : undefined }),
  getConnector: (id: string) => request<Connector>('GET', `/connectors/${enc(id)}`),
  saveConnector: (connector: Connector) => request<Connector>('PUT', `/connectors/${enc(connector.id)}`, connector),
  archiveConnector: (id: string) => request<Connector>('POST', `/connectors/${enc(id)}/archive`),
  callConnectorTool: (id: string, tool: string, args: Record<string, unknown>) =>
    request<ConnectorResult>('POST', `/connectors/${enc(id)}/tools/${enc(tool)}/call`, args),
}

/**
 * Stream one chat turn from `POST /chat` as typed `ChatEvent`s.
 *
 * Behavior:
 *     Parses each `event: <type>` frame and its JSON `data` into the
 *     `ChatEvent` union and passes it to `onEvent`. Frames with an unknown type
 *     are ignored. A non-2xx response (e.g. 400 for an unknown model) rejects with
 *     `ApiError` before any event. If the stream closes or fails without a `done`
 *     or `error` event, a synthetic retryable `ErrorEvent` is emitted, so callers
 *     always see exactly one terminal event. Never retries on its own.
 * Exceptions:
 *     ApiError: the server rejected the request before streaming.
 * Returns:
 *     A promise that resolves after the terminal event.
 * Parameters:
 *     req: The chat turn to run.
 *     onEvent: Called for each event in stream order.
 *     signal: Aborts the stream; no terminal event is emitted after an abort.
 */
export async function chatStream(
  req: ChatRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let terminal = false
  const emit = (event: ChatEvent) => {
    if (terminal) return
    if (event.type === 'done' || event.type === 'error') terminal = true
    onEvent(event)
  }
  const fail = (message: string) => emit({ type: 'error', message, retryable: true })

  if (MOCK) {
    const { mockChatStream } = await import('./mocks')
    await mockChatStream(req, emit, signal)
    if (!terminal && !signal?.aborted) fail('Stream ended without a done event')
    return
  }

  try {
    await fetchEventSource(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: EventStreamContentType },
      body: JSON.stringify(req),
      signal,
      openWhenHidden: true,
      async onopen(response) {
        const type = response.headers.get('content-type') ?? ''
        if (!response.ok || !type.startsWith(EventStreamContentType)) throw await toApiError(response)
      },
      onmessage(message) {
        const type = message.event || 'message'
        if (!CHAT_EVENT_TYPES.has(type) || !message.data) return
        const data = JSON.parse(message.data) as Record<string, unknown>
        emit({ ...data, type } as ChatEvent)
      },
      onerror(err) {
        throw err
      },
    })
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (!signal?.aborted) fail(err instanceof Error ? err.message : 'Stream failed')
    return
  }
  if (!terminal && !signal?.aborted) fail('Stream ended without a done event')
}
