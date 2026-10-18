import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Loader2 } from 'lucide-react'
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

function FrontmatterValue({ value }: { value: unknown }) {
  if (Array.isArray(value) && value.length > 0 && value.every((v) => typeof v !== 'object' || v === null)) {
    return (
      <span className="flex flex-wrap gap-1.5">
        {value.map((v, i) => (
          <span key={i} className="badge max-w-full break-all text-fg/85">
            {display(v)}
          </span>
        ))}
      </span>
    )
  }
  const muted = value === null || value === undefined || (Array.isArray(value) && value.length === 0)
  return <span className={`break-all font-mono text-[12.5px] ${muted ? 'text-muted' : 'text-fg/90'}`}>{display(value)}</span>
}

/**
 * Render one vault file from `GET /vault/file`: frontmatter list plus body.
 *
 * Behavior:
 *     Frontmatter sits in a quiet, collapsible inset list; key and value share a row and
 *     wrap onto two lines when narrow. Arrays of plain values show as chips,
 *     nested values as JSON. The body is rendered as Markdown in `prose`.
 *     Shows the matching `pam … show` command.
 * Parameters:
 *     path: Vault-relative path of the file.
 *     agent: Agent whose scope applies, if any.
 *     showTitle: Show a heading: the frontmatter `title` or `name`, else the
 *         file name.
 *     showCli: Show the CLI hint; off when the page header already shows it.
 */
export function VaultFileView({
  path,
  agent,
  showTitle = false,
  showCli = true,
}: {
  path: string
  agent?: string
  showTitle?: boolean
  showCli?: boolean
}) {
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
  const fm = file.data.frontmatter
  const named = [fm.title, fm.name].find((v): v is string => typeof v === 'string' && v.trim() !== '')
  const title = showTitle ? (named ?? path.split('/').at(-1)) : undefined
  return (
    <div className="space-y-6">
      {title && (
        <h2 className={`break-words text-fg ${named ? 'text-[24px] font-semibold leading-snug tracking-[-0.02em]' : 'break-all font-mono text-lg font-medium'}`}>
          {title}
        </h2>
      )}
      {showCli && <CliHint command={cliForPath(path)} />}
      {entries.length > 0 && (
        <details open aria-label="Frontmatter" className="group">
          <summary className="label mb-2 flex w-fit cursor-pointer list-none items-center gap-1.5 rounded-lg px-1 transition duration-200 ease-out hover:text-fg [&::-webkit-details-marker]:hidden">
            <ChevronRight size={14} strokeWidth={1.75} className="transition-transform duration-200 ease-out group-open:rotate-90" aria-hidden />
            Frontmatter
            <span className="font-normal text-muted/80">· {entries.length} fields</span>
          </summary>
          <dl className="well overflow-hidden px-4 py-1">
            {entries.map(([key, value]) => (
              <div key={key} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-edge/[0.06] py-1.5 last:border-0">
                <dt className="w-36 shrink-0 break-all font-mono text-[12.5px] leading-6 text-muted">{key}</dt>
                <dd className="m-0 min-w-0 flex-1 basis-48 text-[12.5px] leading-6">
                  <FrontmatterValue value={value} />
                </dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      <section aria-label="Body">
        {entries.length > 0 && <div className="mb-5 border-t divider" />}
        {file.data.body.trim() ? <Markdown className={`scroll-reveal ${showTitle ? 'text-[15px] leading-relaxed' : ''}`}>{file.data.body}</Markdown> : <p className="text-sm text-muted">Empty body.</p>}
      </section>
    </div>
  )
}
