import type { ReactNode } from 'react'
import { CliHint } from './CliHint'

/**
 * Page title row with the page's CLI hint and right-aligned actions.
 *
 * Behavior:
 *     Sits directly on the atmospheric background (no surface), so the page's
 *     main glass panel below it stays the focal point.
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
    <header className="flex shrink-0 flex-col gap-4 px-2 pb-4 pt-2 sm:px-4 lg:pt-3">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em] text-fg sm:text-[30px]">{title}</h1>
          {subtitle && <p className="mt-1 max-w-2xl text-[15px] leading-relaxed text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {cli && <CliHint command={cli} />}
    </header>
  )
}
