import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

/**
 * Select an agent from `GET /agents`.
 *
 * Behavior:
 *     Falls back to a single `default` option while the list loads or fails.
 * Parameters:
 *     value: Selected agent name.
 *     onChange: Called with the new agent name.
 *     id: Element id for an external `<label htmlFor>`.
 */
export function AgentSelect({ value, onChange, id }: { value: string; onChange: (name: string) => void; id?: string }) {
  const agents = useQuery({ queryKey: ['agents'], queryFn: api.listAgents })
  const names = agents.data?.map((a) => a.name) ?? ['default']
  return (
    <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)} aria-label={id ? undefined : 'Agent'}>
      {(names.includes(value) ? names : [value, ...names]).map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </select>
  )
}
