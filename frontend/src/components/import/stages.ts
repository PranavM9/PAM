import type { JobStatus } from '../../types/generated'

export type ImportSource = 'claude' | 'chatgpt' | 'gemini'

export const SOURCES: { id: ImportSource; label: string; hint: string }[] = [
  { id: 'claude', label: 'Claude', hint: 'Conversations zip' },
  { id: 'chatgpt', label: 'ChatGPT', hint: 'Data export zip' },
  { id: 'gemini', label: 'Gemini', hint: 'Google Takeout' },
]

export const STEPS: { stage: JobStatus['stage']; label: string }[] = [
  { stage: 'extract', label: 'Extract' },
  { stage: 'normalize', label: 'Normalize' },
  { stage: 'derive', label: 'Derive' },
  { stage: 'index', label: 'Index' },
  { stage: 'cluster', label: 'Cluster' },
]

export const ORDER: JobStatus['stage'][] = ['queued', 'extract', 'normalize', 'derive', 'index', 'cluster', 'done']
