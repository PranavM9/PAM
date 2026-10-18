import { ArrowLeft, ArrowRight, Clock } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Markdown } from '../components/Markdown'
import { PageHeader } from '../components/PageHeader'
import { ResizeHandle } from '../components/Resizable'
import { usePaneSize } from '../lib/usePaneSize'
import { GuideNav } from '../components/guides/GuideNav'
import { guideKind } from '../components/guides/guideKind'
import { guides } from '../guides'
import { cliHints } from '../lib/cliHints'

/**
 * Guides page: list of `src/guides/*.md` and the selected guide in `prose`.
 *
 * Behavior:
 *     The selected guide is kept in the URL (`?g=<slug>`); the first guide is
 *     shown by default. The guide list is a glass nav beside the article on
 *     wide screens and above it on narrow ones. The article sits in one glass
 *     panel at a comfortable reading measure, with links to the previous and
 *     next guide, and scrolls back to the top when the guide changes.
 */
export default function GuidesPage() {
  const navPane = usePaneSize({ id: 'guides-nav', initial: 288, min: 220, max: 420 })
  const [params, setParams] = useSearchParams()
  const selected = guides.find((g) => g.slug === params.get('g')) ?? guides[0]
  const index = selected ? guides.indexOf(selected) : -1
  const prev = index > 0 ? guides[index - 1] : undefined
  const next = index >= 0 && index < guides.length - 1 ? guides[index + 1] : undefined
  const scroller = useRef<HTMLDivElement>(null)
  const page = useRef<HTMLDivElement>(null)

  const select = (slug: string) => setParams({ g: slug })

  useEffect(() => {
    scroller.current?.scrollTo({ top: 0 })
    page.current?.scrollTo({ top: 0 })
  }, [selected?.slug])

  const minutes = selected ? Math.max(1, Math.round(selected.body.split(/\s+/).length / 200)) : 0
  const kind = selected ? guideKind(selected.slug) : undefined

  return (
    <div ref={page} className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:overflow-hidden">
      <PageHeader
        title="Guides"
        cli={cliHints.mcpServe()}
      />
      <div className="flex flex-col gap-3 lg:min-h-0 lg:flex-1 lg:flex-row lg:gap-0">
        <GuideNav guides={guides} selected={selected?.slug} onSelect={select} style={navPane.style} />
        <ResizeHandle pane={navPane} side="before" label="Resize guide list" />
        <article className="panel flex min-w-0 flex-col lg:min-h-0 lg:flex-1">
          <div ref={scroller} className="px-5 py-6 sm:px-10 sm:py-10 lg:min-h-0 lg:flex-1 lg:overflow-auto">
            {selected && kind ? (
              <div key={selected.slug} className="enter mx-auto max-w-[68ch]">
                <div className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
                  <span className="eyebrow text-[13px]">{kind.label}</span>
                  <span className="h-1 w-1 rounded-full bg-muted/50" aria-hidden />
                  <span className="inline-flex items-center gap-1.5 text-muted">
                    <Clock size={13} strokeWidth={1.75} aria-hidden />
                    {minutes} min read
                  </span>
                </div>
                <Markdown className="scroll-reveal prose-base leading-relaxed [&_h1]:mb-4 [&_h1]:text-[28px] [&_h1]:leading-tight sm:[&_h1]:text-[32px] [&_h2]:mt-10 [&_h2]:text-[19px] [&_pre]:text-[13px] [&_table]:block [&_table]:overflow-x-auto [&_pre]:max-w-full">
                  {selected.body}
                </Markdown>
                {(prev || next) && (
                  <div className="divider mt-12 grid gap-3 border-t pt-6 sm:grid-cols-2">
                    {prev ? (
                      <button type="button" onClick={() => select(prev.slug)} className="well group flex flex-col items-start gap-1 rounded-card px-4 py-3 text-left transition duration-200 ease-out hover:bg-fg/[0.07]">
                        <span className="inline-flex items-center gap-1.5 text-[13px] text-muted">
                          <ArrowLeft size={14} strokeWidth={1.75} className="transition duration-200 ease-out" aria-hidden />
                          Previous
                        </span>
                        <span className="text-sm font-medium text-fg">{prev.title}</span>
                      </button>
                    ) : (
                      <span className="hidden sm:block" />
                    )}
                    {next && (
                      <button type="button" onClick={() => select(next.slug)} className="well group flex flex-col items-end gap-1 rounded-card px-4 py-3 text-right transition duration-200 ease-out hover:bg-fg/[0.07]">
                        <span className="inline-flex items-center gap-1.5 text-[13px] text-muted">
                          Next
                          <ArrowRight size={14} strokeWidth={1.75} className="transition duration-200 ease-out" aria-hidden />
                        </span>
                        <span className="text-sm font-medium text-fg">{next.title}</span>
                      </button>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-muted">No guides found.</p>
            )}
          </div>
        </article>
      </div>
    </div>
  )
}
