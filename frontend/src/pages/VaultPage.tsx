import { PageHeader } from '../components/PageHeader'
import { cliHints } from '../lib/cliHints'

/** Vault page (placeholder until its T15 subtask). */
export default function VaultPage() {
  return <PageHeader title="Vault" subtitle="Browse every file in the vault." cli={cliHints.episodeShow()} />
}
