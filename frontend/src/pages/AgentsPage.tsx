import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, CheckCircle2, Eye, Loader2, PenLine, Save } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type AgentDetail } from '../api/client'
import { AgentList } from '../components/agents/AgentList'
import { ChoiceRow, Field, FormSection, choiceClass } from '../components/agents/FormParts'
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

const TOOL_GROUPS = [
  { kind: 'read', label: 'Read tools', icon: Eye },
  { kind: 'write', label: 'Write tools', icon: PenLine },
] as const

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
const BUDGET_MIN = 256
const BUDGET_MAX = 32000

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
 * Agent editor: agent list beside one glass panel holding the manifest form and persona editors.
 *
 * Behavior:
 *     Selecting an agent loads `GET /agents/{name}`; "New agent" starts a blank
 *     custom agent. Saving sends `{manifest, identity_custom, rules_custom,
 *     style_custom}` with `POST /agents` (new) or `PUT /agents/{name}`. Projects
 *     for the read scope come from the default agent's graph. Validation is left
 *     to the backend; its error is shown as returned. Below `lg` the list sits
 *     above the editor and the whole page scrolls; at `lg` only the form panel does.
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
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto lg:flex-row lg:overflow-hidden">
      <AgentList
        agents={agents.data}
        loading={agents.isPending}
        error={agents.error}
        selected={creating ? null : selected}
        onSelect={(name) => setParams({ agent: name })}
        onNew={() => setParams({ new: '1' })}
      />

      <section className="flex min-w-0 shrink-0 flex-col lg:min-h-0 lg:flex-1 lg:shrink" aria-label="Agent editor">
        {creating ? (
          <AgentForm key="new" initial={null} onSaved={(name) => setParams({ agent: name })} />
        ) : !selected ? (
          <>
            <PageHeader
              title="Agents"
              subtitle="Each agent sees only its read scope and writes only what its manifest allows."
              cli={cliHints.agentCreate()}
            />
            <div className="panel flex flex-col items-center gap-4 px-6 py-16 text-center lg:flex-1 lg:justify-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-accent/15 text-accent" aria-hidden>
                <Bot size={26} strokeWidth={1.75} />
              </span>
              <div>
                <p className="text-[15px] font-medium text-fg">Pick an agent or create a new one.</p>
                <p className="mt-1 text-sm text-muted">Its scope, tools and persona open here.</p>
              </div>
            </div>
          </>
        ) : detail.isPending ? (
          <div className="panel flex items-center justify-center gap-2.5 p-8 text-sm text-muted lg:flex-1">
            <Loader2 size={16} className="animate-spin" aria-hidden /> Loading {selected}…
          </div>
        ) : detail.isError ? (
          <div className="panel p-6 sm:p-8">
            <ErrorNote error={detail.error} />
          </div>
        ) : (
          <AgentForm key={selected} initial={detail.data} onSaved={(name) => setParams({ agent: name })} />
        )}
      </section>
    </div>
  )
}

/**
 * Manifest and persona form for one agent, grouped into calm sections inside a single panel.
 *
 * Behavior:
 *     Holds every field in local state seeded from `initial`. Submitting
 *     creates or updates the agent and then reports the saved name. The Save
 *     button is disabled until the name is a valid slug.
 * Parameters:
 *     initial: The loaded agent, or null for a new agent.
 *     onSaved: Called with the saved agent's name.
 */
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
  const budgetPct = ((budget - BUDGET_MIN) / (BUDGET_MAX - BUDGET_MIN)) * 100

  return (
    <form
      className="flex flex-col lg:min-h-0 lg:flex-1"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <PageHeader
        title={initial ? `Edit ${initial.manifest.display_name}` : 'New agent'}
        subtitle={
          initial?.manifest.origin === 'derived'
            ? 'Derived agent: PAM regenerates the Derived persona sections; Custom sections are yours.'
            : 'Custom agent.'
        }
        cli={cli}
        actions={
          <button type="submit" className="btn btn-primary px-5" disabled={!nameValid || save.isPending}>
            {save.isPending ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Save size={16} strokeWidth={1.75} aria-hidden />} Save
          </button>
        }
      />

      <div className="panel p-5 sm:p-8 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
        {(save.error || save.isSuccess) && (
          <div className="mb-6 space-y-3" aria-live="polite">
            <ErrorNote error={save.error} />
            {save.isSuccess && (
              <p className="flex items-center gap-2 text-sm text-ok">
                <CheckCircle2 size={16} strokeWidth={1.75} aria-hidden /> Saved.
              </p>
            )}
          </div>
        )}

        <div className="divide-y divide-edge/10">
          <FormSection title="Profile" description="How the agent is named and which model it uses by default.">
            <div className="grid gap-5 sm:grid-cols-2">
              <Field
                label="Name"
                hint={nameValid || !name ? 'Lowercase letters, digits and hyphens.' : 'Must match [a-z0-9][a-z0-9-]*'}
                invalid={Boolean(name) && !nameValid}
              >
                <input className="input font-mono" value={name} onChange={(e) => setName(e.target.value)} disabled={Boolean(initial)} required />
              </Field>
              <Field label="Display name">
                <input className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder={name} />
              </Field>
              <div className="sm:col-span-2">
                <Field label="Description">
                  <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
                </Field>
              </div>
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
          </FormSection>

          <FormSection title="Access" description="What the agent can read from memory and how far its writes reach.">
            <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
              <fieldset className="well min-w-0 p-4">
                <legend className="sr-only">Read scope</legend>
                <div className="mb-2 px-1 text-sm font-medium text-fg" aria-hidden>
                  Read scope
                </div>
                <div className="space-y-0.5">
                  <ChoiceRow>
                    <input type="checkbox" className={choiceClass} checked={readAll} onChange={(e) => setReadAll(e.target.checked)} />
                    Everything (all scopes)
                  </ChoiceRow>
                  <ChoiceRow>
                    <input type="checkbox" className={choiceClass} checked={sharedFacts} onChange={(e) => setSharedFacts(e.target.checked)} />
                    Shared facts about the user
                  </ChoiceRow>
                </div>
                <div className={`mt-4 transition-opacity duration-200 ${readAll ? 'pointer-events-none opacity-40' : ''}`} aria-disabled={readAll}>
                  <div className="mb-1.5 flex items-baseline justify-between px-1">
                    <span className="label">Projects</span>
                    <span className="text-xs tabular-nums text-muted">{projectIds.length} selected</span>
                  </div>
                  <ul className="max-h-56 space-y-0.5 overflow-y-auto border-t border-edge/10 pt-2">
                    {graph.isPending && <li className="px-3 py-2 text-sm text-muted">Loading projects…</li>}
                    {projects.length === 0 && !graph.isPending && <li className="px-3 py-2 text-sm text-muted">No projects yet.</li>}
                    {projects.map((p) => (
                      <li key={p.id}>
                        <ChoiceRow>
                          <input
                            type="checkbox"
                            className={choiceClass}
                            disabled={readAll}
                            checked={projectIds.includes(p.id)}
                            onChange={() => setProjectIds((ids) => toggle(ids, p.id))}
                          />
                          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: clusterColor(p.cluster_id) }} aria-hidden />
                          <span className="min-w-0 flex-1 truncate">{p.label}</span>
                          <span className="text-xs tabular-nums text-muted">{p.size}</span>
                        </ChoiceRow>
                      </li>
                    ))}
                  </ul>
                </div>
              </fieldset>

              <fieldset className="well min-w-0 p-4">
                <legend className="sr-only">Write level</legend>
                <div className="mb-2 px-1 text-sm font-medium text-fg" aria-hidden>
                  Write level
                </div>
                <div className="space-y-0.5">
                  {WRITE_LEVELS.map((w) => (
                    <ChoiceRow key={w.value} className="py-2">
                      <input
                        type="radio"
                        className={choiceClass}
                        name="write"
                        value={w.value}
                        checked={write === w.value}
                        onChange={() => setWrite(w.value)}
                      />
                      <span className="min-w-0">
                        <span className="block text-fg">{w.label}</span>
                        <span className="block truncate text-xs text-muted">{w.hint}</span>
                      </span>
                    </ChoiceRow>
                  ))}
                </div>
              </fieldset>
            </div>
          </FormSection>

          <FormSection title="Tools" description="MCP tools the agent may call. Write tools change memory.">
            <div className="grid gap-5 md:grid-cols-2">
              {TOOL_GROUPS.map(({ kind, label, icon: Icon }) => (
                <fieldset key={kind} className="well min-w-0 p-4">
                  <legend className="sr-only">{label}</legend>
                  <div className="mb-2 flex items-center gap-2 px-1 text-sm font-medium text-fg" aria-hidden>
                    <Icon size={16} strokeWidth={1.75} className={kind === 'write' ? 'text-warn' : 'text-accent'} />
                    {label}
                  </div>
                  <div className="space-y-0.5">
                    {(Object.entries(TOOLS) as [Tool, 'read' | 'write'][])
                      .filter(([, k]) => k === kind)
                      .map(([tool]) => (
                        <ChoiceRow key={tool}>
                          <input type="checkbox" className={choiceClass} checked={tools.includes(tool)} onChange={() => setTools((t) => toggle(t, tool))} />
                          <span className="min-w-0 truncate font-mono text-[13px]">{tool}</span>
                        </ChoiceRow>
                      ))}
                  </div>
                </fieldset>
              ))}
            </div>
          </FormSection>

          <FormSection title="Token budget" description="Upper bound on the context bundle the agent receives.">
            <div className="well p-5">
              <div className="flex items-baseline justify-between gap-4">
                <span className="label">Budget per request</span>
                <span className="text-[22px] font-semibold tabular-nums tracking-[-0.01em] text-fg">
                  {budget.toLocaleString()}
                  <span className="ml-1.5 text-sm font-normal text-muted">tokens</span>
                </span>
              </div>
              <input
                type="range"
                min={BUDGET_MIN}
                max={BUDGET_MAX}
                step={16}
                value={budget}
                onChange={(e) => setBudget(Number(e.target.value))}
                className="mt-3 w-full cursor-pointer accent-accent"
                aria-label="Token budget"
                aria-valuetext={`${budget.toLocaleString()} tokens, ${Math.round(budgetPct)}% of maximum`}
              />
              <div className="mt-1 flex justify-between text-xs tabular-nums text-muted">
                <span>{BUDGET_MIN.toLocaleString()}</span>
                <span>{BUDGET_MAX.toLocaleString()}</span>
              </div>
            </div>
          </FormSection>

          <FormSection title="Persona" description="Custom sections are yours. PAM never touches them.">
            {SECTIONS.map((s) => (
              <div key={s.key} className="well p-4">
                <div className="grid gap-4 lg:grid-cols-2">
                  <label className="flex min-w-0 flex-col gap-2">
                    <span className="px-1 text-sm font-medium text-fg">{s.label}</span>
                    <textarea
                      className="input min-h-[9rem] resize-y font-mono text-[13px] leading-relaxed"
                      value={sections[s.key]}
                      placeholder={s.placeholder}
                      onChange={(e) => setSections((all) => ({ ...all, [s.key]: e.target.value }))}
                    />
                  </label>
                  <div className="flex min-w-0 flex-col gap-2">
                    <span className="px-1 text-sm text-muted">Preview</span>
                    <div className="min-h-[9rem] flex-1 overflow-auto rounded-control border border-edge/[0.08] bg-bg/20 px-4 py-3">
                      {sections[s.key].trim() ? <Markdown>{sections[s.key]}</Markdown> : <p className="text-sm text-muted">Nothing yet.</p>}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </FormSection>
        </div>
      </div>
    </form>
  )
}
