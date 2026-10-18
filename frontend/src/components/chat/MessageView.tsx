import { ArrowRight, ArrowRightLeft, Loader2, Plug, RotateCcw, Sparkles, Wrench } from 'lucide-react'
import { ApiError } from '../../api/client'
import { splitToolName, useConnectors } from '../../lib/connectors'
import { ConnectorCards } from '../connectors/Cards'
import { ErrorNote } from '../ErrorNote'
import { Markdown } from '../Markdown'
import type { Message } from './types'

/**
 * A connector tool call in the transcript: a compact chip, then its display cards.
 *
 * Behavior:
 *     The chip reads "Used <connector name> · <tool>"; the name comes from the
 *     connector list (archived included) and falls back to the id. A failed call
 *     (its summary starts with `ERROR:`) shows the summary instead of cards.
 * Parameters:
 *     call: The connector id and tool parsed from `<connector_id>__<tool>`.
 *     message: The tool message.
 */
function ConnectorToolCall({ call, message }: { call: { connector: string; tool: string }; message: Extract<Message, { kind: 'tool' }> }) {
  const connectors = useConnectors(true)
  const name = connectors.data?.find((c) => c.id === call.connector)?.name ?? call.connector
  const failed = message.summary.startsWith('ERROR:')
  return (
    <div className="enter ml-11 min-w-0 space-y-2.5" data-testid="connector-call">
      <span
        className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${
          failed ? 'border-bad/30 bg-bad/10 text-bad' : 'border-accent/25 bg-accent/10 text-fg/90'
        }`}
        title={message.args}
      >
        <Plug size={12} strokeWidth={1.75} className="shrink-0 text-accent" aria-hidden />
        <span className="truncate">
          Used {name} · <span className="font-mono">{call.tool}</span>
        </span>
      </span>
      {failed && <p className="text-xs text-muted">{message.summary}</p>}
      {!failed && message.cards && message.cards.length > 0 && <ConnectorCards cards={message.cards} />}
    </div>
  )
}

/**
 * Round lavender avatar with a sparkle, used for the assistant.
 *
 * Parameters:
 *     size: Diameter preset, `sm` for messages and `lg` for the empty state.
 */
export function AssistantAvatar({ size = 'sm' }: { size?: 'sm' | 'lg' }) {
  const box = size === 'lg' ? 'h-14 w-14' : 'h-8 w-8'
  return (
    <span
      className={`${box} inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-strong text-accent-fg shadow-[inset_0_1px_0_rgba(255,255,255,0.35),0_6px_20px_rgb(var(--accent-strong)/0.35)]`}
      aria-hidden
    >
      <Sparkles size={size === 'lg' ? 24 : 15} strokeWidth={1.75} />
    </span>
  )
}

/**
 * Render one transcript entry: a user bubble, an assistant reply, a tool call, or a model-switch divider.
 *
 * Behavior:
 *     User turns are right-aligned lavender bubbles. Assistant replies sit on
 *     a quiet surface next to the avatar, with the model label, a streaming
 *     spinner and token usage above; a streaming reply carries
 *     `data-streaming="true"`. A failed reply shows its error, with a Retry
 *     button when the error is retryable.
 * Parameters:
 *     message: The entry to render.
 *     labelOf: Maps a model id to its display label.
 *     onRetry: Called with the prompt to resend.
 *     disabled: Whether Retry is blocked.
 */
export function MessageView({
  message,
  labelOf,
  onRetry,
  disabled,
}: {
  message: Message
  labelOf: (id: string) => string
  onRetry: (prompt: string) => void
  disabled: boolean
}) {
  if (message.kind === 'user') {
    return (
      <div className="msg-user flex justify-end pl-10 sm:pl-16">
        <div className="max-w-full whitespace-pre-wrap break-words rounded-[20px] rounded-br-md bg-gradient-to-br from-accent to-accent/80 px-4 py-2.5 text-[14px] leading-relaxed text-accent-fg shadow-[inset_0_1px_0_rgba(255,255,255,0.3),0_10px_30px_rgb(var(--accent-strong)/0.28)]">
          {message.text}
        </div>
      </div>
    )
  }
  if (message.kind === 'switch') {
    return (
      <div className="enter flex items-center gap-3 py-1 text-xs text-muted" role="separator">
        <div className="h-px flex-1 bg-edge/10" />
        <span className="inline-flex min-w-0 items-center gap-1.5 rounded-full border border-edge/10 bg-edge/[0.05] px-3 py-1">
          <ArrowRightLeft size={12} strokeWidth={1.75} className="shrink-0 text-accent" aria-hidden />
          <span className="truncate">switched to {labelOf(message.model)}</span>
        </span>
        <div className="h-px flex-1 bg-edge/10" />
      </div>
    )
  }
  if (message.kind === 'tool') {
    const connectorCall = splitToolName(message.name)
    if (connectorCall) return <ConnectorToolCall call={connectorCall} message={message} />
    return (
      <div className="enter ml-11 flex items-start gap-2.5 rounded-control border border-edge/[0.08] bg-edge/[0.04] px-3.5 py-2.5 text-xs leading-relaxed">
        <Wrench size={14} strokeWidth={1.75} className="mt-0.5 shrink-0 text-accent" aria-hidden />
        <div className="min-w-0">
          <span className="font-mono text-fg/90">{message.name}</span>
          <span className="ml-1.5 break-all font-mono text-muted">{message.args}</span>
          <div className="mt-0.5 text-muted">→ {message.summary}</div>
        </div>
      </div>
    )
  }
  const usage = message.usage && (message.usage.prompt !== null || message.usage.completion !== null) ? message.usage : null
  return (
    <div className="msg-assistant flex items-start gap-3" data-streaming={message.streaming ? 'true' : undefined}>
      <AssistantAvatar />
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 pl-1 text-xs text-muted">
          <span className="text-fg/80">{labelOf(message.model)}</span>
          {message.streaming && <Loader2 size={12} className="animate-spin text-accent" aria-label="Streaming" />}
          {usage && (
            <span className="tabular-nums">
              {usage.prompt ?? '?'} in · {usage.completion ?? '?'} out
            </span>
          )}
        </div>
        <div className="space-y-3 rounded-[20px] rounded-tl-md border border-edge/10 bg-edge/[0.06] px-4 py-3 shadow-[inset_0_1px_0_rgb(var(--edge)/0.06)]">
          {message.text ? (
            <Markdown className="text-[14px] leading-relaxed">{message.text}</Markdown>
          ) : message.streaming ? (
            <p className="flex items-center gap-2 text-sm text-muted">
              <span className="flex gap-1" aria-hidden>
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent [animation-delay:300ms]" />
              </span>
              Thinking…
            </p>
          ) : null}
          {message.error && (
            <ErrorNote
              error={new ApiError(0, message.error.retryable ? 'RETRYABLE' : 'ERROR', message.error.message)}
              action={
                message.error.retryable && (
                  <button type="button" className="btn shrink-0" disabled={disabled} onClick={() => onRetry(message.error!.prompt)}>
                    <RotateCcw size={14} strokeWidth={1.75} /> Retry
                  </button>
                )
              }
            />
          )}
        </div>
      </div>
    </div>
  )
}

const STARTERS = [
  "Let's keep going on my project. Where did I leave off?",
  'What do you know about me?',
  'Summarize the decisions I made this week.',
]

/**
 * Empty conversation: a short introduction and starter prompts.
 *
 * Parameters:
 *     onPick: Called with the starter prompt to send.
 */
export function EmptyChat({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="enter mx-auto flex max-w-md flex-col items-center gap-5 py-10 text-center sm:py-16">
      <span className="animate-pop rounded-full [animation-delay:120ms]">
        <AssistantAvatar size="lg" />
      </span>
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-[-0.015em] text-fg">Pick up where you left off</h2>
        <p className="text-[14px] leading-relaxed text-muted">
          Pick any model. PAM injects only the memory this turn needs and shows the token savings alongside.
        </p>
      </div>
      <div className="stagger flex w-full flex-col gap-2 pt-2">
        {STARTERS.map((q) => (
          <button
            key={q}
            type="button"
            className="press group flex w-full items-center justify-between gap-3 rounded-control border border-edge/10 bg-edge/[0.05] px-4 py-3 text-left text-sm text-fg/90 hover:border-accent/40 hover:bg-edge/[0.09] hover:text-fg"
            onClick={() => onPick(q)}
          >
            {q}
            <ArrowRight
              size={16}
              strokeWidth={1.75}
              className="shrink-0 text-muted transition duration-300 ease-[var(--ease-spring)] group-hover:translate-x-1 group-hover:text-accent"
              aria-hidden
            />
          </button>
        ))}
      </div>
    </div>
  )
}
