import { useMutation } from '@tanstack/react-query'
import { Layers, Loader2, Search, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { AgentSelect } from '../components/AgentSelect'
import { CliHint } from '../components/CliHint'
import { ErrorNote } from '../components/ErrorNote'
import { Markdown } from '../components/Markdown'
import { PageHeader } from '../components/PageHeader'
import { TokenMeter } from '../components/TokenMeter'
import { cliHints } from '../lib/cliHints'
import type { ContextBundle, SearchHit } from '../types/generated'

/**
 * Search playground: hybrid search hits with rank badges, and context bundles.
 *
 * Behavior:
 *     "Search" posts a `SearchQuery`; each hit shows its fused score and its
 *     vector and keyword ranks. "Build context" posts a `ContextRequest` with the
 *     same query, agent and budget and opens the `ContextBundle` beside the hits.
 */
export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [agent, setAgent] = useState('default')
  const [k, setK] = useState(8)
  const [budget, setBudget] = useState(2000)
  const search = useMutation({ mutationFn: api.search })
  const context = useMutation({ mutationFn: api.context })
  const bundle = context.data

  const run = () => {
    if (query.trim()) search.mutate({ query: query.trim(), agent, k })
  }
  const build = () => {
    if (query.trim()) context.mutate({ query: query.trim(), agent, token_budget: budget })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="Search"
        subtitle="Hybrid search (vector + keyword, fused with RRF) and the token-budgeted context bundle an agent would get."
        cli={cliHints.search(query || undefined, agent, k)}
      />
      <div className="flex min-h-0 flex-1">
        <section className="flex min-w-0 flex-1 flex-col" aria-label="Search">
          <form
            className="flex flex-wrap items-end gap-3 border-b border-line px-6 py-4"
            onSubmit={(e) => {
              e.preventDefault()
              run()
            }}
          >
            <label className="flex min-w-[16rem] flex-1 flex-col gap-1">
              <span className="label">Query</span>
              <input
                className="input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g. sqlite-vec hybrid search"
                aria-label="Query"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="label">Agent</span>
              <AgentSelect value={agent} onChange={setAgent} />
            </label>
            <label className="flex w-20 flex-col gap-1">
              <span className="label">k</span>
              <input
                className="input"
                type="number"
                min={1}
                max={50}
                value={k}
                onChange={(e) => setK(Math.max(1, Math.min(50, Number(e.target.value) || 8)))}
              />
            </label>
            <label className="flex w-28 flex-col gap-1">
              <span className="label">Budget</span>
              <input
                className="input"
                type="number"
                min={256}
                max={32000}
                step={256}
                value={budget}
                onChange={(e) => setBudget(Number(e.target.value) || 2000)}
              />
            </label>
            <button type="submit" className="btn btn-primary" disabled={!query.trim() || search.isPending}>
              {search.isPending ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />} Search
            </button>
            <button type="button" className="btn" disabled={!query.trim() || context.isPending} onClick={build}>
              {context.isPending ? <Loader2 size={14} className="animate-spin" /> : <Layers size={14} />} Build context
            </button>
          </form>
          <div className="min-h-0 flex-1 space-y-3 overflow-auto px-6 py-4">
            <CliHint label="Context" command={cliHints.context(query || undefined, budget, agent)} />
            <ErrorNote error={search.error} />
            {search.data && (
              <p className="text-xs text-muted">
                {search.data.hits.length} hits for “{search.data.query}” as <span className="font-mono">{search.data.agent}</span> in{' '}
                {search.data.took_ms} ms
              </p>
            )}
            {search.data?.hits.length === 0 && <p className="text-sm text-muted">No hits in this agent's scope.</p>}
            <ol className="space-y-2">
              {search.data?.hits.map((hit, i) => (
                <li key={hit.chunk_id}>
                  <HitCard hit={hit} position={i + 1} />
                </li>
              ))}
            </ol>
            {!search.data && !search.error && (
              <p className="pt-10 text-center text-sm text-muted">Search your vault to see how hits are ranked.</p>
            )}
          </div>
        </section>

        {(bundle || context.error) && (
          <aside aria-label="Context bundle" className="flex w-[28rem] shrink-0 flex-col border-l border-line bg-panel/50">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <h2 className="font-semibold">Context bundle</h2>
              <button type="button" className="rounded p-1 text-muted hover:text-fg" onClick={() => context.reset()} aria-label="Close context bundle">
                <X size={18} />
              </button>
            </div>
            <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
              <ErrorNote error={context.error} />
              {bundle && <BundleView bundle={bundle} />}
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}

function HitCard({ hit, position }: { hit: SearchHit; position: number }) {
  return (
    <article className="card space-y-1.5 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs tabular-nums text-muted">#{position}</span>
        <Link to={`/vault?path=${encodeURIComponent(hit.path)}`} className="font-medium hover:text-accent">
          {hit.title ?? hit.path}
        </Link>
        <span className="badge">{hit.doc_type}</span>
        <span className="ml-auto flex gap-1.5">
          <span className="badge border-accent/40 text-fg" title="Fused score (higher is better)">
            score {hit.score.toFixed(4)}
          </span>
          <span className="badge" title="Rank among vector candidates">
            vec {hit.vector_rank ?? '—'}
          </span>
          <span className="badge" title="Rank among keyword (FTS5) candidates">
            kw {hit.keyword_rank ?? '—'}
          </span>
        </span>
      </div>
      <p className="line-clamp-3 text-sm text-fg/80">{hit.snippet}</p>
      <div className="font-mono text-[11px] text-muted">
        {hit.scope} · {hit.path}
        {hit.created_at && ` · ${hit.created_at.slice(0, 10)}`}
      </div>
    </article>
  )
}

/**
 * Summary of a `ContextBundle`: token meter, item counts and rendered Markdown.
 *
 * Parameters:
 *     bundle: The bundle returned by `POST /context`.
 */
function BundleView({ bundle }: { bundle: ContextBundle }) {
  const counts = [
    ['persona', bundle.persona ? 1 : 0],
    ['conflicts', bundle.conflicts.length],
    ['working', bundle.working ? 1 : 0],
    ['facts', bundle.facts.length],
    ['projects', bundle.projects.length],
    ['snippets', bundle.episodes.length],
  ] as const
  return (
    <div className="space-y-4">
      <TokenMeter used={bundle.tokens_used} baseline={bundle.baseline_tokens} saved={bundle.tokens_saved} budget={bundle.token_budget} />
      <dl className="grid grid-cols-3 gap-2 text-center text-xs">
        {counts.map(([label, value]) => (
          <div key={label} className="rounded-md bg-raised/60 px-2 py-1.5">
            <dd className="text-base font-semibold tabular-nums">{value}</dd>
            <dt className="text-muted">{label}</dt>
          </div>
        ))}
      </dl>
      <CliHint command={cliHints.context(bundle.query, bundle.token_budget, bundle.agent)} />
      <div className="text-[11px] text-muted">
        {bundle.tokenizer ?? 'cl100k_base'} · generated {bundle.generated_at}
      </div>
      <div className="rounded-md border border-line p-3">
        <Markdown className="prose-compact text-xs">{bundle.rendered}</Markdown>
      </div>
    </div>
  )
}
