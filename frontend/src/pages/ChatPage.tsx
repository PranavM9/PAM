import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, History, Loader2, MessageSquarePlus, PanelRight } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, chatStream } from '../api/client'
import { AgentSelect } from '../components/AgentSelect'
import { ErrorNote } from '../components/ErrorNote'
import { ResizeHandle } from '../components/Resizable'
import { usePaneSize } from '../lib/usePaneSize'
import { ModelSelect } from '../components/chat/ChatControls'
import { Composer } from '../components/chat/Composer'
import { ContextPanel } from '../components/chat/ContextPanel'
import { AssistantAvatar, EmptyChat, MessageView } from '../components/chat/MessageView'
import { SessionList } from '../components/chat/SessionList'
import type { Message, Mode, StoredSession } from '../components/chat/types'
import type { WriteResult } from '../types/generated'

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

/** How often open sessions are checked for the server's idle auto-end (CHG-0026). */
const IDLE_POLL_MS = 30_000

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
 *     returns the last 8 turns of a session. The server ends a session after
 *     its idle time and saves an episode; every 30 s the page asks for the
 *     status of each open session and shows "ended after inactivity". From `xl` up the sessions,
 *     conversation and context sit side by side; below it the sessions and
 *     context columns open as drawers from the conversation header.
 */
export default function ChatPage() {
  const [sessions, setSessions] = useState<StoredSession[]>(loadSessions)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [draft, setDraft] = useState<StoredSession>(() => blank('default'))
  const [pickedModel, setModel] = useState<string>('')
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [requestError, setRequestError] = useState<unknown>(null)
  const [ended, setEnded] = useState<WriteResult | null>(null)
  const [autoEnded, setAutoEnded] = useState<Record<string, string | null>>({})
  const sessionsRef = useRef(sessions)
  const sessionsPane = usePaneSize({ id: 'chat-sessions', initial: 240, min: 200, max: 360 })
  const contextPane = usePaneSize({ id: 'chat-context', initial: 336, min: 280, max: 560 })
  const [sessionsOpen, setSessionsOpen] = useState(false)
  const [contextOpen, setContextOpen] = useState(false)
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
  const mode: Mode = current?.supports_tools ? 'tool' : 'injection'

  const working = useQuery({
    queryKey: ['session', activeId],
    queryFn: () => api.getSession(activeId!),
    enabled: Boolean(activeId),
  })

  useEffect(() => {
    sessionsRef.current = sessions
    saveSessions(sessions)
  }, [sessions])

  useEffect(() => {
    const sweep = async () => {
      for (const s of sessionsRef.current.filter((x) => x.id && !x.ended)) {
        try {
          const state = await api.getSession(s.id)
          if (state.status !== 'ended') continue
          setAutoEnded((m) => ({ ...m, [s.id]: state.promoted_episode_id ?? null }))
          setSessions((list) => list.map((x) => (x.id === s.id ? { ...x, ended: true } : x)))
          for (const key of ['session', 'graph', 'vault-tree']) queryClient.invalidateQueries({ queryKey: [key] })
        } catch {
          // Unreachable API or unknown session: try again on the next tick.
        }
      }
    }
    const timer = setInterval(sweep, IDLE_POLL_MS)
    window.addEventListener('focus', sweep)
    return () => {
      clearInterval(timer)
      window.removeEventListener('focus', sweep)
    }
  }, [queryClient])

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
                  {
                    id: uid(), kind: 'tool', name: event.name, args: JSON.stringify(event.arguments),
                    summary: event.result_summary, cards: event.cards ?? [],
                  },
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

  const closeSessions = useCallback(() => setSessionsOpen(false), [])
  const closeContext = useCallback(() => setContextOpen(false), [])

  return (
    <div className="flex min-h-0 flex-1 gap-4 xl:gap-0">
      <SessionList
        sessions={sessions}
        activeId={activeId}
        onOpen={(id) => {
          openSession(id)
          setSessionsOpen(false)
        }}
        onNew={() => {
          newChat()
          setSessionsOpen(false)
        }}
        disabled={streaming}
        open={sessionsOpen}
        onClose={closeSessions}
        style={sessionsPane.style}
      />
      <ResizeHandle pane={sessionsPane} side="before" label="Resize sessions panel" breakpoint="xl" />

      <section className="panel flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden" aria-label="Conversation">
        <header className="flex shrink-0 flex-wrap items-center gap-2 border-b border-edge/[0.08] px-4 py-3 sm:px-5">
          <button
            type="button"
            className="icon-btn xl:hidden"
            onClick={() => setSessionsOpen(true)}
            aria-label="Show sessions"
            aria-controls="chat-sessions"
            aria-expanded={sessionsOpen}
          >
            <History size={18} strokeWidth={1.75} />
          </button>
          <div className="flex min-w-0 items-center gap-3">
            <AssistantAvatar />
            <div className="min-w-0 leading-tight">
              <h1 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-fg">
                {activeId ? session.title : 'New chat'}
              </h1>
              <p className="truncate font-mono text-[11px] text-muted" title="Session id">
                {activeId ?? 'not started'}
              </p>
            </div>
          </div>
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
            <AgentSelect value={agentName} onChange={(name) => update(activeId, (s) => ({ ...s, agent: name }))} />
            <ModelSelect models={modelList} loaded={models.isSuccess} value={model} onChange={pickModel} />
            <button
              type="button"
              className="btn"
              disabled={!activeId || session.ended || streaming || end.isPending}
              onClick={() => activeId && end.mutate(activeId)}
            >
              {end.isPending ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} strokeWidth={1.75} />}
              End session
            </button>
            <button
              type="button"
              className="icon-btn xl:hidden"
              onClick={() => setContextOpen(true)}
              aria-label="Show context"
              aria-controls="chat-context"
              aria-expanded={contextOpen}
            >
              <PanelRight size={18} strokeWidth={1.75} />
            </button>
          </div>
        </header>

        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8" aria-live="polite" aria-busy={streaming}>
          {session.messages.length === 0 ? (
            <EmptyChat onPick={(q) => send(q)} />
          ) : (
            <ol className="mx-auto max-w-3xl space-y-6">
              {session.messages.map((m) => (
                <li key={m.id}>
                  <MessageView message={m} labelOf={labelOf} onRetry={(prompt) => send(prompt, m.id)} disabled={streaming} />
                </li>
              ))}
            </ol>
          )}
        </div>

        <footer className="shrink-0 space-y-3 px-4 pb-4 pt-2 sm:px-8 sm:pb-5">
          <div className="mx-auto max-w-3xl space-y-3">
            <ErrorNote error={requestError ?? end.error} />
            {(ended || session.ended) && (
              <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-ok/30 bg-ok/10 px-4 py-3 text-sm">
                <CheckCircle2 size={16} className="text-ok" aria-hidden />
                <span className="min-w-0 flex-1">
                  {!ended && activeId && activeId in autoEnded ? 'Session ended after inactivity' : 'Session ended'}
                  {ended?.path ? (
                    <>
                      {' '}and saved as <code className="break-all font-mono text-xs">{ended.path}</code>
                    </>
                  ) : activeId && autoEnded[activeId] ? (
                    <>
                      {' '}and saved as episode <code className="break-all font-mono text-xs">{autoEnded[activeId]}</code>
                    </>
                  ) : null}
                  .
                </span>
                <button type="button" className="btn" onClick={newChat}>
                  <MessageSquarePlus size={15} strokeWidth={1.75} /> New chat
                </button>
              </div>
            )}
          </div>
          <Composer
            value={input}
            onChange={setInput}
            onSend={() => send(input)}
            onStop={() => abort.current?.abort()}
            streaming={streaming}
            canSend={Boolean(model)}
            ended={session.ended}
          />
        </footer>
      </section>

      <ResizeHandle pane={contextPane} side="after" label="Resize context panel" breakpoint="xl" />
      <ContextPanel
        style={contextPane.style}
        context={session.context}
        budget={agent?.token_budget}
        goal={working.data?.goal}
        switches={working.data?.models_used?.map((s) => labelOf(s.to_model)) ?? []}
        turns={working.data?.recent_turns?.length}
        open={contextOpen}
        onClose={closeContext}
      />
    </div>
  )
}

function blank(agent: string): StoredSession {
  return { id: '', title: 'New chat', agent, updated: new Date().toISOString(), ended: false, messages: [], context: null }
}
