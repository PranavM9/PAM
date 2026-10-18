import { CheckCircle2, MessageSquarePlus } from 'lucide-react'
import type { CSSProperties } from 'react'
import { SidePanel } from './SidePanel'
import type { StoredSession } from './types'

/**
 * Sessions column: a New chat button and the sessions remembered by this browser.
 *
 * Behavior:
 *     The active session is highlighted and marked `aria-current`. Session
 *     buttons are disabled while a reply streams. Below `xl` the column is a
 *     drawer controlled by `open`.
 * Parameters:
 *     sessions: Sessions to list, newest first.
 *     activeId: Id of the open session, or `null` for a new chat.
 *     onOpen: Called with the id of the session to open.
 *     onNew: Called to start a new chat.
 *     disabled: Whether opening another session is blocked.
 *     open: Whether the drawer is shown below `xl`.
 *     onClose: Called to close the drawer.
 *     style: Inline style; sets `--pane-w`, the width from `xl` up.
 */
export function SessionList({
  sessions,
  activeId,
  onOpen,
  onNew,
  disabled,
  open,
  onClose,
  style,
}: {
  sessions: StoredSession[]
  activeId: string | null
  onOpen: (id: string) => void
  onNew: () => void
  disabled: boolean
  open: boolean
  onClose: () => void
  style?: CSSProperties
}) {
  return (
    <SidePanel
      as="nav"
      id="chat-sessions"
      label="Sessions"
      title="Sessions"
      side="left"
      open={open}
      onClose={onClose}
      width="xl:w-[var(--pane-w)]"
      style={style}
      actions={
        <button type="button" className="btn w-full" onClick={onNew}>
          <MessageSquarePlus size={16} strokeWidth={1.75} /> New chat
        </button>
      }
    >
      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-4">
        {sessions.length === 0 && <li className="px-2 py-1 text-[13px] leading-relaxed text-muted">No sessions yet. Your chats will appear here.</li>}
        {sessions.map((s) => {
          const active = s.id === activeId
          return (
            <li key={s.id}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onOpen(s.id)}
                aria-current={active ? 'true' : undefined}
                className={`w-full rounded-control px-3 py-2.5 text-left transition duration-200 ease-out disabled:cursor-not-allowed disabled:opacity-60 ${
                  active
                    ? 'bg-gradient-to-r from-accent/25 to-accent/10 shadow-[inset_0_1px_0_rgb(var(--edge)/0.1)]'
                    : 'hover:bg-fg/[0.06]'
                }`}
              >
                <div className={`truncate text-sm ${active ? 'font-medium text-fg' : 'text-fg/90'}`}>{s.title}</div>
                <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
                  <span className="truncate font-mono">{s.id}</span>
                  {s.ended && (
                    <span className="inline-flex shrink-0 items-center gap-1 text-ok">
                      <CheckCircle2 size={11} aria-hidden /> ended
                    </span>
                  )}
                </div>
              </button>
            </li>
          )
        })}
      </ul>
    </SidePanel>
  )
}
