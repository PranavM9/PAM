import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Loader2, Play, XCircle } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import type { EditableConnector, EditableTool } from '../../lib/connectors'
import { ErrorNote } from '../ErrorNote'
import { ChoiceRow, Field, choiceClass } from '../agents/FormParts'
import { ConnectorCards } from './Cards'

type Values = Record<string, string | boolean>

/** Turn the form's values into the arguments object, typed by each parameter; empty optional fields are left out. */
function toArgs(params: EditableTool['params'], values: Values): Record<string, unknown> {
  const args: Record<string, unknown> = {}
  for (const p of params) {
    const v = values[p.name]
    if (p.type === 'boolean') {
      if (v === true || p.required) args[p.name] = v === true
    } else if (typeof v === 'string' && v.trim() !== '') {
      args[p.name] = p.type === 'number' && !Number.isNaN(Number(v)) ? Number(v) : v
    }
  }
  return args
}

/**
 * "Test tool" panel: call one tool of a saved connector and show what came back.
 *
 * Behavior:
 *     Builds a form from the chosen tool's `params` (text, number or checkbox,
 *     required ones marked) and posts it to `/connectors/{id}/tools/{tool}/call`.
 *     Shows the HTTP status, latency, ok or the error code and message, the
 *     display cards, and the raw JSON in a collapsed section. A request error
 *     (e.g. 404 for an unsaved tool) is shown as an error note.
 * Parameters:
 *     connector: The saved connector to test.
 */
export function TestToolPanel({ connector }: { connector: EditableConnector }) {
  const [toolName, setToolName] = useState(connector.tools[0]?.name ?? '')
  const [values, setValues] = useState<Values>({})
  const tool = connector.tools.find((t) => t.name === toolName) ?? connector.tools[0]
  const call = useMutation({
    mutationFn: (t: EditableTool) => api.callConnectorTool(connector.id, t.name, toArgs(t.params, values)),
  })

  if (!tool) return <p className="text-sm text-muted">Add a tool and save the connector to test it.</p>

  const submit = (e: FormEvent) => {
    e.preventDefault()
    call.mutate(tool)
  }
  const result = call.data
  const errorCode = typeof result?.error?.code === 'string' ? result.error.code : null
  const errorMessage = typeof result?.error?.message === 'string' ? result.error.message : null

  return (
    <div className="space-y-4" data-testid="test-tool">
      <form className="space-y-4" onSubmit={submit}>
        <Field label="Tool">
          <select
            className="input font-mono"
            value={tool.name}
            onChange={(e) => {
              setToolName(e.target.value)
              setValues({})
              call.reset()
            }}
          >
            {connector.tools.map((t) => (
              <option key={t.name} value={t.name}>{t.name}</option>
            ))}
          </select>
        </Field>
        {tool.description && <p className="text-[13px] leading-relaxed text-muted">{tool.description}</p>}
        {tool.params.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2">
            {tool.params.map((p) =>
              p.type === 'boolean' ? (
                <ChoiceRow key={p.name} className="self-end">
                  <input
                    type="checkbox"
                    className={choiceClass}
                    checked={values[p.name] === true}
                    onChange={(e) => setValues({ ...values, [p.name]: e.target.checked })}
                  />
                  <span className="font-mono">{p.name}</span>
                </ChoiceRow>
              ) : (
                <Field key={p.name} label={`${p.name}${p.required ? ' (required)' : ''}`} hint={p.description || undefined}>
                  <input
                    className="input font-mono"
                    name={p.name}
                    type={p.type === 'number' ? 'number' : 'text'}
                    step="any"
                    required={p.required}
                    value={typeof values[p.name] === 'string' ? (values[p.name] as string) : ''}
                    onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                  />
                </Field>
              ),
            )}
          </div>
        )}
        <button type="submit" className="btn btn-primary" disabled={call.isPending}>
          {call.isPending ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Play size={15} strokeWidth={1.75} aria-hidden />}
          Call {tool.name}
        </button>
      </form>

      <ErrorNote error={call.error} />
      {result && (
        <div className="space-y-3" data-testid="test-result" data-ok={result.ok ? 'true' : 'false'}>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            {result.ok ? (
              <span className="inline-flex items-center gap-1.5 font-medium text-ok">
                <CheckCircle2 size={15} aria-hidden /> ok
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 font-medium text-bad">
                <XCircle size={15} aria-hidden /> {errorCode ?? 'error'}
              </span>
            )}
            {result.status != null && <span className="font-mono text-xs text-muted">HTTP {result.status}</span>}
            <span className="font-mono text-xs text-muted">{result.latency_ms} ms</span>
            <span className="text-xs text-muted">{result.cards?.length ?? 0} cards</span>
          </p>
          {errorMessage && <p className="text-sm text-fg/90">{errorMessage}</p>}
          {result.cards && result.cards.length > 0 && <ConnectorCards cards={result.cards} />}
          <details className="well p-3 text-xs">
            <summary className="cursor-pointer text-muted">Raw JSON</summary>
            <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-fg/85">
              {JSON.stringify(result, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  )
}
