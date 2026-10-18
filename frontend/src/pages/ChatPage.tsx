import { PageHeader } from '../components/PageHeader'
import { cliHints } from '../lib/cliHints'

/** Chat page (placeholder until its T15 subtask). */
export default function ChatPage() {
  return <PageHeader title="Chat" subtitle="Chat with any model on top of your memory." cli={cliHints.chat()} />
}
