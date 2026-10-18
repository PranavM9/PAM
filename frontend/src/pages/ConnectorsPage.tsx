import { Plug, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { ChoiceRow, Field, FormSection, choiceClass } from '../components/agents/FormParts'
import { PageHeader } from '../components/PageHeader'
import {
  blankConnector,
  saveConnectors,
  useConnectors,
  type Connector,
  type ConnectorAuth,
  type ConnectorParam,
  type ConnectorTool,
} from '../lib/connectors'

const blankTool = (): ConnectorTool => ({ name: '', description: '', method: 'GET', path: '', params: [] })
const blankParam = (): ConnectorParam => ({ name: '', type: 'string', required: false, description: '' })

function defaultAuth(type: ConnectorAuth['type']): ConnectorAuth {
  if (type === 'api_key') return { type, header: 'x-api-key', env_var: '' }
  if (type === 'bearer') return { type, env_var: '' }
  return { type: 'none' }
}

/**
 * Connectors page: define external services that agents can call as tools.
 *
 * Behavior:
 *     Lists the registered connectors beside an editor for one connector: name,
 *     base URL, auth (a secret is referenced by env var name, never typed in),
 *     and its tools with their parameters. Which agents may use a connector is
 *     chosen on the Agents page. The registry lives in browser storage for now;
 *     there is no backend route yet, so nothing here changes what the chat model
 *     can call.
 */
export default function ConnectorsPage() {
  const connectors = useConnectors()
  const [selectedId, setSelectedId] = useState<string | null>(connectors[0]?.id ?? null)
  const [draft, setDraft] = useState<Connector | null>(null)
  const current = draft ?? connectors.find((c) => c.id === selectedId) ?? null
  const isNew = draft !== null && !connectors.some((c) => c.id === draft.id)

  const edit = (patch: Partial<Connector>) => current && setDraft({ ...current, ...patch })
  const editTool = (i: number, patch: Partial<ConnectorTool>) =>
    current && edit({ tools: current.tools.map((t, j) => (j === i ? { ...t, ...patch } : t)) })
  const editParam = (i: number, k: number, patch: Partial<ConnectorParam>) =>
    current && editTool(i, { params: current.tools[i].params.map((p, j) => (j === k ? { ...p, ...patch } : p)) })

  const save = () => {
    if (!current) return
    saveConnectors(isNew ? [...connectors, current] : connectors.map((c) => (c.id === current.id ? current : c)))
    setSelectedId(current.id)
    setDraft(null)
  }
  const remove = () => {
    if (!current) return
    const rest = connectors.filter((c) => c.id !== current.id)
    saveConnectors(rest)
    setSelectedId(rest[0]?.id ?? null)
    setDraft(null)
  }
  const canSave = Boolean(current?.name.trim() && /^https?:\/\//.test(current.base_url) && current.tools.every((t) => t.name.trim() && t.path.startsWith('/')))

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto lg:flex-row lg:gap-4 lg:overflow-hidden">
      <aside className="panel flex shrink-0 flex-col gap-3 p-4 lg:min-h-0 lg:w-64 lg:overflow-y-auto" aria-label="Connectors">
        <button type="button" className="btn btn-primary" onClick={() => setDraft(blankConnector())}>
          <Plus size={16} strokeWidth={1.75} aria-hidden /> New connector
        </button>
        <ul className="space-y-1">
          {connectors.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => {
                  setDraft(null)
                  setSelectedId(c.id)
                }}
                className={`press flex w-full items-center gap-2 rounded-control px-3 py-2 text-left text-sm hover:bg-fg/[0.05] ${
                  current?.id === c.id ? 'bg-accent/[0.12]' : ''
                }`}
              >
                <span className={`h-2 w-2 shrink-0 rounded-full ${c.enabled ? 'bg-ok' : 'bg-muted/50'}`} aria-hidden />
                <span className="min-w-0 flex-1 truncate">{c.name || 'Untitled'}</span>
                <span className="text-xs tabular-nums text-muted">{c.tools.length}</span>
              </button>
            </li>
          ))}
          {connectors.length === 0 && <li className="px-3 py-2 text-sm text-muted">No connectors yet.</li>}
        </ul>
      </aside>

      <section className="flex min-w-0 shrink-0 flex-col lg:min-h-0 lg:flex-1 lg:shrink" aria-label="Connector editor">
        <PageHeader
          title="Connectors"
          subtitle="External APIs your agents can call as tools."
          actions={
            current && (
              <>
                <button type="button" className="btn" onClick={remove} disabled={isNew}>
                  <Trash2 size={16} strokeWidth={1.75} aria-hidden /> Delete
                </button>
                <button type="button" className="btn btn-primary px-5" onClick={save} disabled={!canSave || (!draft && !isNew)}>
                  Save
                </button>
              </>
            )
          }
        />
        {!current ? (
          <div className="panel flex flex-col items-center gap-4 px-6 py-16 text-center lg:flex-1 lg:justify-center">
            <span className="flex h-14 w-14 items-center justify-center rounded-full bg-accent/15 text-accent" aria-hidden>
              <Plug size={26} strokeWidth={1.75} />
            </span>
            <p className="text-[15px] font-medium text-fg">Add a connector to give agents new tools.</p>
          </div>
        ) : (
          <div className="panel p-5 sm:p-8 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
            <div className="divide-y divide-edge/10">
              <FormSection title="Service" description="What the connector is and where it lives.">
                <div className="grid gap-5 sm:grid-cols-2">
                  <Field label="Name">
                    <input className="input" value={current.name} onChange={(e) => edit({ name: e.target.value })} />
                  </Field>
                  <Field label="Base URL" hint="Must start with http:// or https://">
                    <input className="input font-mono" value={current.base_url} onChange={(e) => edit({ base_url: e.target.value })} placeholder="https://api.example.com/v1" />
                  </Field>
                  <div className="sm:col-span-2">
                    <Field label="Description" hint="Shown to the model so it knows when to use these tools.">
                      <input className="input" value={current.description} onChange={(e) => edit({ description: e.target.value })} />
                    </Field>
                  </div>
                </div>
                <ChoiceRow>
                  <input type="checkbox" className={choiceClass} checked={current.enabled} onChange={(e) => edit({ enabled: e.target.checked })} />
                  Enabled
                </ChoiceRow>
              </FormSection>

              <FormSection title="Authentication" description="Secrets are read from an environment variable on the server, never stored here.">
                <div className="grid gap-5 sm:grid-cols-3">
                  <Field label="Type">
                    <select className="input" value={current.auth.type} onChange={(e) => edit({ auth: defaultAuth(e.target.value as ConnectorAuth['type']) })}>
                      <option value="none">None</option>
                      <option value="api_key">API key header</option>
                      <option value="bearer">Bearer token</option>
                    </select>
                  </Field>
                  {current.auth.type === 'api_key' && (
                    <Field label="Header name">
                      <input className="input font-mono" value={current.auth.header} onChange={(e) => edit({ auth: { ...(current.auth as Extract<ConnectorAuth, { type: 'api_key' }>), header: e.target.value } })} />
                    </Field>
                  )}
                  {current.auth.type !== 'none' && (
                    <Field label="Env var holding the secret">
                      <input
                        className="input font-mono"
                        value={current.auth.env_var}
                        placeholder="MY_SERVICE_API_KEY"
                        onChange={(e) => edit({ auth: { ...current.auth, env_var: e.target.value } as ConnectorAuth })}
                      />
                    </Field>
                  )}
                </div>
              </FormSection>

              <FormSection title="Tools" description="Each tool is one HTTP request the model can make, with the parameters it must fill in.">
                {current.tools.map((t, i) => (
                  <div key={i} className="well space-y-4 p-4">
                    <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_6rem_minmax(0,1fr)_auto] sm:items-end">
                      <Field label="Tool name">
                        <input className="input font-mono" value={t.name} onChange={(e) => editTool(i, { name: e.target.value })} placeholder="search_products" />
                      </Field>
                      <Field label="Method">
                        <select className="input" value={t.method} onChange={(e) => editTool(i, { method: e.target.value as 'GET' | 'POST' })}>
                          <option>GET</option>
                          <option>POST</option>
                        </select>
                      </Field>
                      <Field label="Path" hint="Starts with /">
                        <input className="input font-mono" value={t.path} onChange={(e) => editTool(i, { path: e.target.value })} placeholder="/products/search" />
                      </Field>
                      <button type="button" className="icon-btn h-10 w-10" aria-label="Remove tool" onClick={() => edit({ tools: current.tools.filter((_, j) => j !== i) })}>
                        <Trash2 size={15} />
                      </button>
                    </div>
                    <Field label="Description">
                      <input className="input" value={t.description} onChange={(e) => editTool(i, { description: e.target.value })} />
                    </Field>
                    <div className="space-y-2">
                      <span className="label">Parameters</span>
                      {t.params.map((p, k) => (
                        <div key={k} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_7rem_auto_minmax(0,2fr)_auto] sm:items-center">
                          <input className="input font-mono" aria-label="Parameter name" value={p.name} onChange={(e) => editParam(i, k, { name: e.target.value })} placeholder="query" />
                          <select className="input" aria-label="Parameter type" value={p.type} onChange={(e) => editParam(i, k, { type: e.target.value as ConnectorParam['type'] })}>
                            <option>string</option>
                            <option>number</option>
                            <option>boolean</option>
                          </select>
                          <ChoiceRow>
                            <input type="checkbox" className={choiceClass} checked={p.required} onChange={(e) => editParam(i, k, { required: e.target.checked })} />
                            required
                          </ChoiceRow>
                          <input className="input" aria-label="Parameter description" value={p.description} onChange={(e) => editParam(i, k, { description: e.target.value })} placeholder="Description" />
                          <button type="button" className="icon-btn h-10 w-10" aria-label="Remove parameter" onClick={() => editTool(i, { params: t.params.filter((_, j) => j !== k) })}>
                            <Trash2 size={15} />
                          </button>
                        </div>
                      ))}
                      <button type="button" className="btn" onClick={() => editTool(i, { params: [...t.params, blankParam()] })}>
                        <Plus size={15} strokeWidth={1.75} aria-hidden /> Add parameter
                      </button>
                    </div>
                  </div>
                ))}
                <button type="button" className="btn" onClick={() => edit({ tools: [...current.tools, blankTool()] })}>
                  <Plus size={15} strokeWidth={1.75} aria-hidden /> Add tool
                </button>
              </FormSection>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
