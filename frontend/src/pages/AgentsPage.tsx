import { PageHeader } from '../components/PageHeader'
import { cliHints } from '../lib/cliHints'

/** Agents page (placeholder until its T15 subtask). */
export default function AgentsPage() {
  return <PageHeader title="Agents" subtitle="Create and edit agents." cli={cliHints.agentCreate()} />
}
