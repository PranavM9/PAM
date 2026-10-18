/**
 * Deterministic in-memory vault used by the mock API.
 *
 * Behavior:
 *     Holds seed projects, episodes, facts, agents and sessions. A base set
 *     (an earlier ChatGPT import) exists from the start; the Claude export used in
 *     the §3.3 demo is added when a mock import job finishes, so the graph grows.
 *     All IDs and dates derive from fixed seeds, so every reload looks the same.
 */
import type {
  AgentManifest,
  Fact,
  ModelEntry,
  Persona,
  RawMessage,
  Source,
  WorkingMemory,
} from '../../types/generated'

/** Seed episode, rendered into contract shapes by the handlers. */
export interface SeedEpisode {
  id: string
  title: string
  source: Source
  createdAt: string
  projectId: string | null
  summary: string
  turns: RawMessage[]
}

/** Seed project, rendered into contract shapes by the handlers. */
export interface SeedProject {
  id: string
  name: string
  keywords: string[]
  summary: string
  notes: string[]
  status: 'active' | 'dormant'
  source: Source
}

interface ProjectSpec {
  name: string
  keywords: string[]
  status: 'active' | 'dormant'
  source: Source
  start: string
  notes: string[]
  episodes: [string, string, string][]
}

/** Stable FNV-1a hash of a string. */
export function hash(text: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

/** Deterministic UUID-shaped id from a seed string. */
export function seedUuid(seed: string): string {
  let hex = ''
  for (let i = 0; hex.length < 32; i++) hex += hash(`${seed}#${i}`).toString(16).padStart(8, '0')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`
}

/** Small seeded PRNG (mulberry32). */
export function rng(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function addMinutes(iso: string, minutes: number): string {
  return new Date(new Date(iso).getTime() + minutes * 60_000).toISOString().replace('.000Z', 'Z')
}

const BASE_PROJECTS: ProjectSpec[] = [
  {
    name: 'Home lab k3s cluster',
    keywords: ['k3s', 'raspberry-pi', 'traefik', 'longhorn', 'homelab'],
    status: 'dormant',
    source: 'chatgpt',
    start: '2026-06-02T19:10:00Z',
    notes: ['Longhorn needs open-iscsi on every node'],
    episodes: [
      ['Flashing Pi OS for a 3-node k3s cluster', 'Picked Ubuntu Server 24.04 over Raspberry Pi OS for cgroup support.', 'How do I set up k3s on three Raspberry Pis?'],
      ['Traefik ingress with wildcard certs', 'Configured Traefik with a DNS-01 challenge through Cloudflare.', 'Traefik keeps serving the default cert, what am I missing?'],
      ['Longhorn volumes stuck attaching', 'Root cause: open-iscsi missing on worker nodes.', 'My Longhorn PVCs are stuck in attaching.'],
      ['Backing up etcd snapshots to S3', 'Scheduled k3s etcd snapshots every 6 hours to Backblaze B2.', 'How do I back up the k3s datastore?'],
    ],
  },
  {
    name: 'Job search 2026',
    keywords: ['resume', 'internship', 'interview', 'leetcode', 'cover-letter'],
    status: 'active',
    source: 'chatgpt',
    start: '2026-08-11T16:00:00Z',
    notes: ['Target: backend / infra internships, summer 2027'],
    episodes: [
      ['Tightening my resume bullets', 'Rewrote bullets to lead with impact and numbers.', 'Can you make these resume bullets punchier?'],
      ['System design: URL shortener mock interview', 'Covered hashing, base62, read-heavy caching and analytics.', 'Run a system design mock interview with me.'],
      ['Cover letter for an infra internship', 'Drafted a 250-word letter centered on the home lab work.', 'Help me write a cover letter for an infra internship.'],
      ['Behavioral answers in STAR format', 'Prepared four STAR stories (conflict, failure, leadership, ambiguity).', 'Help me prepare behavioral answers.'],
    ],
  },
]

const CLAUDE_PROJECTS: ProjectSpec[] = [
  {
    name: 'PAM: portable agent memory (DubHacks)',
    keywords: ['pam', 'memory', 'mcp', 'sqlite-vec', 'react', 'fastapi', 'hackathon'],
    status: 'active',
    source: 'claude',
    start: '2026-10-09T18:00:00Z',
    notes: [
      'Decided to use sqlite-vec + FTS5 with RRF fusion for hybrid search',
      'Decided fastembed bge-small (384-dim) instead of sentence-transformers',
      'Next: wire the SSE chat stream into the React frontend',
    ],
    episodes: [
      ['Scoping PAM for a 24 h hackathon', 'Agreed on a vault of Markdown files in git, plus an MCP server so any model can read it.', 'I want to build portable memory for AI agents at DubHacks. Help me scope it.'],
      ['Vault layout and episode format', 'One conversation = one Markdown file with YAML frontmatter; bodies are immutable and hashed.', 'How should I store conversations on disk?'],
      ['Choosing between pgvector and sqlite-vec', 'Picked sqlite-vec so the vault stays a single portable folder.', 'pgvector or sqlite-vec for a local-first app?'],
      ['Hybrid search with reciprocal rank fusion', 'Vector and FTS5 candidates fused with RRF (k=60) plus a recency boost.', 'How do I combine vector and keyword search results?'],
      ['Token budget for the context bundle', 'Fill order: persona, conflicts, working memory, facts, projects, snippets.', 'How do I keep injected context under a token budget?'],
      ['Rule-based fact extraction with spaCy', 'Regex + dependency patterns, negation and question filtering, no LLM.', 'Can I extract facts about the user without calling an LLM?'],
      ['Clustering episodes into projects', 'HDBSCAN on episode embeddings, c-TF-IDF keywords for names, stable IDs by Jaccard.', 'How do I group conversations into projects automatically?'],
      ['MCP server tool surface', 'Ten tools; tools not in the agent manifest are not advertised.', 'Which MCP tools should PAM expose?'],
      ['Hot-swapping models mid-session', 'Working memory keeps the last 8 turns so any model can continue the thread.', 'How can I switch models mid-chat without losing the thread?'],
      ['Force graph for the frontend', 'react-force-graph-2d; projects big, episodes small, similarity links between episodes.', 'What library should I use for an Obsidian-style graph?'],
      ['SSE over POST for streaming chat', 'Native EventSource is GET-only, so use @microsoft/fetch-event-source.', 'How do I stream chat tokens from FastAPI to React?'],
      ['Docker setup for Windows and macOS', 'Bake models into the image, bind-mount the vault, nginx with proxy_buffering off.', 'How do I make this run with one docker compose command?'],
      ['Writing the demo script', 'Import, graph blooms, chat, switch models, follow-up keeps going.', 'Help me plan a 4 minute demo for the judges.'],
      ['Where I stopped: wiring the chat panel', 'Context panel shows tokens used vs. a full-history replay; next is the model switch divider.', 'I ran out of messages, summarize where I am on the chat panel.'],
    ],
  },
  {
    name: 'Thesis literature review',
    keywords: ['thesis', 'retrieval', 'rag', 'survey', 'citations'],
    status: 'active',
    source: 'claude',
    start: '2026-09-14T15:00:00Z',
    notes: ['Advisor wants the related-work draft by Nov 1'],
    episodes: [
      ['Outlining the related-work chapter', 'Three threads: dense retrieval, memory-augmented agents, evaluation.', 'Help me outline my related-work chapter.'],
      ['Summarizing long-context vs. RAG papers', 'Long context helps recall but costs more; RAG wins on freshness.', 'Summarize the long-context vs. RAG debate.'],
      ['Zotero to BibTeX workflow', 'Better BibTeX with citation keys auth-year-title.', 'How do I keep BibTeX in sync with Zotero?'],
      ['Evaluation metrics for retrieval', 'Recall@k, nDCG@10 and MRR; report all three.', 'Which retrieval metrics should I report?'],
      ['Reviewer-style critique of my draft', 'Main gaps: no ablation of the recency weight, unclear baselines.', 'Critique my draft like a reviewer would.'],
    ],
  },
  {
    name: 'Rust CLI for photo dedupe',
    keywords: ['rust', 'cli', 'perceptual-hash', 'clap', 'rayon'],
    status: 'dormant',
    source: 'claude',
    start: '2026-07-20T21:00:00Z',
    notes: ['dHash with Hamming distance <= 6 works for resized copies'],
    episodes: [
      ['Perceptual hashing for near-duplicate photos', 'dHash is fast and robust to resizing; pHash for crops.', 'How do I find near-duplicate photos?'],
      ['Parallel directory walk with rayon', 'walkdir + rayon par_bridge, hashing in a thread pool.', 'How do I parallelize hashing files in Rust?'],
      ['clap derive for subcommands', 'scan, report and dedupe subcommands with a dry-run flag.', 'Help me design the CLI with clap.'],
    ],
  },
]

function buildProjects(specs: ProjectSpec[]): { projects: SeedProject[]; episodes: SeedEpisode[] } {
  const projects: SeedProject[] = []
  const episodes: SeedEpisode[] = []
  for (const spec of specs) {
    const projectId = seedUuid(`project:${spec.name}`)
    projects.push({
      id: projectId,
      name: spec.name,
      keywords: spec.keywords,
      summary: `${spec.episodes.length} conversations about ${spec.keywords.slice(0, 3).join(', ')}.`,
      notes: spec.notes,
      status: spec.status,
      source: spec.source,
    })
    spec.episodes.forEach(([title, summary, opener], i) => {
      const createdAt = addMinutes(spec.start, i * 60 * 19 + (hash(title) % 300))
      episodes.push({
        id: seedUuid(`episode:${spec.source}:${title}`),
        title,
        source: spec.source,
        createdAt,
        projectId,
        summary,
        turns: [
          { role: 'user', text: opener, created_at: createdAt },
          { role: 'assistant', text: `${summary}\n\nWant me to go deeper on any part?`, created_at: addMinutes(createdAt, 1) },
          { role: 'user', text: 'Yes, write down the decision and the next step.', created_at: addMinutes(createdAt, 6) },
          { role: 'assistant', text: `Decision: ${summary}\n\nNext step: turn this into code and test it.`, created_at: addMinutes(createdAt, 7) },
        ],
      })
    })
  }
  return { projects, episodes }
}

function loneEpisode(title: string, source: Source, createdAt: string, opener: string): SeedEpisode {
  return {
    id: seedUuid(`episode:${source}:${title}`),
    title,
    source,
    createdAt,
    projectId: null,
    summary: '',
    turns: [
      { role: 'user', text: opener, created_at: createdAt },
      { role: 'assistant', text: 'Here is a short answer.', created_at: addMinutes(createdAt, 1) },
    ],
  }
}

const NOW = '2026-10-17T20:00:00Z'

function fact(
  attribute: string,
  value: string,
  category: Fact['category'],
  sourceEpisode: string | null,
  extra: Partial<Fact> = {},
): Fact {
  return {
    schema_version: '1.0.0',
    id: seedUuid(`fact:${attribute}:${value}`),
    scope: 'shared',
    subject: 'user',
    attribute,
    value,
    cardinality: 'single',
    category,
    confidence: 0.8,
    status: 'active',
    conflict: null,
    source_episode: sourceEpisode,
    updated_by_episode: null,
    extractor: 'rule',
    pattern_id: null,
    created_at: '2026-10-10T02:00:00Z',
    updated_at: '2026-10-16T22:00:00Z',
    history: [],
    ...extra,
  }
}

const base = buildProjects(BASE_PROJECTS)
const claude = buildProjects(CLAUDE_PROJECTS)
const pamEpisodes = claude.episodes.filter((e) => e.title.includes('sqlite-vec') || e.title.includes('Scoping'))

/** Mutable mock state shared by all handlers. */
export const world = {
  claudeImported: false,
  projects: [...base.projects],
  episodes: [
    ...base.episodes,
    loneEpisode('Sourdough starter schedule', 'chatgpt', '2026-05-30T09:00:00Z', 'How often do I feed a sourdough starter?'),
    loneEpisode('Seattle to Vancouver by train', 'chatgpt', '2026-07-04T12:00:00Z', 'Is the Amtrak Cascades worth it?'),
  ],
  facts: [
    fact('studies_at', 'University of Washington', 'education', base.episodes[4].id),
    fact('location', 'Seattle', 'location', base.episodes[2].id),
    fact('prefers_language', 'TypeScript', 'preference', base.episodes[5].id),
    fact('uses_editor', 'VS Code', 'tooling', base.episodes[0].id),
    fact('goal', 'backend / infra internship for summer 2027', 'work', base.episodes[6].id),
  ],
  agents: [] as AgentManifest[],
  personas: new Map<string, Persona>(),
  customSections: new Map<string, { identity: string; rules: string; style: string }>(),
  sessions: new Map<string, WorkingMemory>(),
}

/** Facts that only exist after the Claude export is imported. */
const CLAUDE_FACTS: Fact[] = [
  fact('working_on', 'PAM, a portable memory layer for AI agents', 'project', pamEpisodes[0]?.id ?? null, { confidence: 0.9 }),
  fact('uses_framework', 'React + FastAPI', 'tooling', pamEpisodes[0]?.id ?? null, { cardinality: 'multi' }),
  fact('preferred_vector_store', 'sqlite-vec', 'preference', pamEpisodes[1]?.id ?? null, {
    status: 'conflict',
    conflict: {
      candidate_value: 'pgvector',
      candidate_source_episode: base.episodes[1].id,
      detected_at: '2026-10-16T22:00:00Z',
      detected_by: 'rule',
    },
  }),
]

/**
 * Add the Claude export's projects, episodes and facts to the mock vault.
 *
 * Behavior:
 *     Idempotent: a second call reports every conversation as skipped.
 * Returns:
 *     `[found, written]` conversation counts.
 */
export function importClaudeExport(): [number, number] {
  const found = claude.episodes.length
  if (world.claudeImported) return [found, 0]
  world.claudeImported = true
  world.projects.push(...claude.projects)
  world.episodes.push(...claude.episodes)
  world.facts.push(...CLAUDE_FACTS)
  return [found, found]
}

export const MODELS: ModelEntry[] = [
  { id: 'openrouter/meta-llama/llama-3.3-70b-instruct:free', label: 'Llama 3.3 70B (OpenRouter, free)', supports_tools: false },
  { id: 'openrouter/google/gemini-2.0-flash-exp:free', label: 'Gemini 2.0 Flash (OpenRouter, free)', supports_tools: true },
  { id: 'ollama/qwen2.5:7b', label: 'Qwen 2.5 7B (Ollama, local)', supports_tools: true },
  { id: 'anthropic/claude-sonnet-5-5', label: 'Claude Sonnet (Anthropic)', supports_tools: true },
]

export const ALL_TOOLS: AgentManifest['tools'] = [
  'get_context', 'search_memory', 'get_episode', 'list_agents', 'add_fact',
  'supersede_fact', 'log_episode', 'update_project', 'add_skill', 'update_working_memory',
]

function seedAgents() {
  const defaultAgent: AgentManifest = {
    schema_version: '1.0.0',
    name: 'default',
    display_name: 'Default',
    description: 'Sees everything; writes shared facts.',
    origin: 'derived',
    created_at: '2026-10-09T17:55:00Z',
    read: { all: true, project_ids: [], include_shared_facts: true, include_own_memory: true, include_skills_from: [] },
    write: 'shared',
    tools: [...ALL_TOOLS],
    default_model: MODELS[0].id,
    token_budget: 2000,
  }
  const research: AgentManifest = {
    schema_version: '1.0.0',
    name: 'research',
    display_name: 'Research',
    description: 'Thesis work only; never sees the job search.',
    origin: 'custom',
    created_at: '2026-10-12T10:00:00Z',
    read: {
      all: false,
      project_ids: [seedUuid('project:Thesis literature review')],
      include_shared_facts: true,
      include_own_memory: true,
      include_skills_from: [],
    },
    write: 'own',
    tools: ['get_context', 'search_memory', 'get_episode', 'add_fact', 'update_working_memory'],
    default_model: MODELS[1].id,
    token_budget: 4000,
  }
  world.agents.push(defaultAgent, research)
  world.customSections.set('default', {
    identity: 'I am a hackathon builder. Keep me focused on shipping.',
    rules: '- Ask before deleting anything in the vault.',
    style: '',
  })
  world.customSections.set('research', {
    identity: 'Academic research assistant for my thesis.',
    rules: '- Always cite the paper and year.',
    style: 'Formal, concise, no emoji.',
  })
}
seedAgents()

/** Build the `Persona` for an agent from derived rules and its Custom sections. */
export function personaFor(name: string): Persona {
  const custom = world.customSections.get(name) ?? { identity: '', rules: '', style: '' }
  const section = (derived: string, mine: string) =>
    `## Derived (auto-generated — edits here are overwritten by \`pam derive\`)\n${derived}\n\n## Custom (yours — never touched by PAM)\n${mine}`
  return {
    agent: name,
    identity: section('Student at the University of Washington, based in Seattle, building developer tools.', custom.identity),
    rules: [
      { id: 'r_1a2b3c4d', text: 'Prefer TypeScript examples over JavaScript.', origin: 'derived', evidence_count: 4, evidence_episodes: [] },
      { id: 'r_5e6f7a8b', text: 'Keep answers short; use bullet lists for steps.', origin: 'derived', evidence_count: 3, evidence_episodes: [] },
      ...custom.rules
        .split('\n')
        .map((line) => line.replace(/^\s*-\s*/, '').trim())
        .filter(Boolean)
        .map((text) => ({ id: `r_${hash(text).toString(16).padStart(8, '0')}`, text, origin: 'manual' as const, evidence_count: 0, evidence_episodes: [] })),
    ],
    style: section('Direct and technical. Code first, explanation second.', custom.style),
  }
}

export { NOW }
