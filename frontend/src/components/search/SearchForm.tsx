import { Layers, Loader2, Search } from 'lucide-react'
import { AgentSelect } from '../AgentSelect'

/**
 * Search form: a large glass query field with secondary agent, k and budget controls.
 *
 * Behavior:
 *     Submitting the form (Enter or the "Search" button) calls `onSearch`. The
 *     "Build context" button calls `onBuild`. Both buttons are disabled while the
 *     query is blank or their request is pending, and show a spinner when pending.
 *     `k` is clamped to 1–50; an empty or invalid budget falls back to 2000.
 * Parameters:
 *     query: Current query text.
 *     onQuery: Called with the new query text.
 *     agent: Selected agent name.
 *     onAgent: Called with the new agent name.
 *     k: Number of hits to request.
 *     onK: Called with the new `k`.
 *     budget: Token budget for "Build context".
 *     onBudget: Called with the new budget.
 *     searching: Whether a search request is pending.
 *     building: Whether a context request is pending.
 *     onSearch: Runs the search.
 *     onBuild: Builds the context bundle.
 */
export function SearchForm({
  query,
  onQuery,
  agent,
  onAgent,
  k,
  onK,
  budget,
  onBudget,
  searching,
  building,
  onSearch,
  onBuild,
}: {
  query: string
  onQuery: (value: string) => void
  agent: string
  onAgent: (value: string) => void
  k: number
  onK: (value: number) => void
  budget: number
  onBudget: (value: number) => void
  searching: boolean
  building: boolean
  onSearch: () => void
  onBuild: () => void
}) {
  const blank = !query.trim()
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        onSearch()
      }}
    >
      <div className="glass-strong flex items-center gap-2 rounded-[18px] py-1.5 pl-4 pr-1.5 transition duration-200 ease-out focus-within:border-accent/60">
        <Search size={20} strokeWidth={1.75} className="shrink-0 text-muted" aria-hidden />
        <input
          className="min-h-[2.75rem] min-w-0 flex-1 bg-transparent text-base text-fg outline-none placeholder:text-muted/80 sm:text-[17px]"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="e.g. sqlite-vec hybrid search"
          aria-label="Query"
        />
        <button type="submit" className="btn btn-solid min-h-[2.75rem] shrink-0 rounded-[14px] px-4" disabled={blank || searching}>
          {searching ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Search size={16} strokeWidth={2} aria-hidden />} Search
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-[9rem] flex-1 flex-col gap-1.5 sm:flex-none">
          <span className="label">Agent</span>
          <AgentSelect value={agent} onChange={onAgent} />
        </label>
        <label className="flex w-20 flex-col gap-1.5">
          <span className="label">Hits (k)</span>
          <input
            className="input tabular-nums"
            type="number"
            min={1}
            max={50}
            value={k}
            onChange={(e) => onK(Math.max(1, Math.min(50, Number(e.target.value) || 8)))}
          />
        </label>
        <label className="flex w-28 flex-col gap-1.5">
          <span className="label">Token budget</span>
          <input
            className="input tabular-nums"
            type="number"
            min={256}
            max={32000}
            step={1}
            value={budget}
            onChange={(e) => onBudget(Number(e.target.value) || 2000)}
          />
        </label>
        <button type="button" className="btn ml-auto" disabled={blank || building} onClick={onBuild}>
          {building ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Layers size={16} strokeWidth={1.75} aria-hidden />} Build context
        </button>
      </div>
    </form>
  )
}
