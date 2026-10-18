import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, CheckCircle2, Loader2, Plus, Save, Trash2, XCircle } from 'lucide-react'
import { useRef, useState } from 'react'
import { api, type CheckResult, type KeyProvider, type KeyStatus } from '../api/client'
import { choiceClass, Field, FormSection } from '../components/agents/FormParts'
import { ErrorNote } from '../components/ErrorNote'
import { PageHeader } from '../components/PageHeader'
import { cliHints } from '../lib/cliHints'
import type { ModelEntry } from '../types/generated'

/** One editable model row; `key` keeps React's identity stable while the id is being typed. */
interface Row extends ModelEntry {
  key: number
}

const PRESETS: ModelEntry[] = [
  { id: 'anthropic/claude-sonnet-5-5', label: 'Claude Sonnet (Anthropic)', supports_tools: true },
  { id: 'openrouter/meta-llama/llama-3.3-70b-instruct:free', label: 'Llama 3.3 70B (OpenRouter, free)', supports_tools: false },
  { id: 'openrouter/google/gemini-2.0-flash-exp:free', label: 'Gemini 2.0 Flash (OpenRouter, free)', supports_tools: true },
  { id: 'ollama/qwen2.5:7b', label: 'Qwen 2.5 7B (Ollama, local)', supports_tools: true },
]

const PROVIDERS: { provider: KeyProvider; label: string; placeholder: string; secret: boolean }[] = [
  { provider: 'anthropic', label: 'Anthropic API key', placeholder: 'sk-ant-…', secret: true },
  { provider: 'openrouter', label: 'OpenRouter API key', placeholder: 'sk-or-…', secret: true },
  { provider: 'ollama', label: 'Ollama base URL', placeholder: 'http://ollama:11434', secret: false },
]

const plain = ({ id, label, supports_tools }: Row): ModelEntry => ({ id: id.trim(), label: label.trim(), supports_tools })

/**
 * Settings page: manage chat models and provider keys.
 *
 * Behavior:
 *     Edits the model list locally and saves it with `PUT /models`, then refreshes the `['models']`
 *     query so the Chat picker updates without a reload. Each saved model has a Check button that
 *     pings it. Provider keys are write-only: the page shows only "set (…last4)" and where the value
 *     comes from, and clears a key field after every save.
 */
export default function SettingsPage() {
  const queryClient = useQueryClient()
  const models = useQuery({ queryKey: ['models'], queryFn: api.models })
  const keys = useQuery({ queryKey: ['settings', 'keys'], queryFn: api.keyStatus })
  const nextKey = useRef(0)
  const [rows, setRows] = useState<Row[] | null>(null)
  const [checks, setChecks] = useState<Record<string, CheckResult | 'pending'>>({})
  const [preset, setPreset] = useState('')

  // Until the user edits, the draft is the saved list; saved rows get negative keys, new rows positive ones.
  const saved = models.data ?? []
  const base: Row[] = saved.map((m, i) => ({ ...m, key: -(i + 1) }))
  const draft = rows ?? base
  const dirty = JSON.stringify(draft.map(plain)) !== JSON.stringify(saved)
  const update = (key: number, change: Partial<ModelEntry>) =>
    setRows((list) => (list ?? base).map((r) => (r.key === key ? { ...r, ...change } : r)))

  const save = useMutation({
    mutationFn: () => api.saveModels(draft.map(plain)),
    onSuccess: (list) => {
      setRows(null)
      setChecks({})
      queryClient.setQueryData(['models'], list)
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
  })

  const runChecks = async (id?: string) => {
    const ids = id ? [id] : saved.map((m) => m.id)
    setChecks((c) => ({ ...c, ...Object.fromEntries(ids.map((i) => [i, 'pending' as const])) }))
    try {
      const results = await api.checkModels(id)
      setChecks((c) => ({ ...c, ...Object.fromEntries(results.map((r) => [r.id, r])) }))
    } catch (err) {
      const error = err instanceof Error ? err.message : 'Check failed'
      setChecks((c) => ({ ...c, ...Object.fromEntries(ids.map((i) => [i, { id: i, ok: false, latency_ms: 0, error }])) }))
    }
  }

  const addRow = (entry: ModelEntry) => setRows((list) => [...(list ?? base), { ...entry, key: ++nextKey.current }])
  const duplicate = (id: string) => id.trim() !== '' && draft.filter((r) => r.id.trim() === id.trim()).length > 1

  return (
    <div className="enter flex flex-col lg:min-h-0 lg:flex-1">
      <PageHeader title="Settings" subtitle="Chat models and the provider keys they use." cli={cliHints.modelsList()} />
      <div className="panel p-5 sm:p-8 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
        <div className="divide-y divide-edge/10">
          <FormSection title="Models" description="LiteLLM model ids shown in the Chat picker. Saving does not contact the provider; use Check.">
            <div className="space-y-4">
              {(models.error || save.error) && <ErrorNote error={models.error ?? save.error} />}
              {models.isPending && <p className="text-sm text-muted">Loading models…</p>}
              {models.isSuccess && draft.length === 0 && (
                <p className="text-sm text-muted">No models yet. Add one below, or pick a preset, then save.</p>
              )}
              <ul className="space-y-3">
                {draft.map((row) => {
                  const result = checks[row.id.trim()]
                  const isSaved = saved.some((m) => m.id === row.id.trim()) && !dirty
                  return (
                    <li key={row.key} className="well grid gap-3 p-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)_auto_auto]">
                      <Field label="Model id" hint={duplicate(row.id) ? 'Duplicate id' : undefined} invalid={duplicate(row.id)}>
                        <input
                          className="input font-mono"
                          value={row.id}
                          onChange={(e) => update(row.key, { id: e.target.value })}
                          placeholder="provider/model"
                          autoComplete="off"
                          spellCheck={false}
                        />
                      </Field>
                      <Field label="Label">
                        <input className="input" value={row.label} onChange={(e) => update(row.key, { label: e.target.value })} autoComplete="off" />
                      </Field>
                      <label className="flex items-center gap-2 self-end pb-2 text-sm">
                        <input
                          type="checkbox"
                          className={choiceClass}
                          checked={row.supports_tools ?? false}
                          onChange={(e) => update(row.key, { supports_tools: e.target.checked })}
                        />
                        Supports tools
                      </label>
                      <div className="flex items-end gap-2">
                        <button
                          type="button"
                          className="btn"
                          disabled={!isSaved || result === 'pending'}
                          title={isSaved ? undefined : 'Save the list first'}
                          onClick={() => runChecks(row.id.trim())}
                        >
                          {result === 'pending' ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Activity size={15} strokeWidth={1.75} aria-hidden />}
                          Check
                        </button>
                        <button
                          type="button"
                          className="icon-btn h-9 w-9"
                          aria-label={`Remove ${row.label || row.id || 'model'}`}
                          onClick={() => setRows((list) => (list ?? base).filter((r) => r.key !== row.key))}
                        >
                          <Trash2 size={15} strokeWidth={1.75} aria-hidden />
                        </button>
                      </div>
                      {result && result !== 'pending' && (
                        <p role="status" className={`flex items-start gap-2 text-sm lg:col-span-4 ${result.ok ? 'text-ok' : 'text-bad'}`}>
                          {result.ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" aria-hidden /> : <XCircle size={16} className="mt-0.5 shrink-0" aria-hidden />}
                          <span className="min-w-0 break-words">{result.ok ? `OK, ${result.latency_ms} ms` : `Failed: ${result.error ?? 'unknown error'}`}</span>
                        </p>
                      )}
                    </li>
                  )
                })}
              </ul>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className="btn" onClick={() => addRow({ id: '', label: '', supports_tools: false })}>
                  <Plus size={15} strokeWidth={1.75} aria-hidden /> Add model
                </button>
                <select
                  className="input"
                  aria-label="Add from preset"
                  value={preset}
                  onChange={(e) => {
                    const entry = PRESETS.find((p) => p.id === e.target.value)
                    if (entry) addRow(entry)
                    setPreset('')
                  }}
                >
                  <option value="">Add from preset…</option>
                  {PRESETS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
                <div className="ml-auto flex items-center gap-2">
                  <button type="button" className="btn" disabled={dirty || saved.length === 0} onClick={() => runChecks()}>
                    <Activity size={15} strokeWidth={1.75} aria-hidden /> Check all
                  </button>
                  <button type="button" className="btn btn-primary px-5" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
                    {save.isPending ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Save size={16} strokeWidth={1.75} aria-hidden />} Save models
                  </button>
                </div>
              </div>
              <p aria-live="polite" className="min-h-5 text-sm text-ok">
                {save.isSuccess && !dirty ? 'Saved. The Chat picker is up to date.' : ''}
              </p>
            </div>
          </FormSection>

          <FormSection title="Provider keys" description="Keys are write-only: they are stored on the server and never shown again. A key saved here overrides one from the environment.">
            <div className="space-y-4">
              {keys.error && <ErrorNote error={keys.error} />}
              {PROVIDERS.map((p) => (
                <KeyRow key={p.provider} {...p} status={keys.data?.find((k) => k.provider === p.provider)} />
              ))}
            </div>
          </FormSection>
        </div>
      </div>
    </div>
  )
}

/**
 * One provider row: current status plus a write-only input.
 *
 * Behavior:
 *     Shows "set (…last4)" and the source for keys, or the URL for Ollama. Saving sends the typed
 *     value and clears the field; Clear removes the stored value (the environment value, if any,
 *     applies again).
 * Parameters:
 *     provider: Which provider this row edits.
 *     label: Field caption.
 *     placeholder: Example value.
 *     secret: True for API keys (password field), false for the Ollama URL.
 *     status: Current status from `GET /settings/keys`.
 */
function KeyRow({ provider, label, placeholder, secret, status }: { provider: KeyProvider; label: string; placeholder: string; secret: boolean; status?: KeyStatus }) {
  const queryClient = useQueryClient()
  const [value, setValue] = useState('')
  const write = useMutation({
    mutationFn: (next: string | null) => api.setKey(provider, next),
    onSuccess: () => {
      setValue('')
      queryClient.invalidateQueries({ queryKey: ['settings', 'keys'] })
    },
  })
  const summary = !status
    ? 'Loading…'
    : !status.is_set
      ? 'not set'
      : secret
        ? `set${status.last4 ? ` (…${status.last4})` : ''}, from ${status.source}`
        : `${status.value ?? 'set'}, from ${status.source}`
  return (
    <form
      className="well grid gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_auto]"
      onSubmit={(e) => {
        e.preventDefault()
        if (value.trim()) write.mutate(value)
      }}
    >
      <Field label={label} hint={summary}>
        <input
          className="input font-mono"
          type={secret ? 'password' : 'url'}
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
        />
      </Field>
      <div className="flex items-end gap-2">
        <button type="submit" className="btn btn-primary" disabled={!value.trim() || write.isPending}>
          {write.isPending ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Save size={15} strokeWidth={1.75} aria-hidden />} Save
        </button>
        <button type="button" className="btn" disabled={status?.source !== 'settings' || write.isPending} onClick={() => write.mutate(null)}>
          Clear
        </button>
      </div>
      {write.error && (
        <div className="sm:col-span-2">
          <ErrorNote error={write.error} />
        </div>
      )}
    </form>
  )
}
