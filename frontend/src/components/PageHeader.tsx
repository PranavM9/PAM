import type { ReactNode } from 'react'
import { CliHint } from './CliHint'

/**
 * Page title row with the page's CLI hint and right-aligned actions.
 *
 * Parameters:
 *     title: Page title.
 *     subtitle: One-line description.
 *     cli: Equivalent CLI command for the page's main action.
 *     actions: Controls rendered on the right.
 */
export function PageHeader({
  title,
  subtitle,
  cli,
  actions,
}: {
  title: string
  subtitle?: string
  cli?: string
  actions?: ReactNode
}) {
  return (
    <header className="flex shrink-0 flex-col gap-3 border-b border-line px-6 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">{title}</h1>
          {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {cli && <CliHint command={cli} />}
    </header>
  )
}
