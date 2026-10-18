import { Bot, Plus } from 'lucide-react'
import type { CSSProperties } from 'react'
import type { AgentManifest } from '../../types/generated'
import { ErrorNote } from '../ErrorNote'

/**
 * Glass side panel listing every agent, with a "New agent" button on top.
 *
 * Behavior:
 *     Below `lg` the list becomes a horizontally scrolling row so the editor
 *     keeps the full width; at `lg` it is a fixed-width column.
 * Parameters:
 *     agents: Manifests from `GET /agents`, or undefined while loading.
 *     loading: Whether the list request is pending.
 *     error: The list request's error, if any.
 *     selected: Name of the highlighted agent, or null.
 *     onSelect: Called with an agent's name when its row is clicked.
 *     onNew: Called when "New agent" is clicked.
 *     style: Inline style; sets `--pane-w`, the width from `lg` up.
 */
export function AgentList({
  agents,
  loading,
  error,
  selected,
  onSelect,
  onNew,
  style,
}: {
  agents: AgentManifest[] | undefined
  loading: boolean
  error: unknown
  selected: string | null
  onSelect: (name: string) => void
  onNew: () => void
  style?: CSSProperties
}) {
  return (
    <nav aria-label="Agents" style={style} className="panel flex shrink-0 flex-col gap-3 p-3 lg:w-[var(--pane-w)] lg:gap-4 lg:p-4">
      <div className="flex items-center justify-between gap-3 px-1 lg:flex-col lg:items-stretch">
        <h2 className="text-[15px] font-semibold tracking-[-0.01em] lg:px-1 lg:pt-1">Agents</h2>
        <button type="button" className="group btn lg:w-full" onClick={onNew}>
          <Plus size={16} strokeWidth={1.75} aria-hidden className="transition-transform duration-500 ease-[var(--ease-spring)] group-hover:rotate-90" /> New agent
        </button>
      </div>
      <ul className="stagger -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 lg:mx-0 lg:min-h-0 lg:flex-1 lg:flex-col lg:gap-1 lg:overflow-y-auto lg:overflow-x-visible lg:px-0 lg:pb-0">
        {loading && <li className="px-3 py-2 text-sm text-muted">Loading…</li>}
        {agents?.map((a) => {
          const active = a.name === selected
          return (
            <li key={a.name} className="shrink-0 lg:shrink">
              <button
                type="button"
                onClick={() => onSelect(a.name)}
                aria-current={active ? 'true' : undefined}
                className={`press group flex w-full min-w-[11rem] items-center gap-3 rounded-control px-3 py-2.5 text-left lg:min-w-0 ${
                  active
                    ? 'bg-accent/15 shadow-[inset_0_1px_0_var(--glass-highlight)]'
                    : 'hover:bg-fg/[0.06]'
                }`}
              >
                <span
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition duration-500 ease-[var(--ease-spring)] group-hover:scale-110 ${active ? 'scale-105 bg-accent/25 text-fg' : 'bg-fg/[0.06] text-muted'}`}
                  aria-hidden
                >
                  <Bot size={17} strokeWidth={1.75} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className={`block truncate text-sm ${active ? 'font-semibold text-fg' : 'font-medium text-fg/90'}`}>{a.display_name}</span>
                  <span className="block truncate font-mono text-[11px] text-muted">{a.name}</span>
                </span>
                <span className="badge shrink-0">{a.origin}</span>
              </button>
            </li>
          )
        })}
      </ul>
      <ErrorNote error={error} />
    </nav>
  )
}
