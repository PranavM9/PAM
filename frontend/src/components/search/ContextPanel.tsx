import { X } from 'lucide-react'
import { forwardRef, type CSSProperties } from 'react'
import { cliHints } from '../../lib/cliHints'
import type { ContextBundle } from '../../types/generated'
import { CliHint } from '../CliHint'
import { ErrorNote } from '../ErrorNote'
import { Markdown } from '../Markdown'
import { TokenMeter } from '../TokenMeter'

/**
 * Glass side panel holding a built context bundle or the error from building it.
 *
 * Behavior:
 *     Beside the results from `xl` up, where its body scrolls on its own; below
 *     `xl` it is a full-width section under the results. The close button calls
 *     `onClose`.
 * Parameters:
 *     bundle: The bundle from `POST /context`, if any.
 *     error: The error from `POST /context`, if any.
 *     onClose: Hides the panel.
 *     style: Inline style; sets `--pane-w`, the width from `xl` up.
 */
export const ContextPanel = forwardRef<HTMLElement, { bundle?: ContextBundle; error: unknown; onClose: () => void; style?: CSSProperties }>(
  function ContextPanel({ bundle, error, onClose, style }, ref) {
    return (
      <aside
        ref={ref}
        aria-label="Context bundle"
        style={style}
        className="panel flex shrink-0 scroll-mt-4 flex-col xl:min-h-0 xl:w-[var(--pane-w)]"
      >
        <div className="flex items-center justify-between gap-3 px-5 pb-2 pt-5 sm:px-6">
          <div>
            <h2 className="text-[17px] font-semibold tracking-[-0.01em]">Context bundle</h2>
            {bundle && <p className="text-[13px] text-muted">What {bundle.agent} would receive</p>}
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close context bundle">
            <X size={18} strokeWidth={1.75} />
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-5 px-5 pb-6 pt-3 sm:px-6 xl:overflow-auto">
          <ErrorNote error={error} />
          {bundle && <BundleView bundle={bundle} />}
        </div>
      </aside>
    )
  },
)

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
    <>
      <TokenMeter used={bundle.tokens_used} baseline={bundle.baseline_tokens} saved={bundle.tokens_saved} budget={bundle.token_budget} />
      <dl className="well grid grid-cols-3 gap-y-4 px-2 py-4 text-center">
        {counts.map(([label, value]) => (
          <div key={label} className="flex flex-col-reverse">
            <dt className="text-xs text-muted">{label}</dt>
            <dd className={`text-lg font-semibold tabular-nums ${value ? 'text-fg' : 'text-muted/70'}`}>{value}</dd>
          </div>
        ))}
      </dl>
      <div className="space-y-2">
        <CliHint command={cliHints.context(bundle.query, bundle.token_budget, bundle.agent)} />
        <div className="px-1 text-[11px] text-muted">
          {bundle.tokenizer ?? 'cl100k_base'} · generated {bundle.generated_at}
        </div>
      </div>
      <div className="well px-4 py-3">
        <Markdown className="prose-compact text-[13px] leading-relaxed">{bundle.rendered}</Markdown>
      </div>
    </>
  )
}
