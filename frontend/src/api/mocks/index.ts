/**
 * In-memory handlers that stand in for the REST API when `VITE_PAM_MOCK=1`.
 *
 * Behavior:
 *     `mockRequest` routes `(method, path)` to a handler, waits 150–400 ms and
 *     returns JSON typed with the generated contracts, or throws `ApiError` with
 *     the §7.14 error codes. `mockChatStream` emits `context` first, then tokens,
 *     then exactly one `done`, or an `error` when the message contains `/fail`.
 *     Only `client.ts` imports this module.
 */
import type {
  AgentManifest,
  ChatEvent,
  ChatRequest,
  ContextBundle,
  ContextRequest,
  EpisodeSnippet,
  Fact,
  GraphData,
  GraphLink,
  GraphNode,
  ImportReport,
  JobStatus,
  ProjectBrief,
  SearchHit,
  SearchQuery,
  SearchResponse,
  Source,
  SyncReport,
  WorkingMemory,
  WriteResult,
} from '../../types/generated'
import { ApiError, type AgentUpsert, type Health, type VaultFile, type VaultTree } from '../client'
import {
  ALL_TOOLS,
  MODELS,
  NOW,
  hash,
  importClaudeExport,
  personaFor,
  rng,
  seedUuid,
  world,
  type SeedEpisode,
  type SeedProject,
} from './world'

const SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/
const RESERVED = new Set(['shared'])
const STAGES: JobStatus['stage'][] = ['queued', 'extract', 'normalize', 'derive', 'index', 'cluster']
const STAGE_MS = 1100

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      resolve()
    })
  })
}

const latency = () => sleep(150 + Math.random() * 250)
const now = () => new Date().toISOString()
const notFound = (what: string) => new ApiError(404, 'NOT_FOUND', `${what} not found`)
const invalid = (message: string) => new ApiError(400, 'VALIDATION_ERROR', message)
const tokensOf = (text: string) => Math.ceil(text.length / 4)

// ---------------------------------------------------------------- scope

function agentOrDefault(name: string | null | undefined): AgentManifest {
  const agent = world.agents.find((a) => a.name === (name || 'default'))
  if (!agent) throw notFound(`agent '${name}'`)
  return agent
}

function visibleProjects(agent: AgentManifest): SeedProject[] {
  if (agent.read.all) return world.projects
  const ids = new Set(agent.read.project_ids ?? [])
  return world.projects.filter((p) => ids.has(p.id))
}

function visibleEpisodes(agent: AgentManifest): SeedEpisode[] {
  if (agent.read.all) return world.episodes
  const ids = new Set(visibleProjects(agent).map((p) => p.id))
  return world.episodes.filter((e) => e.projectId !== null && ids.has(e.projectId))
}

function visibleFacts(agent: AgentManifest): Fact[] {
  return agent.read.all || agent.read.include_shared_facts !== false ? world.facts : []
}

const episodePath = (e: SeedEpisode) => `memory/default/episodes/${e.id}.md`
const projectPath = (p: SeedProject) => `memory/default/projects/${p.id}.md`
const factPath = (f: Fact) => `memory/shared/facts/${f.id}.md`

function lastActivity(project: SeedProject): string {
  const dates = world.episodes.filter((e) => e.projectId === project.id).map((e) => e.createdAt)
  return dates.sort().at(-1) ?? NOW
}

// ---------------------------------------------------------------- graph

function syntheticGraph(total: number): GraphData {
  const random = rng(total)
  const nodes: GraphNode[] = []
  const links: GraphLink[] = []
  const projectCount = Math.max(4, Math.round(total / 25))
  for (let p = 0; p < projectCount; p++) {
    const id = seedUuid(`synthetic-project:${p}`)
    nodes.push({ id, type: 'project', label: `Synthetic project ${p + 1}`, cluster_id: id, size: 0, created_at: NOW, path: null })
  }
  const projects = nodes.slice()
  for (let i = nodes.length; i < total; i++) {
    const project = projects[Math.floor(random() * projectCount)]
    const id = seedUuid(`synthetic-episode:${i}`)
    nodes.push({ id, type: 'episode', label: `Conversation ${i}`, cluster_id: project.cluster_id, size: Math.log(4 + random() * 40), created_at: NOW, path: null })
    project.size += 1
    links.push({ source: id, target: project.id, kind: 'member', weight: 1 })
    if (i > projectCount + 2 && random() < 0.7) {
      const other = nodes[projectCount + Math.floor(random() * (i - projectCount))]
      links.push({ source: id, target: other.id, kind: 'similar', weight: 0.75 + random() * 0.2 })
    }
  }
  return { schema_version: '1.0.0', agent: 'default', nodes, links, generated_at: now() }
}

function buildGraph(agentName: string | null, withFacts: boolean): GraphData {
  const override = Number(new URLSearchParams(window.location.search).get('mockNodes'))
  if (override > 0) return syntheticGraph(Math.min(override, 5000))

  const agent = agentOrDefault(agentName)
  const projects = visibleProjects(agent)
  const episodes = visibleEpisodes(agent)
  const nodes: GraphNode[] = []
  const links: GraphLink[] = []

  for (const p of projects) {
    const members = episodes.filter((e) => e.projectId === p.id)
    nodes.push({ id: p.id, type: 'project', label: p.name, cluster_id: p.id, size: members.length, created_at: lastActivity(p), path: projectPath(p) })
  }
  const byProject = new Map<string, SeedEpisode[]>()
  for (const e of episodes) {
    nodes.push({ id: e.id, type: 'episode', label: e.title, cluster_id: e.projectId, size: Math.log(e.turns.length + 1), created_at: e.createdAt, path: episodePath(e) })
    if (e.projectId) {
      links.push({ source: e.id, target: e.projectId, kind: 'member', weight: 1 })
      byProject.set(e.projectId, [...(byProject.get(e.projectId) ?? []), e])
    }
  }
  for (const members of byProject.values()) {
    members.forEach((e, i) => {
      const h = hash(e.id)
      for (const offset of [1, 2 + (h % 3)]) {
        const other = members[(i + offset) % members.length]
        if (other.id !== e.id && (h >> offset) % 3 !== 0) {
          links.push({ source: e.id, target: other.id, kind: 'similar', weight: 0.75 + ((h >> 4) % 20) / 100 })
        }
      }
    })
  }
  const all = [...byProject.values()].flat()
  for (let i = 0; i + 7 < all.length; i += 7) {
    if (all[i].projectId !== all[i + 7].projectId) {
      links.push({ source: all[i].id, target: all[i + 7].id, kind: 'similar', weight: 0.76 })
    }
  }
  if (withFacts) {
    const ids = new Set(nodes.map((n) => n.id))
    for (const f of visibleFacts(agent)) {
      nodes.push({ id: f.id, type: 'fact', label: `${f.attribute}: ${f.value}`, cluster_id: null, size: 1, created_at: f.updated_at, path: factPath(f) })
      if (f.source_episode && ids.has(f.source_episode)) {
        links.push({ source: f.id, target: f.source_episode, kind: 'derived_from', weight: f.confidence })
      }
    }
  }
  return { schema_version: '1.0.0', agent: agent.name, nodes, links, generated_at: now() }
}

// ---------------------------------------------------------------- search & context

const words = (text: string) => text.toLowerCase().match(/[a-z0-9][a-z0-9-]+/g) ?? []
const STOP = new Set(['the', 'and', 'for', 'was', 'what', 'where', 'did', 'left', 'off', 'with', 'my', 'how', 'lets', 'let', 'keep', 'going', 'on', 'me', 'am', 'i', 'it', 'is'])

function overlap(query: string[], text: string): number {
  const bag = new Set(words(text))
  return query.filter((w) => bag.has(w)).length
}

interface Doc {
  id: string
  type: SearchHit['doc_type']
  title: string
  text: string
  path: string
  createdAt: string | null
  scope: string
}

function docsFor(agent: AgentManifest): Doc[] {
  return [
    ...visibleEpisodes(agent).map((e): Doc => ({
      id: e.id, type: 'episode', title: e.title, scope: 'default', path: episodePath(e), createdAt: e.createdAt,
      text: [e.summary, ...e.turns.map((t) => t.text)].join(' '),
    })),
    ...visibleProjects(agent).map((p): Doc => ({
      id: p.id, type: 'project', title: p.name, scope: 'default', path: projectPath(p), createdAt: lastActivity(p),
      text: `${p.summary} ${p.keywords.join(' ')} ${p.notes.join(' ')}`,
    })),
    ...visibleFacts(agent).map((f): Doc => ({
      id: f.id, type: 'fact', title: `${f.attribute} = ${f.value}`, scope: f.scope, path: factPath(f), createdAt: f.updated_at,
      text: `${f.attribute.replace(/_/g, ' ')} ${f.value}`,
    })),
  ]
}

function search(q: SearchQuery): SearchResponse {
  const started = performance.now()
  if (!q.query?.trim()) throw invalid('query: must not be empty')
  const k = q.k ?? 8
  if (k < 1 || k > 50) throw invalid('k: must be between 1 and 50')
  const agent = agentOrDefault(q.agent)
  const query = words(q.query).filter((w) => !STOP.has(w))
  const docs = docsFor(agent).filter((d) => !q.doc_types || q.doc_types.includes(d.type))
  const scored = docs.map((d) => {
    const keyword = overlap(query, `${d.title} ${d.text}`)
    const vector = keyword * 0.6 + overlap(query, d.title) + (hash(d.id + q.query) % 100) / 400
    return { d, keyword, vector }
  })
  const keywordRank = new Map(
    scored.filter((s) => s.keyword > 0).sort((a, b) => b.keyword - a.keyword).map((s, i) => [s.d.id, i + 1]),
  )
  const vectorRank = new Map(
    [...scored].sort((a, b) => b.vector - a.vector).slice(0, 50).map((s, i) => [s.d.id, i + 1]),
  )
  const hits: SearchHit[] = scored
    .map(({ d }) => {
      const vr = vectorRank.get(d.id) ?? null
      const kr = keywordRank.get(d.id) ?? null
      const score = (vr ? 1 / (60 + vr) : 0) + (kr ? 1 / (60 + kr) : 0)
      return {
        chunk_id: `${d.id}:0`, doc_id: d.id, doc_type: d.type, scope: d.scope, title: d.title,
        snippet: d.text.slice(0, 280), path: d.path, score: Number(score.toFixed(5)),
        vector_rank: vr, keyword_rank: kr, created_at: d.createdAt,
      }
    })
    .filter((h) => h.vector_rank !== null || h.keyword_rank !== null)
    .sort((a, b) => b.score - a.score)
    .slice(0, k)
  return {
    schema_version: '1.0.0', query: q.query, agent: agent.name, hits,
    took_ms: Math.max(4, Math.round(performance.now() - started + 18)),
  }
}

function rankProjects(agent: AgentManifest, query: string): SeedProject[] {
  const q = words(query).filter((w) => !STOP.has(w))
  return [...visibleProjects(agent)].sort((a, b) => {
    const sa = overlap(q, `${a.name} ${a.keywords.join(' ')} ${a.notes.join(' ')}`)
    const sb = overlap(q, `${b.name} ${b.keywords.join(' ')} ${b.notes.join(' ')}`)
    if (sa !== sb) return sb - sa
    if (a.status !== b.status) return a.status === 'active' ? -1 : 1
    return lastActivity(b).localeCompare(lastActivity(a))
  })
}

const transcriptTokens = (e: SeedEpisode) => 6000 + (hash(e.id) % 6000)

function buildContext(req: ContextRequest): ContextBundle {
  if (!req.query?.trim()) throw invalid('query: must not be empty')
  const agent = agentOrDefault(req.agent)
  const budget = req.token_budget ?? agent.token_budget ?? 2000
  if (budget < 256 || budget > 32000) throw invalid('token_budget: must be between 256 and 32000')
  const persona = req.include_persona === false ? null : personaFor(agent.name)
  const facts = visibleFacts(agent)
  const active = facts.filter((f) => f.status !== 'conflict')
  const conflicts = facts.filter((f) => f.status === 'conflict')
  const working = req.session_id ? world.sessions.get(req.session_id) ?? null : null
  const ranked = rankProjects(agent, req.query).slice(0, 3)
  const projects: ProjectBrief[] = ranked.map((p) => ({
    id: p.id, name: p.name, keywords: p.keywords, status: p.status, last_activity_at: lastActivity(p),
    summary: `${p.summary} ${p.notes.join('. ')}.`,
  }))
  const top = ranked[0]
  const sourceEpisodes = top
    ? world.episodes.filter((e) => e.projectId === top.id).sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, 5)
    : []
  let episodes: EpisodeSnippet[] = sourceEpisodes.map((e) => ({
    episode_id: e.id, title: e.title, source: e.source, created_at: e.createdAt,
    text: `${e.summary} ${e.turns[0].text}`, chunk_ids: [`${e.id}:0`],
  }))

  const render = (snips: EpisodeSnippet[]) => {
    const out: string[] = []
    if (persona) {
      out.push('# Agent persona', persona.identity.split('## Custom')[0].replace(/## Derived[^\n]*\n/, '').trim(),
        ...persona.rules.map((r) => `- ${r.text}`), `(agent/${agent.name}/identity.md)`, '')
    }
    if (conflicts.length) {
      out.push('# ⚠ Conflicting facts — ask the user',
        ...conflicts.map((f) => `- ${f.attribute}: "${f.value}" vs "${f.conflict?.candidate_value}" (${factPath(f)})`), '')
    }
    if (working) {
      out.push('# Working memory', `- Goal: ${working.goal ?? 'n/a'}`,
        ...(working.recent_turns ?? []).slice(-4).map((t) => `- ${t.role}: ${t.text.replace(/[*#\s]+/g, ' ').trim().slice(0, 120)}`), `(working/${working.session_id}.md)`, '')
    }
    if (active.length) out.push('# Known facts', ...active.map((f) => `- ${f.attribute}: ${f.value} (${factPath(f)})`), '')
    if (projects.length) {
      out.push('# Relevant projects', ...projects.map((p) => `## ${p.name} (${p.status})\n${p.summary}\n(memory/default/projects/${p.id}.md)`), '')
    }
    if (snips.length) {
      out.push('# Relevant past conversations',
        ...snips.map((s) => `## ${s.title} · ${s.created_at.slice(0, 10)}\n${s.text}\n(memory/default/episodes/${s.episode_id}.md)`))
    }
    return out.join('\n').trim()
  }

  let rendered = render(episodes)
  while (tokensOf(rendered) > budget && episodes.length) {
    episodes = episodes.slice(0, -1)
    rendered = render(episodes)
  }
  if (tokensOf(rendered) > budget) rendered = rendered.slice(0, budget * 4)
  const used = tokensOf(rendered)
  const contributing = sourceEpisodes.filter((e) => episodes.some((s) => s.episode_id === e.id))
  const baseline = contributing.reduce((sum, e) => sum + transcriptTokens(e), 0)
  return {
    schema_version: '1.0.0', agent: agent.name, query: req.query, persona, facts: active, conflicts, projects, episodes,
    working, rendered, tokens_used: used, token_budget: budget, baseline_tokens: baseline,
    tokens_saved: Math.max(0, baseline - used), tokenizer: 'cl100k_base', generated_at: now(),
  }
}

// ---------------------------------------------------------------- vault

function vaultTree(agentName: string | null): VaultTree {
  const agent = agentOrDefault(agentName)
  const paths = [
    'pam.toml',
    ...world.agents.flatMap((a) => ['agent.yaml', 'identity.md', 'rules.md', 'style.md'].map((f) => `agent/${a.name}/${f}`)),
    ...visibleEpisodes(agent).map(episodePath),
    ...visibleProjects(agent).map(projectPath),
    ...visibleFacts(agent).map(factPath),
    ...(world.claudeImported ? ['imports/claude/20261017T200000Z/claude-export.zip'] : []),
    'imports/chatgpt/20261009T170000Z/chatgpt-export.zip',
    ...[...world.sessions.keys()].map((id) => `working/${id}.md`),
  ]
  return { paths: paths.sort() }
}

function yamlish(value: unknown): Record<string, unknown> {
  return JSON.parse(JSON.stringify(value)) as Record<string, unknown>
}

function vaultFile(path: string | null): VaultFile {
  if (!path) throw invalid('path: required')
  if (path.includes('..') || path.startsWith('/') || /^[a-zA-Z]:/.test(path) || path.includes('\\')) {
    throw invalid('path: must be a vault-relative POSIX path')
  }
  const id = path.split('/').at(-1)?.replace(/\.(md|yaml)$/, '') ?? ''
  const episode = world.episodes.find((e) => e.id === id)
  if (episode && path === episodePath(episode)) {
    const body = [
      `# ${episode.title}`, '',
      ...(episode.summary ? ['## Summary', episode.summary, ''] : []),
      '## Transcript', '',
      ...episode.turns.flatMap((t) => [`### ${t.role} · ${t.created_at ?? 'unknown'}`, t.text, '']),
    ].join('\n')
    return {
      path,
      frontmatter: {
        schema_version: '1.0.0', id: episode.id, agent: 'default', source: episode.source,
        source_conversation_id: `conv-${hash(episode.id).toString(16)}`, title: episode.title,
        created_at: episode.createdAt, updated_at: episode.createdAt, imported_at: NOW,
        message_count: episode.turns.length, has_summary: Boolean(episode.summary),
        body_sha256: hash(body).toString(16).padStart(8, '0').repeat(8), tags: [], superseded_facts: [],
      },
      body,
    }
  }
  const project = world.projects.find((p) => p.id === id)
  if (project && path === projectPath(project)) {
    const members = world.episodes.filter((e) => e.projectId === project.id)
    return {
      path,
      frontmatter: {
        schema_version: '1.0.0', id: project.id, scope: 'default', name: project.name, keywords: project.keywords,
        episode_ids: members.map((e) => e.id), origin: 'cluster', status: project.status,
        created_at: members[0]?.createdAt ?? NOW, updated_at: NOW, last_activity_at: lastActivity(project),
      },
      body: [
        '## Summary (auto)', project.summary, '', ...members.map((e) => `- ${e.title}`), '',
        '## Notes', ...project.notes.map((n, i) => `- 2026-10-1${i}T03:12Z (agent:default) ${n}`),
      ].join('\n'),
    }
  }
  const fact = world.facts.find((f) => f.id === id)
  if (fact && path === factPath(fact)) {
    return { path, frontmatter: yamlish(fact), body: `${fact.attribute.replace(/_/g, ' ')}: **${fact.value}**` }
  }
  const agentMatch = /^agent\/([^/]+)\/(agent\.yaml|identity\.md|rules\.md|style\.md)$/.exec(path)
  if (agentMatch) {
    const agent = agentOrDefault(agentMatch[1])
    const persona = personaFor(agent.name)
    if (agentMatch[2] === 'agent.yaml') {
      return { path, frontmatter: yamlish(agent), body: '' }
    }
    const body = agentMatch[2] === 'identity.md' ? persona.identity
      : agentMatch[2] === 'style.md' ? persona.style
        : persona.rules.map((r) => `- ${r.text} <!-- ${r.id} · ${r.origin} · evidence ${r.evidence_count} -->`).join('\n')
    return { path, frontmatter: {}, body }
  }
  const session = /^working\/(s_[0-9a-z]{12})\.md$/.exec(path)
  if (session && world.sessions.has(session[1])) {
    const wm = world.sessions.get(session[1])!
    return {
      path,
      frontmatter: yamlish({ ...wm, recent_turns: undefined }),
      body: [`## Goal`, wm.goal ?? '', '', '## Recent turns', ...(wm.recent_turns ?? []).map((t) => `- **${t.role}:** ${t.text}`)].join('\n'),
    }
  }
  if (path === 'pam.toml') {
    return {
      path, frontmatter: {},
      body: ['```toml', 'schema_version = "1.0.0"', '', ...MODELS.map((m) => `[[models]]\nid = "${m.id}"\nlabel = "${m.label}"\nsupports_tools = ${m.supports_tools}\n`), '```'].join('\n'),
    }
  }
  if (path.startsWith('imports/')) {
    return { path, frontmatter: {}, body: '_Raw export archived byte-for-byte; binary content is not rendered._' }
  }
  throw notFound(`file '${path}'`)
}

// ---------------------------------------------------------------- imports

interface Job {
  id: string
  startedAt: number
  source: Source
  fileName: string
  report: ImportReport | null
}
const jobs = new Map<string, Job>()

function detectSource(fileName: string, explicit: string | null): Source {
  if (explicit === 'claude' || explicit === 'chatgpt' || explicit === 'gemini') return explicit
  const lower = fileName.toLowerCase()
  if (lower.includes('chatgpt') || lower.includes('openai')) return 'chatgpt'
  if (lower.includes('gemini') || lower.includes('takeout')) return 'gemini'
  return 'claude'
}

function jobStatus(job: Job): JobStatus {
  const elapsed = Date.now() - job.startedAt
  const index = Math.floor(elapsed / STAGE_MS)
  const failing = job.fileName.toLowerCase().includes('fail')
  if (failing && index >= 2) {
    return { schema_version: '1.0.0', job_id: job.id, stage: 'error', progress: 2 / STAGES.length, report: null, error: `extract: '${job.fileName}' is not a recognized export` }
  }
  if (index < STAGES.length) {
    const progress = Math.min(0.99, (index + (elapsed % STAGE_MS) / STAGE_MS) / STAGES.length)
    return { schema_version: '1.0.0', job_id: job.id, stage: STAGES[index], progress: Number(progress.toFixed(3)), report: null, error: null }
  }
  if (!job.report) {
    const [found, written] = job.source === 'claude' ? importClaudeExport() : [10, 0]
    job.report = {
      schema_version: '1.0.0', source: job.source, input_path: `/tmp/upload/${job.fileName}`,
      archived_path: `imports/${job.source}/20261017T200000Z/${job.fileName}`,
      conversations_found: found, episodes_written: written, episodes_skipped_existing: found - written,
      errors: [], commit_sha: written ? hash(job.id).toString(16).padStart(8, '0').slice(0, 7) : null,
      duration_ms: STAGES.length * STAGE_MS,
    }
  }
  return { schema_version: '1.0.0', job_id: job.id, stage: 'done', progress: 1, report: job.report, error: null }
}

// ---------------------------------------------------------------- agents & sessions

function upsertAgent(body: AgentUpsert, existing: string | null): AgentManifest {
  const m = body?.manifest
  if (!m || typeof m.name !== 'string') throw invalid('manifest: required')
  if (!SLUG.test(m.name)) throw invalid(`manifest.name: must match ${SLUG.source}`)
  if (RESERVED.has(m.name)) throw invalid('manifest.name: reserved name')
  if ((m.token_budget ?? 2000) < 256 || (m.token_budget ?? 2000) > 32000) throw invalid('manifest.token_budget: must be between 256 and 32000')
  if (m.tools.some((t) => !ALL_TOOLS.includes(t))) throw invalid('manifest.tools: unknown tool')
  const index = world.agents.findIndex((a) => a.name === (existing ?? m.name))
  if (existing === null && index >= 0) throw new ApiError(409, 'CONFLICT', `agent '${m.name}' already exists`)
  if (existing !== null && index < 0) throw notFound(`agent '${existing}'`)
  if (existing !== null && m.name !== existing) throw invalid('manifest.name: cannot be renamed')
  const saved: AgentManifest = { ...m, schema_version: '1.0.0' }
  if (index >= 0) world.agents[index] = saved
  else world.agents.push(saved)
  world.customSections.set(m.name, { identity: body.identity_custom, rules: body.rules_custom, style: body.style_custom })
  return saved
}

function newSessionId(): string {
  const chars = '0123456789abcdefghijklmnopqrstuvwxyz'
  let id = ''
  for (let i = 0; i < 12; i++) id += chars[Math.floor(Math.random() * chars.length)]
  return `s_${id}`
}

function getSession(id: string): WorkingMemory {
  const session = world.sessions.get(id)
  if (!session) throw notFound(`session '${id}'`)
  return session
}

function endSession(id: string): WriteResult {
  const session = getSession(id)
  if (session.status === 'ended') {
    return { schema_version: '1.0.0', ok: true, action: 'noop', doc_id: session.promoted_episode_id, path: null, commit_sha: null, conflict: null, message: 'session already ended' }
  }
  const episode: SeedEpisode = {
    id: seedUuid(`episode:pam:${id}`),
    title: session.goal ? `Chat: ${session.goal.slice(0, 60)}` : `Chat session ${id}`,
    source: 'pam',
    createdAt: session.started_at,
    projectId: rankProjects(agentOrDefault(session.agent), session.goal ?? '')[0]?.id ?? null,
    summary: (session.decisions ?? []).join('; '),
    turns: session.recent_turns ?? [],
  }
  world.episodes.push(episode)
  session.status = 'ended'
  session.promoted_episode_id = episode.id
  session.updated_at = now()
  return {
    schema_version: '1.0.0', ok: true, action: 'log_episode', doc_id: episode.id, path: episodePath(episode),
    commit_sha: hash(episode.id).toString(16).padStart(8, '0').slice(0, 7), conflict: null,
    message: `session ${id} promoted to episode`,
  }
}

// ---------------------------------------------------------------- router

/**
 * Serve one mocked REST call.
 *
 * Behavior:
 *     Matches the §7.14 routes; anything else is a 404 `ApiError`.
 * Exceptions:
 *     ApiError: validation (400), missing (404) or conflict (409) errors.
 * Returns:
 *     The response body, shaped like the real endpoint's JSON.
 * Parameters:
 *     method: HTTP method.
 *     url: Path relative to `/api`, with an optional query string.
 *     body: JSON body, or `FormData` for `POST /imports`.
 */
export async function mockRequest(method: string, url: string, body?: unknown): Promise<unknown> {
  await latency()
  const [path, qs] = url.split('?')
  const query = new URLSearchParams(qs ?? '')
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent)
  const route = `${method} /${parts[0] ?? ''}`

  switch (route) {
    case 'GET /health':
      return { ok: true, vault: '/vault', index_ok: true } satisfies Health
    case 'POST /imports': {
      const form = body as FormData
      const file = form.get('file')
      if (!(file instanceof File)) throw invalid('file: required')
      const job: Job = {
        id: `job_${seedUuid(`${file.name}:${Date.now()}`).slice(0, 8)}`,
        startedAt: Date.now(),
        source: detectSource(file.name, form.get('source') as string | null),
        fileName: file.name,
        report: null,
      }
      jobs.set(job.id, job)
      return jobStatus(job)
    }
    case 'GET /imports': {
      const job = jobs.get(parts[1] ?? '')
      if (!job) throw notFound(`import job '${parts[1]}'`)
      return jobStatus(job)
    }
    case 'GET /vault':
      if (parts[1] === 'tree') return vaultTree(query.get('agent'))
      if (parts[1] === 'file') return vaultFile(query.get('path'))
      break
    case 'POST /search':
      return search(body as SearchQuery)
    case 'POST /context':
      return buildContext(body as ContextRequest)
    case 'GET /graph':
      return buildGraph(query.get('agent'), query.get('facts') === 'true')
    case 'GET /agents':
      if (parts[1]) {
        const manifest = agentOrDefault(parts[1])
        return { manifest, persona: personaFor(manifest.name) }
      }
      return world.agents
    case 'POST /agents':
      return upsertAgent(body as AgentUpsert, null)
    case 'PUT /agents':
      return upsertAgent(body as AgentUpsert, parts[1] ?? '')
    case 'GET /models':
      return MODELS
    case 'GET /sessions':
      return getSession(parts[1] ?? '')
    case 'POST /sessions':
      if (parts[2] === 'end') return endSession(parts[1] ?? '')
      break
    case 'POST /sync':
    case 'GET /sync':
      return { schema_version: '1.0.0', dirty_paths: [], reindexed: 0, commit_sha: null } satisfies SyncReport
  }
  throw notFound(`route ${method} ${path}`)
}

// ---------------------------------------------------------------- chat

function compose(session: WorkingMemory, message: string, bundle: ContextBundle, modelLabel: string): string {
  const project = bundle.projects[0]
  const priorAssistant = (session.recent_turns ?? []).filter((t) => t.role === 'assistant')
  const conflict = bundle.conflicts[0]
  if (!project) {
    return `I don't have any memories for this agent yet. Import an export first, then ask me again.`
  }
  const notes = world.projects.find((p) => p.id === project.id)?.notes ?? []
  const decisions = notes.filter((n) => !n.startsWith('Next'))
  const next = notes.find((n) => n.startsWith('Next'))?.replace(/^Next:\s*/, '') ?? 'pick the next open item'
  const latest = bundle.episodes[0]
  if (priorAssistant.length === 0) {
    return [
      `You were working on **${project.name}**.`,
      '',
      `**Where you left off:** ${latest ? `"${latest.title}" (${latest.created_at.slice(0, 10)}). ${world.episodes.find((e) => e.id === latest.episode_id)?.summary ?? ''}` : project.summary}`,
      '',
      '**Decisions so far**',
      ...decisions.map((d) => `- ${d}`),
      '',
      '**Next steps**',
      `1. ${next[0].toUpperCase()}${next.slice(1)}.`,
      `2. Re-read "${latest?.title ?? project.name}" for open questions.`,
      '3. Log the next decision so the next model sees it too.',
      ...(conflict ? ['', `⚠ One thing to confirm: is your vector store **${conflict.value}** or **${conflict.conflict?.candidate_value}**? Your history says both.`] : []),
    ].join('\n')
  }
  const previous = priorAssistant.at(-1)!.text.split('\n')[0].replace(/\*\*/g, '')
  return [
    `Continuing from earlier in this session (${previous.toLowerCase().replace(/\.$/, '')}).`,
    '',
    `For "${message.slice(0, 80)}" on **${project.name}**:`,
    '',
    `1. Start from the last step: ${next}.`,
    '2. Keep the context panel visible so the token savings show during the demo.',
    '3. After that, end the session so this chat is saved as an episode.',
    '',
    `_${modelLabel} picked this up from working memory; no history was replayed._`,
  ].join('\n')
}

/**
 * Stream one mocked chat turn.
 *
 * Behavior:
 *     Validates the model (400 before streaming), loads or creates the session,
 *     records a model switch and the user turn, emits `context` (plus a
 *     `tool_call` in tool mode), streams the answer as tokens and ends with one
 *     `done`. A message containing `/fail` ends with a retryable `error` after a
 *     few tokens and records no assistant turn.
 * Exceptions:
 *     ApiError: unknown model (400), unknown agent or session (404), ended session (409).
 * Parameters:
 *     req: The chat request.
 *     emit: Receives each event.
 *     signal: Stops the stream early.
 */
export async function mockChatStream(req: ChatRequest, emit: (e: ChatEvent) => void, signal?: AbortSignal): Promise<void> {
  await latency()
  const model = MODELS.find((m) => m.id === req.model)
  if (!model) throw invalid(`model: '${req.model}' is not configured in pam.toml`)
  if (!req.message?.trim()) throw invalid('message: must not be empty')
  if (req.mode === 'tool' && !model.supports_tools) throw invalid(`model '${model.id}' does not support tools`)
  const agent = agentOrDefault(req.agent)

  let session: WorkingMemory
  if (req.session_id) {
    session = getSession(req.session_id)
    if (session.status === 'ended') throw new ApiError(409, 'SESSION_ENDED', `session ${req.session_id} has ended`)
  } else {
    session = {
      schema_version: '1.0.0', session_id: newSessionId(), agent: agent.name, status: 'active',
      started_at: now(), updated_at: now(), models_used: [], goal: null, decisions: [], open_questions: [],
      recent_turns: [], promoted_episode_id: null,
    }
    world.sessions.set(session.session_id, session)
  }
  const switches = session.models_used ?? (session.models_used = [])
  const current = switches.at(-1)?.to_model ?? null
  if (current !== model.id) switches.push({ at: now(), from_model: current, to_model: model.id })
  const remember = (role: 'user' | 'assistant', text: string) => {
    session.recent_turns = [...(session.recent_turns ?? []), { role, text, created_at: now(), attachments: [] }].slice(-8)
    session.updated_at = now()
  }
  const history = { ...session, recent_turns: [...(session.recent_turns ?? [])] }
  remember('user', req.message)
  session.goal ??= req.message.slice(0, 200)

  const bundle = buildContext({ query: req.message, agent: agent.name, session_id: session.session_id })
  const tool = req.mode === 'tool'
  emit({
    type: 'context', session_id: session.session_id,
    tokens_used: tool ? tokensOf(bundle.persona?.identity ?? '') : bundle.tokens_used,
    baseline_tokens: tool ? 0 : bundle.baseline_tokens,
    tokens_saved: tool ? 0 : bundle.tokens_saved,
    doc_ids: tool ? [] : [...bundle.projects.map((p) => p.id), ...bundle.episodes.map((e) => e.episode_id)],
    rendered: tool ? `# Agent persona\n${bundle.persona?.identity ?? ''}` : bundle.rendered,
  })
  await sleep(250, signal)
  if (signal?.aborted) return
  if (tool) {
    emit({
      type: 'tool_call', name: 'get_context', arguments: { query: req.message, session_id: session.session_id },
      result_summary: `${bundle.projects.length} projects, ${bundle.facts.length} facts, ${bundle.episodes.length} snippets · ${bundle.tokens_used} tokens`,
    })
    await sleep(300, signal)
  }

  const fail = req.message.includes('/fail')
  const answer = compose(history, req.message, bundle, model.label)
  const pieces = answer.match(/\S+\s*|\s+/g) ?? []
  let sent = 0
  for (const piece of pieces) {
    if (signal?.aborted) return
    emit({ type: 'token', text: piece })
    sent++
    if (fail && sent === 6) {
      emit({ type: 'error', message: `${model.id}: 429 rate limited by provider, try again or switch models`, retryable: true })
      return
    }
    await sleep(18 + Math.random() * 30, signal)
  }
  remember('assistant', answer)
  emit({
    type: 'done', session_id: session.session_id, model: model.id,
    prompt_tokens: bundle.tokens_used + tokensOf(req.message) + 120, completion_tokens: tokensOf(answer),
  })
}
