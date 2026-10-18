import { useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, Loader2, Plug, Plus, Trash2, UploadCloud } from 'lucide-react'
import { useState } from 'react'
import { ChoiceRow, Field, FormSection, choiceClass } from '../components/agents/FormParts'
import { TestToolPanel } from '../components/connectors/TestToolPanel'
import { ErrorNote } from '../components/ErrorNote'
import { PageHeader } from '../components/PageHeader'
import {
  blankConnector,
  editable,
  legacyConnectors,
  migrateLegacy,
  slugify,
  useArchiveConnector,
  useConnectors,
  useSaveConnector,
  validateConnector,
  type EditableConnector,
  type EditableTool,
} from '../lib/connectors'

type Param = EditableTool['params'][number]
type AuthType = EditableConnector['auth']['type']

const blankTool = (): EditableTool => ({ name: '', description: '', method: 'GET', path: '', params: [] })
const blankParam = (): Param => ({ name: '', type: 'string', required: false, description: '' })

function authFor(type: AuthType, current: EditableConnector['auth']): EditableConnector['auth'] {
  if (type === 'api_key') return { type, header: current.header ?? 'x-api-key', env_var: current.env_var }
  if (type === 'bearer') return { type, header: null, env_var: current.env_var }
  return { type: 'none', header: null, env_var: null }
}

/**
 * Banner that moves connectors kept by the old browser-only registry into the vault.
 *
 * Behavior:
 *     Shown only while `localStorage` still holds connectors. "Move" PUTs each one,
 *     then clears the key (or keeps just the failures) and lists any errors.
 */
function MigrationBanner() {
  const queryClient = useQueryClient()
  const [legacy, setLegacy] = useState(() => legacyConnectors())
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  if (legacy.length === 0 && errors.length === 0) return null
  const move = async () => {
    setBusy(true)
    const result = await migrateLegacy()
    setBusy(false)
    setErrors(result.errors)
    setLegacy(legacyConnectors())
    await queryClient.invalidateQueries({ queryKey: ['connectors'] })
  }
  return (
    <div className="panel flex flex-col gap-3 border-accent/30 p-4 sm:flex-row sm:items-center" data-testid="migration-banner">
      <UploadCloud size={20} strokeWidth={1.75} className="shrink-0 text-accent" aria-hidden />
      <p className="min-w-0 flex-1 text-sm text-fg/90">
        {legacy.length > 0
          ? `This browser still holds ${legacy.length} connector${legacy.length === 1 ? '' : 's'} from before connectors were saved in the vault.`
          : 'Some connectors could not be moved:'}
        {errors.length > 0 && (
          <span className="mt-1 block text-xs text-bad">{errors.join(' · ')}</span>
        )}
      </p>
      {legacy.length > 0 && (
        <button type="button" className="btn btn-primary shrink-0" onClick={move} disabled={busy}>
          {busy && <Loader2 size={15} className="animate-spin" aria-hidden />}
          Move {legacy.length} connector{legacy.length === 1 ? '' : 's'} from this browser to the vault
        </button>
      )}
    </div>
  )
}

/**
 * Connectors page: define the outside services agents can call as tools (SPEC §8 M16, T18).
 *
 * Behavior:
 *     Lists the vault's connectors (archived ones behind "Show archived") beside an
 *     editor: ID, name, base URL, browser-visible base URL, auth (a secret is
 *     referenced by variable name, never typed in) and the tools with their
 *     parameters. Save PUTs the whole connector; Archive (confirmed) hides and
 *     disables it, and Restore brings it back, because nothing is deleted. A saved
 *     connector has a "Test tool" panel. Which agents may use a connector is
 *     chosen on the Agents page.
 */
export default function ConnectorsPage() {
  const list = useConnectors(true)
  const save = useSaveConnector()
  const archive = useArchiveConnector()
  const [showArchived, setShowArchived] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<EditableConnector | null>(null)
  const [creating, setCreating] = useState(false)
  const [idTouched, setIdTouched] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(false)

  const all = (list.data ?? []).map(editable)
  const visible = all.filter((c) => showArchived || !c.archived)
  const saved = all.find((c) => c.id === (selectedId ?? visible[0]?.id)) ?? null
  const current = draft ?? saved
  const isNew = creating && draft !== null
  const problem = current ? validateConnector(current) : null
  const idTaken = isNew && current !== null && all.some((c) => c.id === current.id)

  const select = (id: string | null) => {
    setDraft(null)
    setCreating(false)
    setSelectedId(id)
    setConfirmArchive(false)
    save.reset()
    archive.reset()
  }
  const edit = (patch: Partial<EditableConnector>) => current && setDraft({ ...current, ...patch })
  const editTool = (i: number, patch: Partial<EditableTool>) =>
    current && edit({ tools: current.tools.map((t, j) => (j === i ? { ...t, ...patch } : t)) })
  const editParam = (i: number, k: number, patch: Partial<Param>) =>
    current && editTool(i, { params: current.tools[i].params.map((p, j) => (j === k ? { ...p, ...patch } : p)) })

  const startNew = () => {
    select(null)
    setIdTouched(false)
    setCreating(true)
    setDraft(blankConnector())
  }
  const submit = () => {
    if (!current || problem || idTaken) return
    save.mutate(current, {
      onSuccess: (c) => {
        setDraft(null)
        setCreating(false)
        setSelectedId(c.id)
      },
    })
  }
  const doArchive = () => {
    if (!current) return
    if (!confirmArchive) return setConfirmArchive(true)
    archive.mutate(current.id, {
      onSuccess: () => {
        setConfirmArchive(false)
        setSelectedId(all.find((c) => c.id !== current.id && !c.archived)?.id ?? null)
      },
    })
  }
  const restore = () => current && save.mutate({ ...current, archived: false, enabled: true })

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto lg:overflow-hidden">
      <MigrationBanner />
      <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row lg:overflow-hidden">
        <aside className="panel flex shrink-0 flex-col gap-3 p-4 lg:min-h-0 lg:w-64 lg:overflow-y-auto" aria-label="Connectors">
          <button type="button" className="btn btn-primary" onClick={startNew}>
            <Plus size={16} strokeWidth={1.75} aria-hidden /> New connector
          </button>
          <ChoiceRow className="min-h-[2rem] text-xs text-muted">
            <input type="checkbox" className={choiceClass} checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
            Show archived
          </ChoiceRow>
          {list.isLoading && <p className="px-3 text-sm text-muted">Loading…</p>}
          <ErrorNote error={list.error} />
          <ul className="space-y-1" data-testid="connector-list">
            {visible.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => select(c.id)}
                  className={`press flex w-full items-center gap-2 rounded-control px-3 py-2 text-left text-sm hover:bg-fg/[0.05] ${
                    current?.id === c.id && !isNew ? 'bg-accent/[0.12]' : ''
                  } ${c.archived ? 'opacity-60' : ''}`}
                  data-connector={c.id}
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${c.enabled && !c.archived ? 'bg-ok' : 'bg-muted/50'}`} aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{c.name || c.id}</span>
                  {c.archived ? <span className="text-[11px] text-muted">archived</span> : <span className="text-xs tabular-nums text-muted">{c.tools.length}</span>}
                </button>
              </li>
            ))}
            {list.isSuccess && visible.length === 0 && <li className="px-3 py-2 text-sm text-muted">No connectors yet.</li>}
          </ul>
        </aside>

        <section className="flex min-w-0 shrink-0 flex-col lg:min-h-0 lg:flex-1 lg:shrink" aria-label="Connector editor">
          <PageHeader
            title="Connectors"
            subtitle="Outside APIs your agents can call as tools. Saved in the vault, one file per connector."
            actions={
              current && (
                <>
                  {!isNew && (current.archived ? (
                    <button type="button" className="btn" onClick={restore} disabled={save.isPending}>
                      <ArchiveRestore size={16} strokeWidth={1.75} aria-hidden /> Restore
                    </button>
                  ) : (
                    <button type="button" className="btn" onClick={doArchive} disabled={archive.isPending}>
                      <Archive size={16} strokeWidth={1.75} aria-hidden /> {confirmArchive ? 'Confirm archive' : 'Archive'}
                    </button>
                  ))}
                  <button
                    type="button"
                    className="btn btn-primary px-5"
                    onClick={submit}
                    disabled={!draft || Boolean(problem) || idTaken || save.isPending}
                  >
                    {save.isPending && <Loader2 size={15} className="animate-spin" aria-hidden />}
                    Save
                  </button>
                </>
              )
            }
          />
          {current && draft && (problem || idTaken) && (
            <p className="mb-3 text-xs text-warn" data-testid="connector-problem">{idTaken ? `ID ${current.id} is already used.` : problem}</p>
          )}
          {confirmArchive && (
            <p className="mb-3 text-xs text-muted">Archiving hides the connector and turns it off for every agent. The file stays in the vault and can be restored.</p>
          )}
          <div className="mb-3 space-y-2">
            <ErrorNote error={save.error} />
            <ErrorNote error={archive.error} />
          </div>
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
                      <input
                        className="input"
                        value={current.name}
                        onChange={(e) =>
                          edit(isNew && !idTouched ? { name: e.target.value, id: slugify(e.target.value) } : { name: e.target.value })
                        }
                      />
                    </Field>
                    <Field label="ID" hint={isNew ? 'Lowercase letters, digits and dashes. Fixed once saved.' : 'The file is connectors/<id>.yaml.'}>
                      <input
                        className="input font-mono"
                        value={current.id}
                        readOnly={!isNew}
                        onChange={(e) => {
                          setIdTouched(true)
                          edit({ id: e.target.value })
                        }}
                      />
                    </Field>
                    <Field label="Base URL" hint="http:// or https://, no trailing slash. Requests never leave it.">
                      <input className="input font-mono" value={current.base_url} onChange={(e) => edit({ base_url: e.target.value })} placeholder="https://api.example.com/v1" />
                    </Field>
                    <Field label="Browser base URL (optional)" hint="Where the browser loads the service's images, e.g. /connectors/tmobile.">
                      <input
                        className="input font-mono"
                        value={current.public_base_url ?? ''}
                        onChange={(e) => edit({ public_base_url: e.target.value.trim() ? e.target.value : null })}
                      />
                    </Field>
                    <div className="sm:col-span-2">
                      <Field label="Description" hint="Shown to the model so it knows when to use these tools.">
                        <input className="input" value={current.description} onChange={(e) => edit({ description: e.target.value })} />
                      </Field>
                    </div>
                  </div>
                  <ChoiceRow>
                    <input type="checkbox" className={choiceClass} checked={current.enabled} disabled={current.archived} onChange={(e) => edit({ enabled: e.target.checked })} />
                    Enabled
                  </ChoiceRow>
                </FormSection>

                <FormSection title="Authentication" description="The secret is read on the server from a variable in .env, never stored here.">
                  <div className="grid gap-5 sm:grid-cols-3">
                    <Field label="Type">
                      <select className="input" value={current.auth.type} onChange={(e) => edit({ auth: authFor(e.target.value as AuthType, current.auth) })}>
                        <option value="none">None</option>
                        <option value="api_key">API key header</option>
                        <option value="bearer">Bearer token</option>
                      </select>
                    </Field>
                    {current.auth.type === 'api_key' && (
                      <Field label="Header name">
                        <input className="input font-mono" value={current.auth.header ?? ''} onChange={(e) => edit({ auth: { ...current.auth, header: e.target.value } })} />
                      </Field>
                    )}
                    {current.auth.type !== 'none' && (
                      <Field label="Variable holding the secret">
                        <input
                          className="input font-mono"
                          value={current.auth.env_var ?? ''}
                          placeholder="MY_SERVICE_API_KEY"
                          onChange={(e) => edit({ auth: { ...current.auth, env_var: e.target.value } })}
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
                        <Field label="Path" hint="Starts with /; {name} fills a parameter">
                          <input className="input font-mono" value={t.path} onChange={(e) => editTool(i, { path: e.target.value })} placeholder="/products/{id}" />
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
                            <select className="input" aria-label="Parameter type" value={p.type} onChange={(e) => editParam(i, k, { type: e.target.value as Param['type'] })}>
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

                <FormSection title="Test tool" description="Call one tool of the saved connector and see the status, the cards and the raw answer.">
                  {draft || !saved ? (
                    <p className="text-sm text-muted">Save the connector first.</p>
                  ) : (
                    <TestToolPanel key={saved.id} connector={saved} />
                  )}
                </FormSection>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
