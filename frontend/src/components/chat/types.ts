import type { ConnectorCard, ContextEvent } from '../../types/generated'

/** How memory reaches the model: injected into the prompt, or fetched through tool calls. */
export type Mode = 'injection' | 'tool'

/** One entry in a chat transcript: a turn, a model-switch divider, or a tool call. */
export type Message =
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
  | { id: string; kind: 'tool'; name: string; args: string; summary: string; cards?: ConnectorCard[] }

/** A chat session as remembered by this browser (the API has no session list). */
export interface StoredSession {
  id: string
  title: string
  agent: string
  updated: string
  ended: boolean
  messages: Message[]
  context: ContextEvent | null
}
