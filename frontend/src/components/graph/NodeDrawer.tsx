import { ExternalLink, X } from 'lucide-react'
import { VaultFileView } from '../VaultFileView'
import type { GraphNode } from '../../types/generated'

const TYPE_LABEL: Record<GraphNode['type'], string> = { project: 'Project', episode: 'Episode', fact: 'Fact' }

/**
 * Glass drawer floating over the right edge of the graph panel with one node's file.
 *
 * Behavior:
 *     Takes the full panel width below `sm` and a fixed 30rem column above it.
 *     The header shows the node type and label, an "Open in vault" action when
 *     the node has a file, and a close button; the body renders the file.
 * Parameters:
 *     node: Selected node.
 *     swatch: Color of the node on the canvas.
 *     agent: Agent whose scope applies to the file.
 *     onOpen: Called to open the node's file on the vault page.
 *     onClose: Called to dismiss the drawer.
 */
export function NodeDrawer({
  node,
  swatch,
  agent,
  onOpen,
  onClose,
}: {
  node: GraphNode
  swatch: string
  agent: string
  onOpen: () => void
  onClose: () => void
}) {
  return (
    <aside
      className="absolute inset-2 z-20 flex flex-col overflow-hidden rounded-card border border-edge/[0.12] bg-bg/80 shadow-[inset_0_1px_0_var(--glass-highlight),0_24px_60px_rgba(3,1,14,0.35)] backdrop-blur-2xl sm:inset-y-3 sm:left-auto sm:right-3 sm:w-[min(30rem,calc(100%-1.5rem))]"
      aria-label="Node details"
    >
      <div className="flex items-start gap-3 border-b border-edge/10 px-5 pb-4 pt-5">
        <span className="mt-2 h-3 w-3 shrink-0 rounded-full ring-4 ring-edge/[0.06]" style={{ background: swatch }} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="eyebrow">{TYPE_LABEL[node.type]}</div>
          <h2 className="mt-0.5 break-words text-[17px] font-semibold leading-snug tracking-[-0.01em] text-fg">{node.label}</h2>
        </div>
        <button type="button" className="icon-btn -mr-1.5 -mt-1" onClick={onClose} aria-label="Close details">
          <X size={18} strokeWidth={1.75} />
        </button>
      </div>
      {node.path && (
        <div className="px-5 pt-4">
          <button type="button" className="btn w-full sm:w-auto" onClick={onOpen}>
            <ExternalLink size={15} strokeWidth={1.75} /> Open in vault
          </button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto px-5 pb-6 pt-4">
        {node.path ? (
          <VaultFileView path={node.path} agent={agent} />
        ) : (
          <p className="text-sm text-muted">This node has no vault file.</p>
        )}
      </div>
    </aside>
  )
}
