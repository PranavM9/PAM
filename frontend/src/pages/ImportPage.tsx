import { PageHeader } from '../components/PageHeader'
import { cliHints } from '../lib/cliHints'

/** Import page (placeholder until its T15 subtask). */
export default function ImportPage() {
  return <PageHeader title="Import" subtitle="Import an export from Claude, ChatGPT or Gemini." cli={cliHints.importRun()} />
}
