import { Link } from 'react-router-dom'
import { setConnectorAgent, useConnectors } from '../../lib/connectors'
import { ChoiceRow, choiceClass } from './FormParts'

/**
 * Checklist of the connectors an agent may use.
 *
 * Behavior:
 *     Ticking a box updates the connector registry immediately; it is not part
 *     of the agent's Save. Disabled connectors are listed but marked as off.
 * Parameters:
 *     agent: Name of the agent being edited; empty until the name is valid.
 */
export function AgentConnectors({ agent }: { agent: string }) {
  const connectors = useConnectors()
  if (connectors.length === 0) {
    return (
      <p className="text-sm text-muted">
        No connectors yet. <Link to="/connectors" className="text-accent underline">Add one</Link>.
      </p>
    )
  }
  return (
    <fieldset className="well min-w-0 p-4" disabled={!agent}>
      <legend className="sr-only">Connectors</legend>
      <div className="space-y-0.5">
        {connectors.map((c) => (
          <ChoiceRow key={c.id}>
            <input type="checkbox" className={choiceClass} checked={c.agents.includes(agent)} onChange={(e) => setConnectorAgent(c.id, agent, e.target.checked)} />
            <span className="min-w-0 flex-1 truncate">{c.name || 'Untitled'}</span>
            <span className="text-xs text-muted">{c.enabled ? `${c.tools.length} tools` : 'disabled'}</span>
          </ChoiceRow>
        ))}
      </div>
      {!agent && <p className="mt-2 px-1 text-xs text-muted">Name the agent first.</p>}
    </fieldset>
  )
}
