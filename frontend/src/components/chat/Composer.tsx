import { ArrowUp, Square } from 'lucide-react'

/**
 * Message composer: a rounded multiline input with a round send or stop button.
 *
 * Behavior:
 *     Enter sends and Shift+Enter inserts a new line (IME composition is left
 *     alone). The textarea grows to six lines. While a reply streams the send
 *     button becomes a stop button. Everything is disabled once the session ends.
 * Parameters:
 *     value: Current draft.
 *     onChange: Called with the edited draft.
 *     onSend: Called to send the draft.
 *     onStop: Called to abort the streaming reply.
 *     streaming: Whether a reply is streaming.
 *     canSend: Whether a model is selected.
 *     ended: Whether the session has ended.
 */
export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  canSend,
  ended,
}: {
  value: string
  onChange: (text: string) => void
  onSend: () => void
  onStop: () => void
  streaming: boolean
  canSend: boolean
  ended: boolean
}) {
  return (
    <form
      className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-[22px] border border-edge/[0.12] bg-bg/35 p-1.5 pl-4 shadow-[inset_0_1px_2px_rgba(0,0,0,0.12)] transition duration-200 ease-out focus-within:border-accent/60 focus-within:shadow-[0_0_0_3px_rgb(var(--accent)/0.18)]"
      onSubmit={(e) => {
        e.preventDefault()
        onSend()
      }}
    >
      <textarea
        className="min-h-[2.5rem] flex-1 resize-none self-center bg-transparent py-2 text-[14px] leading-relaxed text-fg placeholder:text-muted/80 focus:outline-none disabled:cursor-not-allowed"
        rows={Math.min(6, Math.max(1, value.split('\n').length))}
        placeholder={ended ? 'This session has ended.' : 'Ask anything. Enter to send, Shift+Enter for a new line.'}
        value={value}
        disabled={ended}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            onSend()
          }
        }}
        aria-label="Message"
      />
      {streaming ? (
        <button type="button" className="btn h-10 w-10 shrink-0 rounded-full p-0" onClick={onStop} aria-label="Stop" title="Stop">
          <Square size={14} strokeWidth={2} className="animate-pop fill-current" />
        </button>
      ) : (
        <button
          type="submit"
          className="group btn btn-primary h-10 w-10 shrink-0 rounded-full p-0"
          disabled={!value.trim() || !canSend || ended}
          aria-label="Send"
          title="Send"
        >
          <ArrowUp size={18} strokeWidth={2} className="transition-transform duration-300 ease-[var(--ease-spring)] group-enabled:group-hover:-translate-y-0.5" />
        </button>
      )}
    </form>
  )
}
