import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Loader2, Plus, Save } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type AgentDetail } from '../api/client'
import { ErrorNote } from '../components/ErrorNote'
import { Markdown } from '../components/Markdown'
import { PageHeader } from '../components/PageHeader'
import { cliHints } from '../lib/cliHints'
import { clusterColor } from '../lib/palette'
import type { AgentManifest } from '../types/generated'

type Tool = AgentManifest['tools'][number]
type WriteLevel = NonNullable<AgentManifest['write']>

/** Every MCP tool with its access kind; the `Record` type makes the list exhaustive. */
const TOOLS: Record<Tool, 'read' | 'write'> = {
  get_context: 'read',
  search_memory: 'read',
  get_episode: 'read',
  list_agents: 'read',
  add_fact: 'write',
  supersede_fact: 'write',
  log_episode: 'write',
  update_project: 'write',
  add_skill: 'write',
  update_working_memory: 'write',
}

const WRITE_LEVELS: { value: WriteLevel; label: string; hint: string }[] = [
  { value: 'none', label: 'None', hint: 'read-only' },
  { value: 'own', label: 'Own', hint: 'memory/<name>/ only' },
  { value: 'shared', label: 'Shared', hint: 'own + shared facts' },
]

const SECTIONS = [
  { key: 'identity_custom', label: 'Identity', placeholder: 'Who this agent is and what it works on.' },
  { key: 'rules_custom', label: 'Rules', placeholder: '- One rule per bullet.' },
  { key: 'style_custom', label: 'Style', placeholder: 'Tone, format, length.' },
] as const

type SectionKey = (typeof SECTIONS)[number]['key']

const SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/

/** Text under the `## Custom` heading of a rendered persona file (SPEC §7.7). */
function customSection(markdown: string): string {
  const match = /^## Custom[^\n]*\n([\s\S]*)$/m.exec(markdown)
  return match ? match[1].trim() : ''
}

function customRules(detail: AgentDetail): string {
  return detail.persona.rules
    .filter((r) => r.origin === 'manual')
    .map((r) => `- ${r.text}`)
    .join('\n')
}

/**
 * Agent editor: agent list, manifest form and Markdown editors for the Custom sections.
 *
 * Behavior:
 *     Selecting an agent loads `GET /agents/{name}`; "New agent" starts a blank
 *     custom agent. Saving sends `{manifest, identity_custom, rules_custom,
 *     style_custom}` with `POST /agents` (new) or `PUT /agents/{name}`. Projects
 *     for the read scope come from the default agent's graph. Validation is left
 *     to the backend; its error is shown as returned.
 */
export default function AgentsPage() {
  const [params, setParams] = useSearchParams()
  const selected = params.get('agent')
  const creating = params.get('new') === '1'
  const agents = useQuery({ queryKey: ['agents'], queryFn: api.listAgents })
  const detail = useQuery({
    queryKey: ['agent', selected],
    queryFn: () => api.getAgent(selected!),
    enabled: Boolean(selected) && !creating,
  })

  return (
    <div className="flex min-h-0 flex-1">
      <nav aria-label="Agents" className="flex w-60 shrink-0 flex-col border-r border-line bg-panel/50">
        <div className="p-3">
          <button type="button" className="btn w-full justify-center" onClick={() => setParams({ new: '1' })}>
            <Plus size={14} /> New agent
          </button>
        </div>
        <ul className="min-h-0 flex-1 space-y-0.5 overflow-auto px-2 pb-3">
          {agents.isPending && <li className="px-2 text-xs text-muted">Loading…</li>}
          {agents.data?.map((a) => (
            <li key={a.name}>
              <button
                type="button"
                onClick={() => setParams({ agent: a.name })}
                aria-current={a.name === selected && !creating ? 'true' : undefined}
                className={`w-full rounded-md px-2.5 py-2 text-left ${a.name === selected && !creating ? 'bg-accent/15' : 'hover:bg-raised'}`}
              >
                <div className="flex items-center gap-1.5 text-sm font-medium">
                  <Bot size={14} className="text-muted" aria-hidden />
                  {a.display_name}
                  <span className="ml-auto badge">{a.origin}</span>
                </div>
                <div className="truncate font-mono text-[11px] text-muted">{a.name}</div>
              </button>
            </li>
          ))}
        </ul>
        <div className="p-3">
          <ErrorNote error={agents.error} />
        </div>
      </nav>

      <section className="flex min-w-0 flex-1 flex-col" aria-label="Agent editor">
        {creating ? (
          <AgentForm key="new" initial={null} onSaved={(name) => setParams({ agent: name })} />
        ) : !selected ? (
          <>
            <PageHeader title="Agents" subtitle="Each agent sees only its read scope and writes only what its manifest allows." cli={cliHints.agentCreate()} />
            <p className="pt-16 text-center text-sm text-muted">Pick an agent or create a new one.</p>
          </>
        ) : detail.isPending ? (
          <div className="flex items-center gap-2 p-6 text-sm text-muted">
            <Loader2 size={14} className="animate-spin" /> Loading {selected}…
          </div>
        ) : detail.isError ? (
          <div className="p-6">
            <ErrorNote error={detail.error} />
          </div>
        ) : (
          <AgentForm key={selected} initial={detail.data} onSaved={(name) => setParams({ agent: name })} />
        )}
      </section>
    </div>
  )
}

function AgentForm({ initial, onSaved }: { initial: AgentDetail | null; onSaved: (name: string) => void }) {
  const base = initial?.manifest
  const [name, setName] = useState(base?.name ?? '')
  const [displayName, setDisplayName] = useState(base?.display_name ?? '')
  const [description, setDescription] = useState(base?.description ?? '')
  const [readAll, setReadAll] = useState(base?.read.all ?? false)
  const [projectIds, setProjectIds] = useState<string[]>(base?.read.project_ids ?? [])
  const [sharedFacts, setSharedFacts] = useState(base?.read.include_shared_facts ?? true)
  const [write, setWrite] = useState<WriteLevel>(base?.write ?? 'own')
  const [tools, setTools] = useState<Tool[]>(base?.tools ?? ['get_context', 'search_memory', 'get_episode'])
  const [model, setModel] = useState(base?.default_model ?? '')
  const [budget, setBudget] = useState(base?.token_budget ?? 2000)
  const [sections, setSections] = useState<Record<SectionKey, string>>({
    identity_custom: initial ? customSection(initial.persona.identity) : '',
    rules_custom: initial ? customRules(initial) : '',
    style_custom: initial ? customSection(initial.persona.style) : '',
  })
  const queryClient = useQueryClient()
  const models = useQuery({ queryKey: ['models'], queryFn: api.models })
  const graph = useQuery({ queryKey: ['graph', 'default', false], queryFn: () => api.graph('default') })
  const projects = useMemo(() => graph.data?.nodes.filter((n) => n.type === 'project') ?? [], [graph.data])

  const save = useMutation({
    mutationFn: () => {
      const manifest: AgentManifest = {
        ...base,
        name,
        display_name: displayName || name,
        description,
        origin: base?.origin ?? 'custom',
        created_at: base?.created_at ?? new Date().toISOString(),
        read: { ...base?.read, all: readAll, project_ids: readAll ? [] : projectIds, include_shared_facts: sharedFacts },
        write,
        tools: (Object.keys(TOOLS) as Tool[]).filter((t) => tools.includes(t)),
        default_model: model || null,
        token_budget: budget,
      }
      const body = { manifest, ...sections }
      return initial ? api.updateAgent(initial.manifest.name, body) : api.createAgent(body)
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      queryClient.invalidateQueries({ queryKey: ['agent', saved.name] })
      onSaved(saved.name)
    },
  })

  const toggle = <T,>(list: T[], value: T) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value])
  const nameValid = SLUG.test(name)
  const cli = initial ? cliHints.agentSetScope(name, projectIds) : cliHints.agentCreate(name || undefined, projectIds)

  return (
    <form
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <PageHeader
        title={initial ? `Edit ${initial.manifest.display_name}` : 'New agent'}
        subtitle={initial?.manifest.origin === 'derived' ? 'Derived agent: PAM regenerates the Derived persona sections; Custom sections are yours.' : 'Custom agent.'}
        cli={cli}
        actions={
          <button type="submit" className="btn btn-primary" disabled={!nameValid || save.isPending}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Save
          </button>
        }
      />
      <div className="min-h-0 flex-1 space-y-6 overflow-auto px-6 py-5">
        <ErrorNote error={save.error} />
        {save.isSuccess && <p className="text-sm text-ok">Saved.</p>}

        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Name" hint={nameValid || !name ? 'lowercase, digits, hyphens' : 'must match [a-z0-9][a-z0-9-]*'}>
            <input className="input font-mono" value={name} onChange={(e) => setName(e.target.value)} disabled={Boolean(initial)} required />
          </Field>
          <Field label="Display name">
            <input className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder={name} />
          </Field>
          <Field label="Default model">
            <select className="input" value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">(none)</option>
              {models.data?.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Description">
          <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>

        <div className="grid gap-6 lg:grid-cols-2">
          <fieldset className="card space-y-3 p-4">
            <legend className="label px-1">Read scope</legend>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={readAll} onChange={(e) => setReadAll(e.target.checked)} />
              Everything (all scopes)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={sharedFacts} onChange={(e) => setSharedFacts(e.target.checked)} />
              Shared facts about the user
            </label>
            <div className={readAll ? 'pointer-events-none opacity-40' : ''} aria-disabled={readAll}>
              <div className="mb-1.5 text-xs text-muted">Projects ({projectIds.length} selected)</div>
              <ul className="max-h-48 space-y-1 overflow-auto rounded-md border border-line p-2">
                {graph.isPending && <li className="text-xs text-muted">Loading projects…</li>}
                {projects.length === 0 && !graph.isPending && <li className="text-xs text-muted">No projects yet.</li>}
                {projects.map((p) => (
                  <li key={p.id}>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        disabled={readAll}
                        checked={projectIds.includes(p.id)}
                        onChange={() => setProjectIds((ids) => toggle(ids, p.id))}
                      />
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: clusterColor(p.cluster_id) }} aria-hidden />
                      <span className="truncate">{p.label}</span>
                      <span className="ml-auto text-xs text-muted">{p.size}</span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          </fieldset>

          <div className="space-y-6">
            <fieldset className="card p-4">
              <legend className="label px-1">Write level</legend>
              <div className="flex flex-wrap gap-4">
                {WRITE_LEVELS.map((w) => (
                  <label key={w.value} className="flex items-center gap-2 text-sm">
                    <input type="radio" name="write" value={w.value} checked={write === w.value} onChange={() => setWrite(w.value)} />
                    {w.label}
                    <span className="text-xs text-muted">{w.hint}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className="card p-4">
              <legend className="label px-1">Tools</legend>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                {(Object.entries(TOOLS) as [Tool, 'read' | 'write'][]).map(([tool, kind]) => (
                  <label key={tool} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={tools.includes(tool)} onChange={() => setTools((t) => toggle(t, tool))} />
                    <span className="font-mono text-xs">{tool}</span>
                    <span className={`text-[10px] ${kind === 'write' ? 'text-warn' : 'text-muted'}`}>{kind}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className="card p-4">
              <legend className="label px-1">Token budget</legend>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={256}
                  max={32000}
                  step={16}
                  value={budget}
                  onChange={(e) => setBudget(Number(e.target.value))}
                  className="flex-1 accent-[rgb(var(--accent))]"
                  aria-label="Token budget"
                />
                <span className="w-20 text-right font-mono text-sm tabular-nums">{budget.toLocaleString()}</span>
              </div>
            </fieldset>
          </div>
        </div>

        <div className="space-y-4">
          <div className="label">Persona · Custom sections (never touched by PAM)</div>
          {SECTIONS.map((s) => (
            <div key={s.key} className="grid gap-3 lg:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-sm font-medium">{s.label}</span>
                <textarea
                  className="input min-h-[8rem] font-mono text-xs"
                  value={sections[s.key]}
                  placeholder={s.placeholder}
                  onChange={(e) => setSections((all) => ({ ...all, [s.key]: e.target.value }))}
                />
              </label>
              <div className="flex flex-col gap-1">
                <span className="text-sm text-muted">Preview</span>
                <div className="card min-h-[8rem] overflow-auto px-3 py-2">
                  {sections[s.key].trim() ? <Markdown>{sections[s.key]}</Markdown> : <p className="text-xs text-muted">Nothing yet.</p>}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </form>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-muted">{hint}</span>}
    </label>
  )
}
