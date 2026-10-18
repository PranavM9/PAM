import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Loader2, Maximize2, PinOff, Search, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from 'react-force-graph-2d'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { AgentSelect } from '../components/AgentSelect'
import { ErrorNote } from '../components/ErrorNote'
import { PageHeader } from '../components/PageHeader'
import { VaultFileView } from '../components/VaultFileView'
import { cliHints } from '../lib/cliHints'
import { clusterColor } from '../lib/palette'
import type { GraphLink, GraphNode } from '../types/generated'

type Node = NodeObject<GraphNode>
type Link = LinkObject<GraphNode, GraphLink>
type Methods = ForceGraphMethods<Node, Link>

const FACT_COLOR = '#fbbf24'

function radius(node: GraphNode): number {
  if (node.type === 'project') return 5 + Math.sqrt(Math.max(1, node.size)) * 2.2
  if (node.type === 'fact') return 2.5
  return 2 + Math.max(0, node.size) * 0.9
}

function color(node: GraphNode): string {
  return node.type === 'fact' ? FACT_COLOR : clusterColor(node.cluster_id)
}

/** Link ends are ids in the API but become node objects once d3-force runs. */
function endpointId(end: unknown): string {
  return typeof end === 'object' && end !== null ? String((end as Node).id) : String(end)
}

/** Last known positions and pins, kept across refetches and page visits. */
const positions = new Map<string, { x?: number; y?: number; fx?: number; fy?: number }>()

function rememberPositions(nodes: Node[]) {
  for (const node of nodes) positions.set(String(node.id), { x: node.x, y: node.y, fx: node.fx, fy: node.fy })
}

function clearPins(nodes: Node[]) {
  for (const node of nodes) {
    node.fx = undefined
    node.fy = undefined
  }
  rememberPositions(nodes)
}

function themeColor(name: string, alpha = 1): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim()
  return value ? `rgb(${value} / ${alpha})` : `rgba(140,147,163,${alpha})`
}

function useSize() {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    if (!ref.current) return
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height })
    })
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])
  return { ref, ...size }
}

/**
 * Obsidian-style force graph of projects, episodes and (optionally) facts.
 *
 * Behavior:
 *     Loads `GET /graph?agent=&facts=`. Projects are colored by a palette hashed
 *     from `cluster_id`; episodes are smaller. Hovering highlights neighbours and
 *     fades the rest; dragging pins a node (`fx`, `fy`). Clicking a node, or
 *     picking it in the search box, flies to it and opens its file in a drawer.
 *     Node positions survive refetches, so new nodes "bloom" around old ones.
 *     Physics: charge -60, link distance 30 (member) / 60 (other), 150 cooldown ticks.
 */
export default function GraphPage() {
  const [params, setParams] = useSearchParams()
  const agent = params.get('agent') || 'default'
  const facts = params.get('facts') === 'true'
  const graph = useQuery({ queryKey: ['graph', agent, facts], queryFn: () => api.graph(agent, facts) })
  const fg = useRef<Methods | undefined>(undefined)
  const { ref: box, width, height } = useSize()
  const [hover, setHover] = useState<string | null>(null)
  const [selected, setSelected] = useState<Node | null>(null)
  const [query, setQuery] = useState('')
  const [fitted, setFitted] = useState<unknown>(null)
  const [pinned, setPinned] = useState(() => [...positions.values()].filter((p) => p.fx !== undefined).length)
  const navigate = useNavigate()

  const data = useMemo(() => {
    if (!graph.data) return { nodes: [] as Node[], links: [] as Link[] }
    return {
      nodes: graph.data.nodes.map((n): Node => ({ ...n, ...positions.get(n.id) })),
      links: graph.data.links.map((l): Link => ({ ...l })),
    }
  }, [graph.data])

  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>()
    for (const link of graph.data?.links ?? []) {
      if (!map.has(link.source)) map.set(link.source, new Set())
      if (!map.has(link.target)) map.set(link.target, new Set())
      map.get(link.source)!.add(link.target)
      map.get(link.target)!.add(link.source)
    }
    return map
  }, [graph.data])

  const focus = hover ?? (selected ? String(selected.id) : null)
  const lit = useMemo(() => (focus ? new Set([focus, ...(neighbours.get(focus) ?? [])]) : null), [focus, neighbours])
  const palette = useMemo(() => ({ fg: themeColor('fg'), muted: themeColor('muted', 0.25), bg: themeColor('bg', 0.85) }), [])

  useEffect(() => {
    const methods = fg.current
    if (!methods) return
    methods.d3Force('charge')?.strength(-60)
    methods.d3Force('link')?.distance((link: Link) => (link.kind === 'member' ? 30 : 60))
    methods.d3ReheatSimulation()
  }, [data])


  const flyTo = useCallback((node: Node) => {
    setSelected(node)
    setQuery('')
    if (node.x !== undefined && node.y !== undefined) {
      fg.current?.centerAt(node.x, node.y, 800)
      fg.current?.zoom(4, 800)
    }
  }, [setSelected, setQuery])

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return data.nodes.filter((n) => n.label.toLowerCase().includes(q)).slice(0, 8)
  }, [query, data.nodes])

  const unpinAll = () => {
    clearPins(data.nodes)
    setPinned(0)
    fg.current?.d3ReheatSimulation()
  }

  const drawNode = useCallback(
    (node: Node, ctx: CanvasRenderingContext2D, scale: number) => {
      const r = radius(node)
      const x = node.x ?? 0
      const y = node.y ?? 0
      const faded = lit !== null && !lit.has(String(node.id))
      ctx.globalAlpha = faded ? 0.12 : 1
      ctx.fillStyle = color(node)
      ctx.beginPath()
      if (node.type === 'fact') ctx.rect(x - r, y - r, r * 2, r * 2)
      else ctx.arc(x, y, r, 0, 2 * Math.PI)
      ctx.fill()
      if (node.fx !== undefined || String(node.id) === focus) {
        ctx.lineWidth = 1.5 / scale
        ctx.strokeStyle = palette.fg
        ctx.stroke()
      }
      const showLabel = !faded && (node.type === 'project' ? scale > 0.6 : String(node.id) === focus || (lit !== null && scale > 1.5) || scale > 3.5)
      if (showLabel) {
        const size = (node.type === 'project' ? 13 : 11) / scale
        ctx.font = `${node.type === 'project' ? 600 : 400} ${size}px system-ui, sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        const text = node.label.length > 48 ? `${node.label.slice(0, 46)}…` : node.label
        const w = ctx.measureText(text).width
        ctx.fillStyle = palette.bg
        ctx.fillRect(x - w / 2 - 2 / scale, y + r + 2 / scale, w + 4 / scale, size + 2 / scale)
        ctx.fillStyle = palette.fg
        ctx.fillText(text, x, y + r + 3 / scale)
      }
      ctx.globalAlpha = 1
    },
    [lit, focus, palette],
  )

  const paintPointer = useCallback((node: Node, paint: string, ctx: CanvasRenderingContext2D) => {
    ctx.fillStyle = paint
    ctx.beginPath()
    ctx.arc(node.x ?? 0, node.y ?? 0, radius(node) + 2, 0, 2 * Math.PI)
    ctx.fill()
  }, [])

  const linkColor = useCallback(
    (link: Link) => {
      const touches = focus !== null && (endpointId(link.source) === focus || endpointId(link.target) === focus)
      if (touches) return themeColor('accent', 0.9)
      if (lit) return themeColor('muted', 0.05)
      if (link.kind === 'derived_from') return 'rgba(251,191,36,0.35)'
      return link.kind === 'member' ? palette.muted : themeColor('muted', 0.45)
    },
    [focus, lit, palette],
  )

  const counts = useMemo(() => {
    const c = { project: 0, episode: 0, fact: 0 }
    for (const n of graph.data?.nodes ?? []) c[n.type]++
    return c
  }, [graph.data])

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value === null) next.delete(key)
    else next.set(key, value)
    setParams(next)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="Graph"
        subtitle="Projects (large), episodes (small) and similarity links. Drag to pin, scroll to zoom, click to open."
        cli={cliHints.graphExport(agent, facts)}
        actions={
          <>
            <AgentSelect value={agent} onChange={(name) => setParam('agent', name === 'default' ? null : name)} />
            <label className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={facts} onChange={(e) => setParam('facts', e.target.checked ? 'true' : null)} />
              Show facts
            </label>
            <button type="button" className="btn" onClick={() => fg.current?.zoomToFit(600, 40)}>
              <Maximize2 size={14} /> Fit
            </button>
            <button type="button" className="btn" onClick={unpinAll} disabled={pinned === 0}>
              <PinOff size={14} /> Unpin {pinned > 0 ? pinned : ''}
            </button>
          </>
        }
      />
      <div className="relative min-h-0 flex-1">
        <div ref={box} className="absolute inset-0">
          {width > 0 && (
            <ForceGraph2D<GraphNode, GraphLink>
              ref={fg}
              width={width}
              height={height}
              graphData={data}
              nodeId="id"
              nodeLabel={(n) => `${n.type}: ${n.label}`}
              nodeVal={(n) => radius(n)}
              nodeCanvasObject={drawNode}
              nodePointerAreaPaint={paintPointer}
              linkColor={linkColor}
              linkWidth={(l) => (focus && (endpointId(l.source) === focus || endpointId(l.target) === focus) ? 1.5 : 0.6)}
              linkLineDash={(l) => (l.kind === 'similar' ? [2, 2] : null)}
              cooldownTicks={150}
              onEngineStop={() => {
                rememberPositions(data.nodes)
                if (fitted !== data) {
                  fg.current?.zoomToFit(600, 60)
                  setFitted(data)
                }
              }}
              onNodeHover={(n) => setHover(n ? String(n.id) : null)}
              onNodeClick={flyTo}
              onNodeDragEnd={(n) => {
                n.fx = n.x
                n.fy = n.y
                rememberPositions([n])
                setPinned(data.nodes.filter((d) => d.fx !== undefined).length)
              }}
              onBackgroundClick={() => setSelected(null)}
            />
          )}
        </div>

        <div className="absolute left-4 top-4 w-72 space-y-2">
          <div className="card flex items-center gap-2 px-2.5 py-1.5 shadow-lg">
            <Search size={14} className="text-muted" aria-hidden />
            <input
              className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
              placeholder="Find a node…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && matches[0]) flyTo(matches[0])
                if (e.key === 'Escape') setQuery('')
              }}
              aria-label="Find a node"
              aria-controls="graph-matches"
            />
          </div>
          {matches.length > 0 && (
            <ul id="graph-matches" className="card overflow-hidden shadow-lg">
              {matches.map((n) => (
                <li key={String(n.id)}>
                  <button
                    type="button"
                    onClick={() => flyTo(n)}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-raised focus:bg-raised"
                  >
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color(n) }} aria-hidden />
                    <span className="truncate">{n.label}</span>
                    <span className="ml-auto text-xs text-muted">{n.type}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="text-xs text-muted">
            {counts.project} projects · {counts.episode} episodes{facts ? ` · ${counts.fact} facts` : ''} · {graph.data?.links.length ?? 0} links
          </div>
        </div>

        {graph.isPending && (
          <div className="absolute inset-0 grid place-items-center text-sm text-muted">
            <span className="flex items-center gap-2">
              <Loader2 size={16} className="animate-spin" /> Loading graph…
            </span>
          </div>
        )}
        {graph.isError && (
          <div className="absolute inset-x-4 bottom-4">
            <ErrorNote error={graph.error} />
          </div>
        )}
        {graph.data && graph.data.nodes.length === 0 && (
          <div className="absolute inset-0 grid place-items-center text-sm text-muted">Nothing here yet. Import an export first.</div>
        )}

        {selected && (
          <aside
            className="absolute bottom-0 right-0 top-0 flex w-[min(30rem,100%)] flex-col border-l border-line bg-panel shadow-2xl"
            aria-label="Node details"
          >
            <div className="flex items-start gap-2 border-b border-line px-4 py-3">
              <span className="mt-1.5 h-3 w-3 shrink-0 rounded-full" style={{ background: color(selected) }} aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="text-xs uppercase tracking-wide text-muted">{selected.type}</div>
                <h2 className="font-semibold">{selected.label}</h2>
              </div>
              {selected.path && (
                <button
                  type="button"
                  className="btn"
                  onClick={() => navigate(`/vault?path=${encodeURIComponent(selected.path!)}`)}
                >
                  <ExternalLink size={14} /> Vault
                </button>
              )}
              <button type="button" className="rounded p-1 text-muted hover:text-fg" onClick={() => setSelected(null)} aria-label="Close details">
                <X size={18} />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-4">
              {selected.path ? (
                <VaultFileView path={selected.path} agent={agent} />
              ) : (
                <p className="text-sm text-muted">This node has no vault file.</p>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}
