import { PageHeader } from '../components/PageHeader'
import { cliHints } from '../lib/cliHints'

/** Search page (placeholder until its T15 subtask). */
export default function SearchPage() {
  return <PageHeader title="Search" subtitle="Hybrid search and context bundles." cli={cliHints.search()} />
}
