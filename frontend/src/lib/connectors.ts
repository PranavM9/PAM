import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Connector, ConnectorAuth, ConnectorParam, ConnectorTool } from '../types/generated'

/** A connector with every optional contract field filled in, as the editor works with it. */
export interface EditableConnector {
  id: string
  name: string
  description: string
  base_url: string
  public_base_url: string | null
  auth: Required<ConnectorAuth>
  tools: EditableTool[]
  enabled: boolean
  archived: boolean
  agents: string[]
}

/** A connector tool with its optional fields filled in. */
export interface EditableTool {
  name: string
  description: string
  method: 'GET' | 'POST'
  path: string
  params: Required<ConnectorParam>[]
}

/** The §7.16 patterns, checked before a save so the user sees the problem next to the field. */
export const PATTERNS = {
  id: /^[a-z0-9][a-z0-9-]{0,39}$/,
  tool: /^[a-z][a-z0-9_]{0,22}$/,
  param: /^[a-z][a-z0-9_]{0,39}$/,
  path: /^\/[A-Za-z0-9_\-/{}.]*$/,
  baseUrl: /^https?:\/\/[^\s/]+(\/[^\s]*[^\s/])?$/,
}

/** `localStorage` key of the browser-only registry used before connectors moved to the vault. */
export const LEGACY_KEY = 'pam-connectors'

const CONNECTORS = ['connectors'] as const

/** Fill in every optional field of a connector from the API. */
export function editable(c: Connector): EditableConnector {
  return {
    id: c.id,
    name: c.name,
    description: c.description ?? '',
    base_url: c.base_url,
    public_base_url: c.public_base_url ?? null,
    auth: { type: c.auth?.type ?? 'none', header: c.auth?.header ?? null, env_var: c.auth?.env_var ?? null },
    tools: (c.tools ?? []).map((t) => ({
      name: t.name,
      description: t.description,
      method: t.method ?? 'GET',
      path: t.path,
      params: (t.params ?? []).map((p) => ({
        name: p.name,
        type: p.type ?? 'string',
        required: p.required ?? false,
        description: p.description ?? '',
      })),
    })),
    enabled: c.enabled ?? true,
    archived: c.archived ?? false,
    agents: c.agents ?? [],
  }
}

/** A blank connector for the "New connector" form. */
export function blankConnector(): EditableConnector {
  return {
    id: '', name: '', description: '', base_url: '', public_base_url: null,
    auth: { type: 'none', header: null, env_var: null }, tools: [], enabled: true, archived: false, agents: [],
  }
}

/** Turn a display name into a connector id (lowercase slug, at most 40 characters). */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
    .replace(/-+$/, '')
}

/**
 * Check a connector against the §7.16 rules before saving it.
 *
 * Returns:
 *     The first problem as a sentence, or `null` when the connector can be saved.
 * Parameters:
 *     c: The connector being edited.
 */
export function validateConnector(c: EditableConnector): string | null {
  if (!PATTERNS.id.test(c.id)) return 'ID: lowercase letters, digits and dashes, starting with a letter or digit.'
  if (!c.name.trim()) return 'Name is required.'
  if (!PATTERNS.baseUrl.test(c.base_url)) return 'Base URL: http:// or https://, with no trailing slash.'
  if (c.auth.type !== 'none' && !c.auth.env_var?.trim()) return 'Authentication: name the variable that holds the secret.'
  for (const t of c.tools) {
    if (!PATTERNS.tool.test(t.name)) return `Tool "${t.name || 'unnamed'}": the name must look like search_devices (at most 23 characters).`
    if (!t.description.trim()) return `Tool ${t.name}: a description is required.`
    if (!PATTERNS.path.test(t.path)) return `Tool ${t.name}: the path must start with /.`
    for (const p of t.params) {
      if (!PATTERNS.param.test(p.name)) return `Tool ${t.name}: parameter "${p.name || 'unnamed'}" must look like customer_id.`
    }
  }
  return null
}

/** Split a model-facing tool name `<connector_id>__<tool>`; `null` for any other tool (e.g. MCP). */
export function splitToolName(name: string): { connector: string; tool: string } | null {
  const i = name.indexOf('__')
  if (i <= 0 || i + 2 >= name.length) return null
  return { connector: name.slice(0, i), tool: name.slice(i + 2) }
}

/** List connectors from the vault; archived ones only when asked. */
export function useConnectors(includeArchived = false) {
  return useQuery({ queryKey: [...CONNECTORS, includeArchived], queryFn: () => api.listConnectors(includeArchived) })
}

/** Create or replace a connector (`PUT /connectors/{id}`); every connector list is refreshed afterwards. */
export function useSaveConnector() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (c: Connector) => api.saveConnector(c),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CONNECTORS }),
  })
}

/** Archive a connector (it is hidden and disabled, never deleted); every connector list is refreshed. */
export function useArchiveConnector() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.archiveConnector(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CONNECTORS }),
  })
}

/** Shape of a connector in the old browser-only registry. */
interface LegacyConnector {
  id: string
  name: string
  description?: string
  base_url: string
  auth?: { type: 'none' | 'api_key' | 'bearer'; header?: string; env_var?: string }
  tools?: ConnectorTool[]
  enabled?: boolean
  agents?: string[]
}

/**
 * Read the connectors still kept in this browser by the old registry.
 *
 * Behavior:
 *     Unavailable or corrupt storage counts as empty. Each entry is mapped to the
 *     §7.16 contract (`archived: false`, no `public_base_url`).
 * Returns:
 *     The connectors to move to the vault.
 */
export function legacyConnectors(): Connector[] {
  let raw: LegacyConnector[] = []
  try {
    const text = localStorage.getItem(LEGACY_KEY)
    raw = text ? (JSON.parse(text) as LegacyConnector[]) : []
  } catch {
    return []
  }
  if (!Array.isArray(raw)) return []
  return raw.map((c) => ({
    id: PATTERNS.id.test(c.id) ? c.id : slugify(c.name || c.id),
    name: c.name,
    description: c.description ?? '',
    base_url: c.base_url,
    public_base_url: null,
    auth: { type: c.auth?.type ?? 'none', header: c.auth?.header ?? null, env_var: c.auth?.env_var ?? null },
    tools: c.tools ?? [],
    enabled: c.enabled ?? true,
    archived: false,
    agents: c.agents ?? [],
  }))
}

/**
 * Move the browser-only connectors to the vault, one `PUT` each.
 *
 * Behavior:
 *     The `localStorage` key is cleared only when every connector was saved;
 *     otherwise it keeps just the ones that failed, so nothing is lost.
 * Returns:
 *     How many were moved, and one message per failure.
 */
export async function migrateLegacy(): Promise<{ moved: number; errors: string[] }> {
  const legacy = legacyConnectors()
  const failed: Connector[] = []
  const errors: string[] = []
  for (const c of legacy) {
    try {
      await api.saveConnector(c)
    } catch (err) {
      failed.push(c)
      errors.push(`${c.name || c.id}: ${err instanceof Error ? err.message : 'could not be saved'}`)
    }
  }
  try {
    if (failed.length === 0) localStorage.removeItem(LEGACY_KEY)
    else localStorage.setItem(LEGACY_KEY, JSON.stringify(failed))
  } catch {
    // Storage became unavailable: the moved connectors are in the vault anyway.
  }
  return { moved: legacy.length - failed.length, errors }
}
