import { ArrowUpRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { SearchHit } from '../../types/generated'

/**
 * Ranked list of search hits separated by hairlines.
 *
 * Parameters:
 *     hits: Hits in rank order, as returned by `POST /search`.
 */
export function HitList({ hits }: { hits: SearchHit[] }) {
  return (
    <ol className="stagger divide-y divide-edge/[0.07]">
      {hits.map((hit, i) => (
        <li key={hit.chunk_id}>
          <HitRow hit={hit} position={i + 1} />
        </li>
      ))}
    </ol>
  )
}

/**
 * One search hit: rank, linked title, type, rank badges, snippet and source path.
 *
 * Behavior:
 *     The title links to the hit's file in the vault browser. Badges show the
 *     fused score and the vector and keyword ranks, with "—" for a missing rank.
 * Parameters:
 *     hit: The hit to show.
 *     position: 1-based rank in the result list.
 */
function HitRow({ hit, position }: { hit: SearchHit; position: number }) {
  return (
    <article className="group -mx-3 flex gap-4 rounded-card px-3 py-4 transition duration-200 ease-out hover:bg-edge/[0.04] sm:-mx-4 sm:px-4">
      <span
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-xs font-medium tabular-nums text-accent"
        aria-label={`Rank ${position}`}
      >
        {position}
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
          <div className="flex min-w-0 flex-1 basis-[14rem] items-center gap-2">
            <Link
              to={`/vault?path=${encodeURIComponent(hit.path)}`}
              className="min-w-0 break-words text-[15px] font-medium leading-snug text-fg transition duration-200 ease-out hover:text-accent"
            >
              {hit.title ?? hit.path}
            </Link>
            <ArrowUpRight size={14} strokeWidth={1.75} className="shrink-0 -translate-x-1 translate-y-1 text-accent opacity-0 transition duration-300 ease-[var(--ease-spring)] group-hover:translate-x-0 group-hover:translate-y-0 group-hover:opacity-100" aria-hidden />
            <span className="badge shrink-0 font-sans">{hit.doc_type}</span>
          </div>
          <span className="flex shrink-0 gap-1.5">
            <span className="badge border-accent/30 bg-accent/10 text-fg" title="Fused score (higher is better)">
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
        <p className="line-clamp-3 text-sm leading-relaxed text-fg/80">{hit.snippet}</p>
        <div className="truncate font-mono text-[11px] text-muted" title={hit.path}>
          {hit.scope} · {hit.path}
          {hit.created_at && ` · ${hit.created_at.slice(0, 10)}`}
        </div>
      </div>
    </article>
  )
}
