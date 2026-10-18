import { useSyncExternalStore } from 'react'

/** How a connector authenticates; secrets are referenced by env var name, never stored. */
export type ConnectorAuth =
  | { type: 'none' }
  | { type: 'api_key'; header: string; env_var: string }
  | { type: 'bearer'; env_var: string }

/** One input parameter of a connector tool, shown to the model as a JSON-schema property. */
export interface ConnectorParam {
  name: string
  type: 'string' | 'number' | 'boolean'
  required: boolean
  description: string
}

/** One callable operation of a connector (an HTTP request the model can trigger). */
export interface ConnectorTool {
  name: string
  description: string
  method: 'GET' | 'POST'
  path: string
  params: ConnectorParam[]
}

/** An external service the agents can call as tools, e.g. a commerce API that returns product links. */
export interface Connector {
  id: string
  name: string
  description: string
  base_url: string
  auth: ConnectorAuth
  tools: ConnectorTool[]
  enabled: boolean
  /** Names of the agents that may use this connector. */
  agents: string[]
}

const STORE_KEY = 'pam-connectors'

const EXAMPLE: Connector = {
  id: 'channel3-commerce',
  name: 'Channel 3 Commerce',
  description: 'Looks up products on commerce sites and returns buy links.',
  base_url: 'https://api.example.com/v1',
  auth: { type: 'api_key', header: 'x-api-key', env_var: 'CHANNEL3_API_KEY' },
  tools: [
    {
      name: 'search_products',
      description: 'Search for products and return links to them.',
      method: 'GET',
      path: '/products/search',
      params: [
        { name: 'query', type: 'string', required: true, description: 'What the user wants to buy.' },
        { name: 'limit', type: 'number', required: false, description: 'Maximum number of links.' },
      ],
    },
  ],
  enabled: false,
  agents: [],
}

function load(): Connector[] {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (raw) return JSON.parse(raw) as Connector[]
  } catch {
    // Unavailable or corrupt storage: fall back to the seeded example.
  }
  return [EXAMPLE]
}

let state: Connector[] = load()
const listeners = new Set<() => void>()

/** Replace the registry, persist it to `localStorage` and notify subscribers. */
export function saveConnectors(next: Connector[]) {
  state = next
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(next))
  } catch {
    // The in-memory registry still applies when browser storage is unavailable.
  }
  listeners.forEach((l) => l())
}

/** Subscribe to the registry; returns the current connectors and re-renders on change. */
export function useConnectors(): Connector[] {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => state,
  )
}

/** A blank connector for the "New connector" form. */
export function blankConnector(): Connector {
  return { id: `c${Date.now().toString(36)}`, name: '', description: '', base_url: '', auth: { type: 'none' }, tools: [], enabled: true, agents: [] }
}

/** Add `agent` to or remove it from a connector's allowed agents. */
export function setConnectorAgent(id: string, agent: string, allowed: boolean) {
  saveConnectors(
    state.map((c) =>
      c.id !== id ? c : { ...c, agents: allowed ? [...new Set([...c.agents, agent])] : c.agents.filter((a) => a !== agent) },
    ),
  )
}
