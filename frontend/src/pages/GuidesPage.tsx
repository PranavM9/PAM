import { useSearchParams } from 'react-router-dom'
import { Markdown } from '../components/Markdown'
import { PageHeader } from '../components/PageHeader'
import { guides } from '../guides'
import { cliHints } from '../lib/cliHints'

/**
 * Guides page: list of `src/guides/*.md` and the selected guide in `prose`.
 *
 * Behavior:
 *     The selected guide is kept in the URL (`?g=<slug>`); the first guide is
 *     shown by default.
 */
export default function GuidesPage() {
  const [params, setParams] = useSearchParams()
  const selected = guides.find((g) => g.slug === params.get('g')) ?? guides[0]
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="Guides"
        subtitle="How to export from each provider and connect MCP clients."
        cli={cliHints.mcpServe()}
      />
      <div className="flex min-h-0 flex-1">
        <nav aria-label="Guides" className="w-64 shrink-0 overflow-auto border-r border-line p-3">
          <ul className="space-y-0.5">
            {guides.map((g) => (
              <li key={g.slug}>
                <button
                  type="button"
                  onClick={() => setParams({ g: g.slug })}
                  aria-current={g.slug === selected?.slug ? 'page' : undefined}
                  className={`w-full rounded-md px-3 py-2 text-left text-sm ${
                    g.slug === selected?.slug ? 'bg-accent/15 font-medium' : 'text-muted hover:bg-raised hover:text-fg'
                  }`}
                >
                  {g.title}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <article className="min-w-0 flex-1 overflow-auto px-8 py-6">
          {selected ? <Markdown className="max-w-3xl">{selected.body}</Markdown> : <p className="text-muted">No guides found.</p>}
        </article>
      </div>
    </div>
  )
}
