import { AlertTriangle } from 'lucide-react'
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'

/**
 * Inline error box for a failed request.
 *
 * Behavior:
 *     Shows the `ApiError` code and message, or the plain error message, with a
 *     warning icon so the state does not rely on color alone. Renders nothing
 *     when `error` is falsy.
 * Parameters:
 *     error: The error to show.
 *     action: Optional control, e.g. a Retry button.
 */
export function ErrorNote({ error, action }: { error: unknown; action?: ReactNode }) {
  if (!error) return null
  const code = error instanceof ApiError ? error.code : null
  const message = error instanceof Error ? error.message : String(error)
  return (
    <div role="alert" className="flex items-start gap-3 rounded-2xl border border-bad/30 bg-bad/10 px-4 py-3 text-sm">
      <AlertTriangle size={16} className="mt-0.5 shrink-0 text-bad" aria-hidden />
      <div className="min-w-0 flex-1 leading-relaxed">
        {code && <span className="mr-2 font-mono text-xs text-bad">{code}</span>}
        <span className="text-fg/90">{message}</span>
      </div>
      {action}
    </div>
  )
}
