import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, FileText, Folder, Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { AgentSelect } from '../components/AgentSelect'
import { ErrorNote } from '../components/ErrorNote'
import { PageHeader } from '../components/PageHeader'
import { VaultFileView } from '../components/VaultFileView'
import { cliForPath } from '../lib/cliHints'

interface TreeNode {
  name: string
  path: string
  children: TreeNode[]
  file: boolean
}

function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode = { name: '', path: '', children: [], file: false }
  for (const path of paths) {
    let node = root
    path.split('/').forEach((part, i, parts) => {
      const childPath = parts.slice(0, i + 1).join('/')
      let child = node.children.find((c) => c.name === part)
      if (!child) {
        child = { name: part, path: childPath, children: [], file: i === parts.length - 1 }
        node.children.push(child)
      }
      node = child
    })
  }
  const sort = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => Number(a.file) - Number(b.file) || a.name.localeCompare(b.name))
    nodes.forEach((n) => sort(n.children))
  }
  sort(root.children)
  return root.children
}

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
 */
export default function VaultPage() {
  const [params, setParams] = useSearchParams()
  const selected = params.get('path')
  const agent = params.get('agent') || 'default'
  const [filter, setFilter] = useState('')
  const [open, setOpen] = useState<Set<string>>(() => new Set(['memory', 'memory/default', ...(selected ? ancestors(selected) : [])]))
  const tree = useQuery({ queryKey: ['vault-tree', agent], queryFn: () => api.vaultTree(agent) })

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

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="Vault"
        subtitle="Every file PAM keeps: plain Markdown and YAML in a git repo."
        cli={cliForPath(selected)}
        actions={
          <AgentSelect
            value={agent}
            onChange={(name) => {
              const next = new URLSearchParams(params)
              if (name === 'default') next.delete('agent')
              else next.set('agent', name)
              setParams(next)
            }}
          />
        }
      />
      <div className="flex min-h-0 flex-1">
        <nav aria-label="Vault files" className="flex w-80 shrink-0 flex-col border-r border-line">
          <div className="p-3">
            <input
              className="input w-full"
              placeholder="Filter paths…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              aria-label="Filter paths"
            />
          </div>
          <div className="min-h-0 flex-1 overflow-auto px-2 pb-3 text-sm">
            {tree.isPending && (
              <div className="flex items-center gap-2 px-2 text-muted">
                <Loader2 size={14} className="animate-spin" /> Loading tree…
              </div>
            )}
            <ErrorNote error={tree.error} />
            {tree.data && (
              <p className="px-2 pb-2 text-xs text-muted">
                {tree.data.paths.length} files visible to <span className="font-mono">{agent}</span>
              </p>
            )}
            <Tree nodes={nodes} depth={0} selected={selected} isOpen={isOpen} onToggle={toggle} onSelect={select} />
          </div>
        </nav>
        <article className="min-w-0 flex-1 overflow-auto px-8 py-6" aria-label="File viewer">
          {selected ? (
            <>
              <h2 className="mb-4 break-all font-mono text-sm text-muted">{selected}</h2>
              <VaultFileView path={selected} agent={agent} />
            </>
          ) : (
            <p className="pt-10 text-center text-sm text-muted">Pick a file to view its frontmatter and body.</p>
          )}
        </article>
      </div>
    </div>
  )
}

function Tree({
  nodes,
  depth,
  selected,
  isOpen,
  onToggle,
  onSelect,
}: {
  nodes: TreeNode[]
  depth: number
  selected: string | null
  isOpen: (path: string) => boolean
  onToggle: (path: string) => void
  onSelect: (path: string) => void
}) {
  return (
    <ul role={depth === 0 ? 'tree' : 'group'}>
      {nodes.map((node) => {
        const pad = { paddingLeft: `${depth * 0.875 + 0.5}rem` }
        if (node.file) {
          return (
            <li key={node.path} role="treeitem" aria-selected={node.path === selected}>
              <button
                type="button"
                data-vault-file
                onClick={() => onSelect(node.path)}
                style={pad}
                title={node.path}
                className={`flex w-full items-center gap-1.5 rounded py-1 pr-2 text-left ${
                  node.path === selected ? 'bg-accent/15 text-fg' : 'text-muted hover:bg-raised hover:text-fg'
                }`}
              >
                <FileText size={14} className="shrink-0" aria-hidden />
                <span className="truncate font-mono text-xs">{node.name}</span>
              </button>
            </li>
          )
        }
        const expanded = isOpen(node.path)
        return (
          <li key={node.path} role="treeitem" aria-expanded={expanded}>
            <button
              type="button"
              onClick={() => onToggle(node.path)}
              style={pad}
              className="flex w-full items-center gap-1.5 rounded py-1 pr-2 text-left hover:bg-raised"
            >
              {expanded ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
              <Folder size={14} className="shrink-0 text-accent" aria-hidden />
              <span className="truncate">{node.name}</span>
              <span className="ml-auto text-[11px] text-muted">{node.children.length}</span>
            </button>
            {expanded && (
              <Tree nodes={node.children} depth={depth + 1} selected={selected} isOpen={isOpen} onToggle={onToggle} onSelect={onSelect} />
            )}
          </li>
        )
      })}
    </ul>
  )
}
