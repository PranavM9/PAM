import { ChevronRight, FileText, Folder, FolderOpen } from 'lucide-react'
import type { TreeNode } from '../lib/vaultTree'

/**
 * Recursive vault file tree with expandable folders and selectable files.
 *
 * Behavior:
 *     Folders toggle open on click and show their child count; files carry
 *     `data-vault-file` and select on click. Nesting is shown by indentation
 *     with a faint guide line instead of borders.
 * Parameters:
 *     nodes: Nodes at this level.
 *     depth: Nesting level, 0 for the root.
 *     selected: Path of the selected file, if any.
 *     isOpen: Whether a folder path is expanded.
 *     onToggle: Called with a folder path to open or close it.
 *     onSelect: Called with a file path to view it.
 */
export function VaultTree({
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
    <ul role={depth === 0 ? 'tree' : 'group'} className={depth > 0 ? 'stagger ml-[1.05rem] border-l border-edge/[0.08] pl-1.5' : 'space-y-px'}>
      {nodes.map((node) => {
        if (node.file) {
          const active = node.path === selected
          return (
            <li key={node.path} role="treeitem" aria-selected={active}>
              <button
                type="button"
                data-vault-file
                onClick={() => onSelect(node.path)}
                title={node.path}
                className={`flex min-h-[2rem] w-full items-center gap-2 rounded-[10px] px-2 text-left transition duration-200 ease-out ${
                  active
                    ? 'bg-gradient-to-r from-accent/25 to-accent/10 text-fg shadow-[inset_0_1px_0_rgb(var(--edge)/0.1)]'
                    : 'text-muted hover:bg-fg/[0.06] hover:text-fg'
                }`}
              >
                <FileText size={15} strokeWidth={1.75} className={`shrink-0 ${active ? 'text-accent' : 'opacity-70'}`} aria-hidden />
                <span className="truncate font-mono text-[12px]">{node.name}</span>
              </button>
            </li>
          )
        }
        const expanded = isOpen(node.path)
        const Icon = expanded ? FolderOpen : Folder
        return (
          <li key={node.path} role="treeitem" aria-expanded={expanded}>
            <button
              type="button"
              onClick={() => onToggle(node.path)}
              className="group flex min-h-[2.125rem] w-full items-center gap-2 rounded-[10px] px-2 text-left text-[14px] text-fg/90 transition duration-200 ease-out hover:bg-fg/[0.06] hover:text-fg"
            >
              <ChevronRight
                size={14}
                strokeWidth={1.75}
                className={`shrink-0 text-muted transition-transform duration-200 ease-out ${expanded ? 'rotate-90' : ''}`}
                aria-hidden
              />
              <Icon size={16} strokeWidth={1.75} className="shrink-0 text-accent/90" aria-hidden />
              <span className="truncate">{node.name}</span>
              <span className="ml-auto pl-2 text-[12px] tabular-nums text-muted/80">{node.children.length}</span>
            </button>
            {expanded && (
              <VaultTree nodes={node.children} depth={depth + 1} selected={selected} isOpen={isOpen} onToggle={onToggle} onSelect={onSelect} />
            )}
          </li>
        )
      })}
    </ul>
  )
}
