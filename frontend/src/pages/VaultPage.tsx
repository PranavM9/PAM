import { useQuery } from '@tanstack/react-query'
import { BookOpen, ChevronDown, ChevronRight, FileSearch, FolderTree, Info, Loader2, Search, X } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { AgentSelect } from '../components/AgentSelect'
import { ErrorNote } from '../components/ErrorNote'
import { PageHeader } from '../components/PageHeader'
import { ResizeHandle } from '../components/Resizable'
import { usePaneSize } from '../lib/usePaneSize'
import { VaultFileView } from '../components/VaultFileView'
import { VaultTree } from '../components/VaultTree'
import { cliForPath } from '../lib/cliHints'
import { buildTree } from '../lib/vaultTree'

function ancestors(path: string): string[] {
  const parts = path.split('/')
  return parts.slice(1).map((_, i) => parts.slice(0, i + 1).join('/'))
}

/**
 * Vault browser: file tree from `GET /vault/tree` and a file viewer.
 *
 * Behavior:
 *     The tree is scope-filtered by the selected agent. The selected file is
 *     kept in the URL (`?path=`), so graph and search results can link here;
 *     its folders open automatically. A filter box narrows the tree by path.
 *     On wide screens the tree is a glass sidebar beside the viewer panel;
 *     below `lg` it stacks above the viewer and can be collapsed.
 */
export default function VaultPage() {
  const treePane = usePaneSize({ id: 'vault-tree', initial: 320, min: 240, max: 520 })
  const [params, setParams] = useSearchParams()
  const selected = params.get('path')
  const agent = params.get('agent') || 'default'
  const [filter, setFilter] = useState('')
  const [treeOpen, setTreeOpen] = useState(true)
  const [showStructure, setShowStructure] = useState(false)
  const [open, setOpen] = useState<Set<string>>(() => new Set(['memory', 'memory/default', ...(selected ? ancestors(selected) : [])]))
  const tree = useQuery({ queryKey: ['vault-tree', agent], queryFn: () => api.vaultTree(agent) })
  const navigate = useNavigate()

  const nodes = useMemo(() => {
    const paths = tree.data?.paths ?? []
    const q = filter.trim().toLowerCase()
    return buildTree(q ? paths.filter((p) => p.toLowerCase().includes(q)) : paths)
  }, [tree.data, filter])

  const select = (path: string) => {
    const next = new URLSearchParams(params)
    next.set('path', path)
    setParams(next)
  }
  const toggle = (path: string) =>
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  const isOpen = (path: string) => Boolean(filter.trim()) || open.has(path) || Boolean(selected?.startsWith(`${path}/`))

  const parts = selected ? selected.split('/') : []

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:overflow-hidden">
      <PageHeader
        title="Vault"
        cli={cliForPath(selected)}
        actions={
          <>
            <button type="button" className="btn" onClick={() => setShowStructure(true)} aria-label="About the vault structure">
              <Info size={16} aria-hidden /> Vault guide
            </button>
            <AgentSelect
              value={agent}
              onChange={(name) => {
                const next = new URLSearchParams(params)
                if (name === 'default') next.delete('agent')
                else next.set('agent', name)
                setParams(next)
              }}
            />
          </>
        }
      />
      <div className="flex flex-col gap-4 pb-1 lg:min-h-0 lg:flex-1 lg:flex-row lg:gap-0">
        <nav aria-label="Vault files" style={treePane.style} className="panel flex shrink-0 flex-col overflow-hidden lg:w-[var(--pane-w)]">
          <div className="flex items-center gap-3 px-5 pb-3 pt-5">
            <div className="min-w-0 flex-1">
              <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-fg">Files</h2>
              <p className="mt-0.5 truncate text-[13px] text-muted">
                {tree.data ? (
                  <>
                    {tree.data.paths.length} visible to <span className="font-mono text-[12px] text-fg/80">{agent}</span>
                  </>
                ) : (
                  'Scoped to the selected agent'
                )}
              </p>
            </div>
            <button
              type="button"
              className="icon-btn lg:hidden"
              onClick={() => setTreeOpen((v) => !v)}
              aria-expanded={treeOpen}
              aria-controls="vault-tree-body"
              aria-label={treeOpen ? 'Collapse file tree' : 'Expand file tree'}
            >
              <ChevronDown size={18} strokeWidth={1.75} className={`transition-transform duration-200 ease-out ${treeOpen ? '' : '-rotate-90'}`} />
            </button>
          </div>
          <div id="vault-tree-body" className={`${treeOpen ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col lg:flex`}>
            <div className="relative mx-4 mb-3">
              <Search size={15} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
              <input
                className="input w-full pl-9"
                placeholder="Filter paths…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                aria-label="Filter paths"
              />
            </div>
            <div className="mx-4 border-t divider" />
            <div className="max-h-[50vh] min-h-0 flex-1 overflow-auto px-3 pb-4 pt-3 text-sm lg:max-h-none">
              {tree.isPending && (
                <div className="flex items-center gap-2 px-2 py-1 text-muted">
                  <Loader2 size={14} className="animate-spin" /> Loading tree…
                </div>
              )}
              <div className="px-1">
                <ErrorNote error={tree.error} />
              </div>
              {tree.data && nodes.length === 0 && (
                <p className="px-2 py-1 text-[13px] text-muted">No paths match “{filter.trim()}”.</p>
              )}
              <VaultTree nodes={nodes} depth={0} selected={selected} isOpen={isOpen} onToggle={toggle} onSelect={select} />
            </div>
          </div>
        </nav>
        <ResizeHandle pane={treePane} side="before" label="Resize file tree" />
        <article
          className="panel flex min-w-0 flex-col lg:min-h-0 lg:flex-1 lg:overflow-auto"
          aria-label="File viewer"
        >
          {selected ? (
            <div className="px-5 py-6 sm:px-8 sm:py-7">
              <p className="mb-3 flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[13px] text-muted" title={selected}>
                {parts.map((part, i) => (
                  <Fragment key={i}>
                    {i > 0 && <ChevronRight size={12} strokeWidth={1.75} className="shrink-0 opacity-60" aria-hidden />}
                    <span className={i === parts.length - 1 ? 'break-all font-mono text-[12px] text-fg/80' : ''}>{part}</span>
                  </Fragment>
                ))}
              </p>
              <VaultFileView path={selected} agent={agent} showTitle showCli={false} />
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-16 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-[18px] bg-gradient-to-b from-accent/25 to-accent/5 text-accent shadow-[inset_0_1px_0_rgb(var(--edge)/0.15)]">
                <FileSearch size={24} strokeWidth={1.75} aria-hidden />
              </div>
              <div>
                <p className="text-[17px] font-medium text-fg">Pick a file</p>
                <p className="mt-1 max-w-xs text-sm leading-relaxed text-muted">Choose a file to view it.</p>
              </div>
            </div>
          )}
        </article>
      </div>
      {showStructure && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-bg/70 p-4 backdrop-blur-sm" onClick={() => setShowStructure(false)} onKeyDown={(event) => event.key === 'Escape' && setShowStructure(false)}>
          <section role="dialog" aria-modal="true" aria-labelledby="vault-guide-title" onClick={(event) => event.stopPropagation()} className="glass-blur panel w-full max-w-2xl p-5 shadow-2xl sm:p-7">
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <p className="eyebrow">A map of your memory</p>
                <h2 id="vault-guide-title" className="display-type mt-1 text-3xl">Inside the vault</h2>
              </div>
              <button autoFocus type="button" className="icon-btn" onClick={() => setShowStructure(false)} aria-label="Close vault guide"><X size={18} /></button>
            </div>
            <ul className="grid gap-2 sm:grid-cols-2">
              {[
                ['agent/', 'Agent settings and persona notes.'],
                ['imports/', 'Original exports kept as received.'],
                ['memory/shared/facts/', 'Facts available across agents.'],
                ['memory/<agent>/episodes/', 'Imported conversations, one file each.'],
                ['memory/<agent>/projects/', 'Groups of related conversations.'],
                ['memory/<agent>/facts/', 'Facts scoped to one agent.'],
                ['skills/<agent>/', 'Reusable instructions for an agent.'],
                ['working/', 'Short term context for active chats.'],
                ['.pam/', 'Search index and other rebuildable data.'],
              ].map(([folder, summary]) => {
                const sample = tree.data?.paths.find((path) => path.startsWith(folder.replace('<agent>', 'default')))
                return (
                  <li key={folder}>
                    <button type="button" disabled={!sample} onClick={() => { if (sample) { select(sample); setShowStructure(false) } }} className="well h-full w-full rounded-xl p-3 text-left transition hover:bg-fg/[0.06] disabled:cursor-default disabled:opacity-60">
                      <span className="flex items-center gap-2 font-mono text-xs text-accent"><FolderTree size={14} />{folder}</span>
                      <span className="mt-1 block text-sm text-fg/85">{summary}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
            <button type="button" className="btn-ghost mt-5" onClick={() => { setShowStructure(false); navigate('/guides?g=vault-structure') }}>
              <BookOpen size={15} /> Read the full guide
            </button>
          </section>
        </div>
      )}
    </div>
  )
}
