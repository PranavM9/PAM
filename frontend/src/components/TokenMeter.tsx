import { formatTokens } from '../lib/palette'

/**
 * Token meter: tokens used vs. a full-history replay, and vs. the budget.
 *
 * Behavior:
 *     The headline compares `used` with `baseline`; the bar shows their ratio.
 *     The footer shows the saved count with its percentage and, when given,
 *     `used / budget`. All numbers come from the backend unchanged.
 * Parameters:
 *     used: Tokens in the injected context.
 *     baseline: Tokens of the full transcripts the context came from.
 *     saved: Saved tokens as reported by the backend.
 *     budget: The token budget, if known.
 */
export function TokenMeter({
  used,
  baseline,
  saved,
  budget,
}: {
  used: number
  baseline: number
  saved: number
  budget?: number
}) {
  const ratio = baseline > 0 ? Math.min(1, used / baseline) : 1
  const percent = baseline > 0 ? Math.round((saved / baseline) * 100) : 0
  return (
    <div className="space-y-3 text-xs" aria-label="Token usage">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[32px] font-semibold leading-none tracking-[-0.02em] tabular-nums text-fg">{formatTokens(used)}</span>
        <span className="text-muted">
          vs <span className="tabular-nums text-fg">{formatTokens(baseline)}</span> full-history replay
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-edge/10"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={baseline}
        aria-valuenow={used}
        aria-label="Tokens used compared with the full history"
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-accent-strong to-accent transition-[width] duration-300 ease-out"
          style={{ width: `${Math.max(2, ratio * 100)}%` }}
        />
      </div>
      <div className="flex flex-wrap justify-between gap-2 text-muted">
        <span>
          Saved <span className="tabular-nums text-ok">{saved.toLocaleString()}</span> tokens ({percent}%)
        </span>
        {budget !== undefined && (
          <span className="tabular-nums">
            {used.toLocaleString()} / {budget.toLocaleString()} budget
          </span>
        )}
      </div>
    </div>
  )
}
