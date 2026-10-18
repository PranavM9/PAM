import { PageHeader } from '../components/PageHeader'
import { cliHints } from '../lib/cliHints'

/** Guides page (placeholder until its T15 subtask). */
export default function GuidesPage() {
  return <PageHeader title="Guides" subtitle="Export and connection guides." cli={cliHints.mcpServe()} />
}
