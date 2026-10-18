import { ChevronDown, FileText } from 'lucide-react'
import { useState } from 'react'
import type { ContextEvent } from '../../types/generated'
import { Markdown } from '../Markdown'
import { TokenMeter } from '../TokenMeter'
import { SidePanel } from './SidePanel'

/**
 * Context column: token meter, working memory, and the injected bundle for the last turn.
 *
 * Behavior:
 *     Before the first `context` event it shows a short hint. Working memory
 *     appears once the session has a goal or model switches. The rendered
 *     bundle can be collapsed and scrolls on its own. Below `xl` the column is
 *     a drawer controlled by `open`.
 * Parameters:
 *     context: The last `context` event, or `null`.
 *     budget: The agent's token budget, if known.
 *     goal: Session goal from working memory.
 *     switches: Labels of the models used, in order.
 *     turns: Number of recent turns carried to the next model.
 *     open: Whether the drawer is shown below `xl`.
 *     onClose: Called to close the drawer.
 */
export function ContextPanel({
  context,
  budget,
  goal,
  switches,
  turns,
  open,
  onClose,
}: {
  context: ContextEvent | null
  budget?: number
  goal?: string | null
  switches: string[]
  turns?: number
  open: boolean
  onClose: () => void
}) {
  const [showRendered, setShowRendered] = useState(true)
  return (
    <SidePanel
      as="aside"
      id="chat-context"
      label="Injected context"
      title="Context this turn"
      side="right"
      open={open}
      onClose={onClose}
      width="xl:w-[21rem]"
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 pb-4 xl:overflow-hidden">
        <div className="well shrink-0 space-y-3 p-4">
          {context ? (
            <>
              <TokenMeter used={context.tokens_used} baseline={context.baseline_tokens} saved={context.tokens_saved} budget={budget} />
              <div className="flex items-center gap-1.5 text-xs text-muted">
                <FileText size={13} strokeWidth={1.75} aria-hidden />
                {context.doc_ids.length} documents cited
              </div>
            </>
          ) : (
            <p className="text-sm leading-relaxed text-muted">Send a message to see what PAM injects and how many tokens it saves.</p>
          )}
        </div>

        {(goal || switches.length > 0) && (
          <section className="shrink-0 space-y-2 px-1 pt-5 text-[13px] leading-relaxed">
            <h3 className="label">Working memory</h3>
            {goal && (
              <p>
                <span className="text-muted">Goal </span>
                <span className="text-fg/90">{goal}</span>
              </p>
            )}
            {switches.length > 0 && (
              <p>
                <span className="text-muted">Models </span>
                <span className="text-fg/90">{switches.join(' → ')}</span>
              </p>
            )}
            {turns !== undefined && <p className="text-xs text-muted">{turns} recent turns carried to the next model</p>}
          </section>
        )}

        {context && (
          <section className="flex min-h-[12rem] flex-1 flex-col pt-4">
            <button
              type="button"
              className="flex shrink-0 items-center justify-between rounded-control px-1 py-1.5 text-left transition duration-200 ease-out hover:text-fg"
              onClick={() => setShowRendered((v) => !v)}
              aria-expanded={showRendered}
            >
              <span className="label">Injected bundle</span>
              <span className="flex items-center gap-1 text-xs text-muted">
                {showRendered ? 'Hide' : 'Show'}
                <ChevronDown
                  size={14}
                  strokeWidth={1.75}
                  className={`transition-transform duration-200 ease-out ${showRendered ? 'rotate-180' : ''}`}
                  aria-hidden
                />
              </span>
            </button>
            {showRendered && (
              <div className="well mt-2 min-h-0 flex-1 overflow-y-auto px-4 py-3">
                <Markdown className="prose-compact text-xs">{context.rendered}</Markdown>
              </div>
            )}
          </section>
        )}
      </div>
    </SidePanel>
  )
}
