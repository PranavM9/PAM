import { AlertTriangle } from 'lucide-react'
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'

/**
 * Inline error box for a failed request.
 *
 * Behavior:
 *     Shows the `ApiError` code and message, or the plain error message.
 *     Renders nothing when `error` is falsy.
 * Parameters:
 *     error: The error to show.
 *     action: Optional control, e.g. a Retry button.
 */
export function ErrorNote({ error, action }: { error: unknown; action?: ReactNode }) {
  if (!error) return null
  const code = error instanceof ApiError ? error.code : null
  const message = error instanceof Error ? error.message : String(error)
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm">
      <AlertTriangle size={16} className="mt-0.5 shrink-0 text-bad" aria-hidden />
      <div className="min-w-0 flex-1">
        {code && <span className="mr-2 font-mono text-xs text-bad">{code}</span>}
        <span>{message}</span>
      </div>
      {action}
    </div>
  )
}
