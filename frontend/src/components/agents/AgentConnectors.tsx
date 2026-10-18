import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { editable, useConnectors, useSaveConnector } from '../../lib/connectors'
import { ErrorNote } from '../ErrorNote'
import { ChoiceRow, choiceClass } from './FormParts'

/**
 * Checklist of the connectors an agent may use.
 *
 * Behavior:
 *     Ticking a box saves the connector right away (`PUT /connectors/{id}` with
 *     the agent added to or removed from its `agents`); it is not part of the
 *     agent's Save. The box changes at once and keeps that state until the save
 *     and the list refetch finish. Archived connectors are not listed; disabled
 *     ones are listed but marked as off. A failed save shows its error and the
 *     box reverts.
 * Parameters:
 *     agent: Name of the agent being edited; empty until the name is valid.
 */
export function AgentConnectors({ agent }: { agent: string }) {
  const list = useConnectors()
  const save = useSaveConnector()
  const [pending, setPending] = useState<string | null>(null)
  // The tick shows at once; it is dropped when the save settles (after the list refetch) or fails.
  const [shown, setShown] = useState<Record<string, boolean>>({})
  const connectors = (list.data ?? []).map(editable)

  if (list.isLoading) return <p className="text-sm text-muted">Loading connectors…</p>
  if (list.error) return <ErrorNote error={list.error} />
  if (connectors.length === 0) {
    return (
      <p className="text-sm text-muted">
        No connectors yet. <Link to="/connectors" className="text-accent underline">Add one</Link>.
      </p>
    )
  }
  const toggle = (id: string, allowed: boolean) => {
    const c = connectors.find((x) => x.id === id)
    if (!c) return
    const agents = allowed ? [...new Set([...c.agents, agent])] : c.agents.filter((a) => a !== agent)
    setPending(id)
    setShown((s) => ({ ...s, [id]: allowed }))
    save.mutate(
      { ...c, agents },
      {
        onSettled: () => {
          setPending(null)
          setShown((s) => Object.fromEntries(Object.entries(s).filter(([k]) => k !== id)))
        },
      },
    )
  }
  return (
    <div className="space-y-2">
      <fieldset className="well min-w-0 p-4" disabled={!agent || save.isPending} data-testid="agent-connectors">
        <legend className="sr-only">Connectors</legend>
        <div className="space-y-0.5">
          {connectors.map((c) => (
            <ChoiceRow key={c.id}>
              <input
                type="checkbox"
                className={choiceClass}
                checked={shown[c.id] ?? c.agents.includes(agent)}
                onChange={(e) => toggle(c.id, e.target.checked)}
                data-connector={c.id}
              />
              <span className="min-w-0 flex-1 truncate">{c.name || c.id}</span>
              {pending === c.id ? (
                <Loader2 size={14} className="animate-spin text-accent" aria-label="Saving" />
              ) : (
                <span className="text-xs text-muted">{c.enabled ? `${c.tools.length} tools` : 'disabled'}</span>
              )}
            </ChoiceRow>
          ))}
        </div>
        {!agent && <p className="mt-2 px-1 text-xs text-muted">Name the agent first.</p>}
      </fieldset>
      <ErrorNote error={save.error} />
    </div>
  )
}
