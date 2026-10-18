import { useMutation } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { CliHint } from '../components/CliHint'
import { ErrorNote } from '../components/ErrorNote'
import { PageHeader } from '../components/PageHeader'
import { ResizeHandle } from '../components/Resizable'
import { usePaneSize } from '../lib/usePaneSize'
import { ContextPanel } from '../components/search/ContextPanel'
import { HitList } from '../components/search/HitList'
import { SearchForm } from '../components/search/SearchForm'
import { cliHints } from '../lib/cliHints'

/**
 * Search playground: hybrid search hits with rank badges, and context bundles.
 *
 * Behavior:
 *     "Search" posts a `SearchQuery`; each hit shows its fused score and its
 *     vector and keyword ranks. "Build context" posts a `ContextRequest` with the
 *     same query, agent and budget and opens the `ContextBundle` in a side panel,
 *     which sits below the results on narrow screens and is scrolled into view.
 */
export default function SearchPage() {
  const bundlePane = usePaneSize({ id: 'search-bundle', initial: 416, min: 320, max: 640 })
  const [query, setQuery] = useState('')
  const [agent, setAgent] = useState('default')
  const [k, setK] = useState(8)
  const [budget, setBudget] = useState(2000)
  const search = useMutation({ mutationFn: api.search })
  const context = useMutation({ mutationFn: api.context })
  const bundle = context.data
  const panelRef = useRef<HTMLElement>(null)

  const run = () => {
    if (query.trim()) search.mutate({ query: query.trim(), agent, k })
  }
  const build = () => {
    if (query.trim()) context.mutate({ query: query.trim(), agent, token_budget: budget })
  }

  useEffect(() => {
    if ((bundle || context.error) && window.matchMedia('(max-width: 1279px)').matches) {
      panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [bundle, context.error])

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto xl:overflow-hidden">
      <PageHeader
        title="Search"
        subtitle="Hybrid search (vector + keyword, fused with RRF) and the token-budgeted context bundle an agent would get."
        cli={cliHints.search(query || undefined, agent, k)}
      />
      <div className="flex flex-col gap-4 pb-2 xl:min-h-0 xl:flex-1 xl:flex-row xl:gap-0">
        <section className="panel flex min-w-0 flex-col xl:min-h-0 xl:flex-1" aria-label="Search">
          <div className="space-y-4 p-5 sm:p-7">
            <SearchForm
              query={query}
              onQuery={setQuery}
              agent={agent}
              onAgent={setAgent}
              k={k}
              onK={setK}
              budget={budget}
              onBudget={setBudget}
              searching={search.isPending}
              building={context.isPending}
              onSearch={run}
              onBuild={build}
            />
            <CliHint label="Context" command={cliHints.context(query || undefined, budget, agent)} />
          </div>
          <div className="mx-5 border-t divider sm:mx-7" />
          <div className="min-h-0 flex-1 space-y-3 px-5 pb-5 pt-4 sm:px-7 sm:pb-7 xl:overflow-auto">
            <ErrorNote error={search.error} />
            {search.data && (
              <p className="text-[13px] text-muted">
                <span className="tabular-nums text-fg">{search.data.hits.length}</span> hits for “{search.data.query}” as{' '}
                <span className="font-mono text-fg/90">{search.data.agent}</span> in{' '}
                <span className="tabular-nums">{search.data.took_ms}</span> ms
              </p>
            )}
            {search.data?.hits.length === 0 && <p className="py-6 text-sm text-muted">No hits in this agent's scope.</p>}
            {search.data && search.data.hits.length > 0 && <HitList hits={search.data.hits} />}
            {!search.data && !search.error && (
              <div className="flex flex-col items-center gap-3 py-12 text-center sm:py-16">
                <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent/15 text-accent">
                  <Search size={22} strokeWidth={1.75} aria-hidden />
                </span>
                <p className="max-w-xs text-sm leading-relaxed text-muted">Search your vault to see how hits are ranked.</p>
              </div>
            )}
          </div>
        </section>

        {(bundle || context.error) && (
          <>
            <ResizeHandle pane={bundlePane} side="after" label="Resize context bundle" breakpoint="xl" />
            <ContextPanel ref={panelRef} style={bundlePane.style} bundle={bundle} error={context.error} onClose={() => context.reset()} />
          </>
        )}
      </div>
    </div>
  )
}
