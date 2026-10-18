import { PageHeader } from '../components/PageHeader'
import { cliHints } from '../lib/cliHints'

/** Graph page (placeholder until its T15 subtask). */
export default function GraphPage() {
  return <PageHeader title="Graph" subtitle="Projects, episodes and similarity links." cli={cliHints.graphExport()} />
}
