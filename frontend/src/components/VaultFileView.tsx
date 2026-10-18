import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { api } from '../api/client'
import { cliForPath } from '../lib/cliHints'
import { CliHint } from './CliHint'
import { ErrorNote } from './ErrorNote'
import { Markdown } from './Markdown'

function display(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.length ? value.map(display).join(', ') : '[]'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/**
 * Render one vault file from `GET /vault/file`: frontmatter table plus body.
 *
 * Behavior:
 *     Nested frontmatter values are shown as JSON; the body is rendered as
 *     Markdown in `prose`. Shows the matching `pam … show` command.
 * Parameters:
 *     path: Vault-relative path of the file.
 *     agent: Agent whose scope applies, if any.
 */
export function VaultFileView({ path, agent }: { path: string; agent?: string }) {
  const file = useQuery({ queryKey: ['vault-file', path, agent], queryFn: () => api.vaultFile(path, agent) })
  if (file.isPending) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted">
        <Loader2 size={14} className="animate-spin" /> Loading {path}
      </div>
    )
  }
  if (file.isError) return <ErrorNote error={file.error} />
  const entries = Object.entries(file.data.frontmatter)
  return (
    <div className="space-y-4">
      <CliHint command={cliForPath(path)} />
      {entries.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full text-xs">
            <caption className="sr-only">Frontmatter</caption>
            <tbody>
              {entries.map(([key, value]) => (
                <tr key={key} className="border-b border-line last:border-0">
                  <th scope="row" className="w-40 whitespace-nowrap bg-raised/50 px-2.5 py-1.5 text-left font-mono font-normal text-muted">
                    {key}
                  </th>
                  <td className="break-all px-2.5 py-1.5 font-mono">{display(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {file.data.body.trim() ? <Markdown>{file.data.body}</Markdown> : <p className="text-sm text-muted">Empty body.</p>}
    </div>
  )
}
