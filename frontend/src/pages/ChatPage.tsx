import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRightLeft,
  Bot,
  CheckCircle2,
  Loader2,
  MessageSquarePlus,
  RotateCcw,
  Send,
  Square,
  Wrench,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api, chatStream } from '../api/client'
import { AgentSelect } from '../components/AgentSelect'
import { CliHint } from '../components/CliHint'
import { ErrorNote } from '../components/ErrorNote'
import { Markdown } from '../components/Markdown'
import { TokenMeter } from '../components/TokenMeter'
import { cliHints } from '../lib/cliHints'
import type { ContextEvent, ModelEntry, WriteResult } from '../types/generated'

type Mode = 'injection' | 'tool'

type Message =
  | { id: string; kind: 'user'; text: string }
  | {
      id: string
      kind: 'assistant'
      text: string
      model: string
      streaming: boolean
      usage?: { prompt: number | null; completion: number | null }
      error?: { message: string; retryable: boolean; prompt: string }
    }
  | { id: string; kind: 'switch'; model: string }
  | { id: string; kind: 'tool'; name: string; args: string; summary: string }

/** A chat session as remembered by this browser (the API has no session list). */
interface StoredSession {
  id: string
  title: string
  agent: string
  updated: string
  ended: boolean
  messages: Message[]
  context: ContextEvent | null
}

const STORE_KEY = 'pam-chat-sessions'

function loadSessions(): StoredSession[] {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY) ?? '[]') as StoredSession[]
  } catch {
    return []
  }
}

function saveSessions(sessions: StoredSession[]) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(sessions.slice(0, 30)))
  } catch {
    // Storage full or unavailable: the list lasts for this tab only.
  }
}

let counter = 0
const uid = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`

/**
 * Chat page: sessions, streamed Markdown messages, hot-swappable model, context panel.
 *
 * Behavior:
 *     Each send streams one turn from `POST /chat`. The first `context` event
 *     fills the right panel (rendered bundle and token meter) and, for a new
 *     chat, provides the session id. Changing the model at any time inserts a
 *     "switched to X" divider; the next turn uses the new model with the same
 *     session, so working memory carries the thread. Retryable errors show a
 *     Retry button. "End session" calls `POST /sessions/{id}/end`. Sessions and
 *     their transcripts are remembered in `localStorage`, since the API only
 *     returns the last 8 turns of a session.
 */
export default function ChatPage() {
  const [sessions, setSessions] = useState<StoredSession[]>(loadSessions)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [draft, setDraft] = useState<StoredSession>(() => blank('default'))
  const [pickedModel, setModel] = useState<string>('')
  const [pickedMode, setMode] = useState<Mode>('injection')
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [requestError, setRequestError] = useState<unknown>(null)
  const [ended, setEnded] = useState<WriteResult | null>(null)
  const abort = useRef<AbortController | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const draftRef = useRef(draft)
  const queryClient = useQueryClient()

  const models = useQuery({ queryKey: ['models'], queryFn: api.models })
  const agents = useQuery({ queryKey: ['agents'], queryFn: api.listAgents })

  const session = activeId ? sessions.find((s) => s.id === activeId) ?? draft : draft
  const agentName = session.agent
  const agent = agents.data?.find((a) => a.name === agentName)
  const modelList = useMemo(() => models.data ?? [], [models.data])
  const fallbackModel =
    agent?.default_model && modelList.some((m) => m.id === agent.default_model) ? agent.default_model : modelList[0]?.id ?? ''
  const model = pickedModel || fallbackModel
  const current = modelList.find((m) => m.id === model)
  const mode: Mode = pickedMode === 'tool' && !current?.supports_tools ? 'injection' : pickedMode
  const lastPrompt = [...session.messages].reverse().find((m) => m.kind === 'user')?.text

  const working = useQuery({
    queryKey: ['session', activeId],
    queryFn: () => api.getSession(activeId!),
    enabled: Boolean(activeId),
  })

  useEffect(() => saveSessions(sessions), [sessions])

  useEffect(() => {
    draftRef.current = draft
  }, [draft])

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight })
  }, [session.messages])

  const update = (id: string | null, change: (s: StoredSession) => StoredSession) => {
    if (id === null) setDraft((d) => change(d))
    else setSessions((list) => list.map((s) => (s.id === id ? change(s) : s)))
  }

  const pickModel = (next: string) => {
    if (next === model) return
    setModel(next)
    if (session.messages.length) {
      update(activeId, (s) => ({ ...s, messages: [...s.messages, { id: uid(), kind: 'switch', model: next }] }))
    }
  }

  const send = async (text: string, retryOf?: string) => {
    const message = text.trim()
    if (!message || streaming || !model || session.ended) return
    setRequestError(null)
    setInput('')
    let sessionId = activeId
    const replyId = uid()
    const reply: Message = { id: replyId, kind: 'assistant', text: '', model, streaming: true }
    update(sessionId, (s) => ({
      ...s,
      messages: [
        ...s.messages.filter((m) => m.id !== retryOf),
        ...(retryOf ? [] : [{ id: uid(), kind: 'user' as const, text: message }]),
        reply,
      ],
    }))
    const patchReply = (change: (m: Extract<Message, { kind: 'assistant' }>) => Partial<Message>) =>
      update(sessionId, (s) => ({
        ...s,
        updated: new Date().toISOString(),
        messages: s.messages.map((m) => (m.id === replyId && m.kind === 'assistant' ? ({ ...m, ...change(m) } as Message) : m)),
      }))

    const controller = new AbortController()
    abort.current = controller
    setStreaming(true)
    try {
      await chatStream(
        { session_id: sessionId, agent: agentName, model, message, mode },
        (event) => {
          switch (event.type) {
            case 'context':
              if (sessionId === null) {
                sessionId = event.session_id
                const promoted: StoredSession = { ...draftRef.current, id: event.session_id, title: message.slice(0, 60) }
                setSessions((list) => [promoted, ...list.filter((s) => s.id !== event.session_id)])
                setActiveId(event.session_id)
                setDraft(blank(agentName))
              }
              update(sessionId, (s) => ({ ...s, context: event }))
              break
            case 'tool_call':
              update(sessionId, (s) => ({
                ...s,
                messages: [
                  ...s.messages.filter((m) => m.id !== replyId),
                  { id: uid(), kind: 'tool', name: event.name, args: JSON.stringify(event.arguments), summary: event.result_summary },
                  ...s.messages.filter((m) => m.id === replyId),
                ],
              }))
              break
            case 'token':
              patchReply((m) => ({ text: m.text + event.text }))
              break
            case 'done':
              patchReply(() => ({
                streaming: false,
                model: event.model,
                usage: { prompt: event.prompt_tokens, completion: event.completion_tokens },
              }))
              break
            case 'error':
              patchReply(() => ({ streaming: false, error: { message: event.message, retryable: event.retryable, prompt: message } }))
              break
          }
        },
        controller.signal,
      )
    } catch (err) {
      setRequestError(err)
      update(sessionId, (s) => ({ ...s, messages: s.messages.filter((m) => m.id !== replyId) }))
    } finally {
      patchReply(() => ({ streaming: false }))
      setStreaming(false)
      abort.current = null
      if (sessionId) queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    }
  }

  const end = useMutation({
    mutationFn: (id: string) => api.endSession(id),
    onSuccess: (result, id) => {
      setEnded(result)
      update(id, (s) => ({ ...s, ended: true }))
      for (const key of ['session', 'graph', 'vault-tree']) queryClient.invalidateQueries({ queryKey: [key] })
    },
  })

  const newChat = () => {
    abort.current?.abort()
    setActiveId(null)
    setDraft(blank(agentName))
    setEnded(null)
    setRequestError(null)
  }

  const openSession = (id: string) => {
    if (streaming) return
    setActiveId(id)
    setEnded(null)
    setRequestError(null)
    const last = [...(sessions.find((s) => s.id === id)?.messages ?? [])]
      .reverse()
      .find((m): m is Extract<Message, { kind: 'assistant' }> => m.kind === 'assistant')
    if (last && modelList.some((m) => m.id === last.model)) setModel(last.model)
  }

  const labelOf = (id: string) => modelList.find((m) => m.id === id)?.label ?? id

  return (
    <div className="flex min-h-0 flex-1">
      <SessionList sessions={sessions} activeId={activeId} onOpen={openSession} onNew={newChat} disabled={streaming} />

      <section className="flex min-w-0 flex-1 flex-col" aria-label="Conversation">
        <header className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          <label className="flex items-center gap-1.5 text-sm text-muted">
            Agent
            <AgentSelect
              value={agentName}
              onChange={(name) => update(activeId, (s) => ({ ...s, agent: name }))}
            />
          </label>
          <ModelSelect models={modelList} value={model} onChange={pickModel} />
          <ModeToggle mode={mode} onChange={setMode} toolsSupported={Boolean(current?.supports_tools)} />
          <div className="ml-auto flex items-center gap-2">
            {activeId && (
              <span className="font-mono text-xs text-muted" title="Session id">
                {activeId}
              </span>
            )}
            <button
              type="button"
              className="btn"
              disabled={!activeId || session.ended || streaming || end.isPending}
              onClick={() => activeId && end.mutate(activeId)}
            >
              {end.isPending ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              End session
            </button>
          </div>
        </header>

        <div ref={scroller} className="min-h-0 flex-1 overflow-auto px-6 py-5" aria-live="polite">
          {session.messages.length === 0 ? (
            <EmptyChat onPick={(q) => send(q)} />
          ) : (
            <ol className="mx-auto max-w-3xl space-y-5">
              {session.messages.map((m) => (
                <li key={m.id}>
                  <MessageView message={m} labelOf={labelOf} onRetry={(prompt) => send(prompt, m.id)} disabled={streaming} />
                </li>
              ))}
            </ol>
          )}
        </div>

        <div className="space-y-2 border-t border-line px-6 py-3">
          <ErrorNote error={requestError ?? end.error} />
          {(ended || session.ended) && (
            <div className="flex items-center gap-2 rounded-md border border-ok/40 bg-ok/10 px-3 py-2 text-sm">
              <CheckCircle2 size={16} className="text-ok" aria-hidden />
              <span className="flex-1">
                Session ended{ended?.path ? <> and saved as <code className="font-mono text-xs">{ended.path}</code></> : ''}.
              </span>
              <button type="button" className="btn" onClick={newChat}>
                <MessageSquarePlus size={14} /> New chat
              </button>
            </div>
          )}
          <form
            className="mx-auto flex max-w-3xl items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              send(input)
            }}
          >
            <textarea
              className="input min-h-[2.75rem] flex-1 resize-none"
              rows={Math.min(6, Math.max(1, input.split('\n').length))}
              placeholder={session.ended ? 'This session has ended.' : 'Ask anything. Enter to send, Shift+Enter for a new line.'}
              value={input}
              disabled={session.ended}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  send(input)
                }
              }}
              aria-label="Message"
            />
            {streaming ? (
              <button type="button" className="btn" onClick={() => abort.current?.abort()}>
                <Square size={14} /> Stop
              </button>
            ) : (
              <button type="submit" className="btn btn-primary" disabled={!input.trim() || !model || session.ended}>
                <Send size={14} /> Send
              </button>
            )}
          </form>
          <CliHint command={cliHints.chat(lastPrompt, model || undefined, activeId ?? undefined)} />
        </div>
      </section>

      <ContextPanel
        context={session.context}
        budget={agent?.token_budget}
        goal={working.data?.goal}
        switches={working.data?.models_used?.map((s) => labelOf(s.to_model)) ?? []}
        turns={working.data?.recent_turns?.length}
      />
    </div>
  )
}

function blank(agent: string): StoredSession {
  return { id: '', title: 'New chat', agent, updated: new Date().toISOString(), ended: false, messages: [], context: null }
}

function SessionList({
  sessions,
  activeId,
  onOpen,
  onNew,
  disabled,
}: {
  sessions: StoredSession[]
  activeId: string | null
  onOpen: (id: string) => void
  onNew: () => void
  disabled: boolean
}) {
  return (
    <nav aria-label="Sessions" className="flex w-56 shrink-0 flex-col border-r border-line bg-panel/50">
      <div className="p-3">
        <button type="button" className="btn w-full justify-center" onClick={onNew}>
          <MessageSquarePlus size={14} /> New chat
        </button>
      </div>
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-auto px-2 pb-3">
        {sessions.length === 0 && <li className="px-2 text-xs text-muted">No sessions yet.</li>}
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onOpen(s.id)}
              aria-current={s.id === activeId ? 'true' : undefined}
              className={`w-full rounded-md px-2.5 py-2 text-left text-sm disabled:opacity-60 ${
                s.id === activeId ? 'bg-accent/15' : 'hover:bg-raised'
              }`}
            >
              <div className="truncate">{s.title}</div>
              <div className="flex items-center gap-1.5 text-[11px] text-muted">
                <span className="font-mono">{s.id}</span>
                {s.ended && <span className="text-ok">ended</span>}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}

function ModelSelect({ models, value, onChange }: { models: ModelEntry[]; value: string; onChange: (id: string) => void }) {
  return (
    <label className="flex items-center gap-1.5 text-sm text-muted">
      Model
      <select className="input max-w-[18rem]" value={value} onChange={(e) => onChange(e.target.value)} aria-label="Model">
        {models.length === 0 && <option value="">Loading…</option>}
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
            {m.supports_tools ? ' · tools' : ''}
          </option>
        ))}
      </select>
    </label>
  )
}

function ModeToggle({ mode, onChange, toolsSupported }: { mode: Mode; onChange: (m: Mode) => void; toolsSupported: boolean }) {
  return (
    <div role="radiogroup" aria-label="Context mode" className="flex overflow-hidden rounded-md border border-line text-sm">
      {(['injection', 'tool'] as const).map((m) => (
        <button
          key={m}
          type="button"
          role="radio"
          aria-checked={mode === m}
          disabled={m === 'tool' && !toolsSupported}
          title={m === 'tool' && !toolsSupported ? 'This model does not support tool calls' : undefined}
          onClick={() => onChange(m)}
          className={`px-2.5 py-1.5 disabled:cursor-not-allowed disabled:opacity-40 ${mode === m ? 'bg-accent text-accent-fg' : 'bg-panel text-muted hover:text-fg'}`}
        >
          {m}
        </button>
      ))}
    </div>
  )
}

const STARTERS = [
  "Let's keep going on my project. Where did I leave off?",
  'What do you know about me?',
  'Summarize the decisions I made this week.',
]

function EmptyChat({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 pt-16 text-center">
      <Bot size={32} className="text-muted" aria-hidden />
      <p className="text-sm text-muted">
        Pick any model. PAM injects only the memory this turn needs and shows the token savings on the right.
      </p>
      <div className="flex flex-col gap-2">
        {STARTERS.map((q) => (
          <button key={q} type="button" className="btn justify-center" onClick={() => onPick(q)}>
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}

function MessageView({
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
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-lg bg-accent/15 px-3.5 py-2 text-sm">{message.text}</div>
      </div>
    )
  }
  if (message.kind === 'switch') {
    return (
      <div className="flex items-center gap-3 text-xs text-muted" role="separator">
        <div className="h-px flex-1 bg-line" />
        <ArrowRightLeft size={12} aria-hidden /> switched to {labelOf(message.model)}
        <div className="h-px flex-1 bg-line" />
      </div>
    )
  }
  if (message.kind === 'tool') {
    return (
      <div className="flex items-start gap-2 rounded-md border border-line bg-raised/50 px-3 py-2 text-xs">
        <Wrench size={14} className="mt-0.5 shrink-0 text-muted" aria-hidden />
        <div className="min-w-0">
          <span className="font-mono">{message.name}</span>
          <span className="ml-1 break-all font-mono text-muted">{message.args}</span>
          <div className="text-muted">→ {message.summary}</div>
        </div>
      </div>
    )
  }
  return (
    <div className="space-y-1.5" data-streaming={message.streaming ? 'true' : undefined}>
      <div className="flex items-center gap-2 text-xs text-muted">
        <Bot size={14} aria-hidden />
        {labelOf(message.model)}
        {message.streaming && <Loader2 size={12} className="animate-spin" aria-label="Streaming" />}
        {message.usage && (message.usage.prompt !== null || message.usage.completion !== null) && (
          <span className="tabular-nums">
            · {message.usage.prompt ?? '?'} in / {message.usage.completion ?? '?'} out
          </span>
        )}
      </div>
      {message.text ? <Markdown>{message.text}</Markdown> : message.streaming ? <p className="text-sm text-muted">Thinking…</p> : null}
      {message.error && (
        <ErrorNote
          error={new ApiError(0, message.error.retryable ? 'RETRYABLE' : 'ERROR', message.error.message)}
          action={
            message.error.retryable && (
              <button type="button" className="btn" disabled={disabled} onClick={() => onRetry(message.error!.prompt)}>
                <RotateCcw size={14} /> Retry
              </button>
            )
          }
        />
      )}
    </div>
  )
}

function ContextPanel({
  context,
  budget,
  goal,
  switches,
  turns,
}: {
  context: ContextEvent | null
  budget?: number
  goal?: string | null
  switches: string[]
  turns?: number
}) {
  const [showRendered, setShowRendered] = useState(true)
  const docs = useMemo(() => context?.doc_ids.length ?? 0, [context])
  return (
    <aside aria-label="Injected context" className="flex w-[22rem] shrink-0 flex-col border-l border-line bg-panel/50">
      <div className="space-y-4 border-b border-line p-4">
        <div className="label">Context this turn</div>
        {context ? (
          <>
            <TokenMeter used={context.tokens_used} baseline={context.baseline_tokens} saved={context.tokens_saved} budget={budget} />
            <div className="text-xs text-muted">{docs} documents cited</div>
          </>
        ) : (
          <p className="text-sm text-muted">Send a message to see what PAM injects.</p>
        )}
      </div>
      {(goal || switches.length > 0) && (
        <div className="space-y-2 border-b border-line p-4 text-xs">
          <div className="label">Working memory</div>
          {goal && (
            <div>
              <span className="text-muted">Goal: </span>
              {goal}
            </div>
          )}
          {switches.length > 0 && (
            <div>
              <span className="text-muted">Models: </span>
              {switches.join(' → ')}
            </div>
          )}
          {turns !== undefined && <div className="text-muted">{turns} recent turns carried to the next model</div>}
        </div>
      )}
      {context && (
        <div className="flex min-h-0 flex-1 flex-col">
          <button
            type="button"
            className="flex items-center justify-between px-4 py-2 text-left text-xs text-muted hover:text-fg"
            onClick={() => setShowRendered((v) => !v)}
            aria-expanded={showRendered}
          >
            <span className="label">Injected bundle</span>
            <span>{showRendered ? 'hide' : 'show'}</span>
          </button>
          {showRendered && (
            <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
              <Markdown className="prose-compact text-xs">{context.rendered}</Markdown>
            </div>
          )}
        </div>
      )}
    </aside>
  )
}
