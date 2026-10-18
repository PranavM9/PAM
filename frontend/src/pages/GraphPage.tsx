import { useQuery } from '@tanstack/react-query'
import { Loader2, Maximize2, PinOff, Search } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from 'react-force-graph-2d'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { AgentSelect } from '../components/AgentSelect'
import { ErrorNote } from '../components/ErrorNote'
import { PageHeader } from '../components/PageHeader'
import { NodeDrawer } from '../components/graph/NodeDrawer'
import { cliHints } from '../lib/cliHints'
import { clusterColor } from '../lib/palette'
import type { GraphLink, GraphNode } from '../types/generated'

type Node = NodeObject<GraphNode>
type Link = LinkObject<GraphNode, GraphLink>
type Methods = ForceGraphMethods<Node, Link>

/** Fact color from the `--warn` token, read once so canvas frames stay cheap. */
let factColor: string | null = null

function factFill(): string {
  factColor ??= themeColor('warn')
  return factColor
}

function radius(node: GraphNode): number {
  if (node.type === 'project') return 5 + Math.sqrt(Math.max(1, node.size)) * 2.2
  if (node.type === 'fact') return 2.5
  return 2 + Math.max(0, node.size) * 0.9
}

function color(node: GraphNode): string {
  return node.type === 'fact' ? factFill() : clusterColor(node.cluster_id)
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
  const palette = useMemo(
    () => ({
      fg: themeColor('fg'),
      muted: themeColor('muted', 0.25),
      bg: themeColor('bg', 0.72),
      edge: themeColor('edge', 0.14),
      derived: themeColor('warn', 0.35),
    }),
    [],
  )

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
        ctx.font = `${node.type === 'project' ? 600 : 400} ${size}px -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        const text = node.label.length > 48 ? `${node.label.slice(0, 46)}…` : node.label
        const w = ctx.measureText(text).width
        const padX = 5 / scale
        const padY = 2.5 / scale
        const top = y + r + 3 / scale
        ctx.beginPath()
        ctx.roundRect(x - w / 2 - padX, top, w + padX * 2, size + padY * 2, 6 / scale)
        ctx.fillStyle = palette.bg
        ctx.fill()
        ctx.lineWidth = 1 / scale
        ctx.strokeStyle = palette.edge
        ctx.stroke()
        ctx.fillStyle = palette.fg
        ctx.fillText(text, x, top + padY)
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
      if (link.kind === 'derived_from') return palette.derived
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
      />
      <section className="panel relative mb-1 min-h-[26rem] flex-1 overflow-hidden shadow-[inset_0_1px_0_var(--glass-highlight),0_8px_24px_rgba(3,1,14,0.16)] sm:mx-2" aria-label="Memory graph">
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

        <div className="pointer-events-none absolute inset-x-3 top-3 z-10 flex flex-col gap-2 sm:inset-x-4 sm:top-4 md:flex-row md:items-start md:justify-between">
          <div className="pointer-events-auto w-full md:w-80">
            <div className="flex min-h-[2.75rem] items-center gap-2.5 rounded-control border border-edge/[0.12] bg-bg/45 px-3.5 shadow-[inset_0_1px_0_var(--glass-highlight)] backdrop-blur-xl transition duration-200 ease-out focus-within:border-accent/60">
              <Search size={16} strokeWidth={1.75} className="shrink-0 text-muted" aria-hidden />
              <input
                className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-muted/80 focus-visible:outline-none"
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
              <ul id="graph-matches" className="mt-2 overflow-hidden rounded-control border border-edge/[0.12] bg-bg/80 p-1.5 shadow-xl backdrop-blur-xl">
                {matches.map((n) => (
                  <li key={String(n.id)}>
                    <button
                      type="button"
                      onClick={() => flyTo(n)}
                      className="flex min-h-[2.5rem] w-full items-center gap-3 rounded-[10px] px-2.5 text-left text-sm text-fg transition duration-150 ease-out hover:bg-fg/[0.07] focus:bg-fg/[0.07] focus:outline-none"
                    >
                      <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color(n) }} aria-hidden />
                      <span className="truncate">{n.label}</span>
                      <span className="ml-auto shrink-0 text-xs capitalize text-muted">{n.type}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div
            role="toolbar"
            aria-label="Graph controls"
            className="pointer-events-auto flex flex-wrap rounded-control border border-edge/[0.12] bg-bg/45 shadow-[inset_0_1px_0_var(--glass-highlight)] backdrop-blur-xl items-center gap-1.5 self-start p-1.5"
          >
            <AgentSelect value={agent} onChange={(name) => setParam('agent', name === 'default' ? null : name)} />
            <label className="flex min-h-[2.25rem] cursor-pointer select-none items-center gap-2 rounded-xl px-2.5 text-sm text-fg/90 transition duration-200 ease-out hover:bg-fg/[0.06]">
              <input
                type="checkbox"
                className="h-4 w-4 accent-accent"
                checked={facts}
                onChange={(e) => setParam('facts', e.target.checked ? 'true' : null)}
              />
              Show facts
            </label>
            <span className="mx-0.5 hidden h-5 w-px bg-edge/10 sm:block" aria-hidden />
            <button type="button" className="btn-ghost min-h-[2.25rem]" onClick={() => fg.current?.zoomToFit(600, 40)}>
              <Maximize2 size={15} strokeWidth={1.75} /> Fit
            </button>
            <button type="button" className="btn-ghost min-h-[2.25rem]" onClick={unpinAll} disabled={pinned === 0}>
              <PinOff size={15} strokeWidth={1.75} /> Unpin {pinned > 0 ? pinned : ''}
            </button>
          </div>
        </div>

        <div className="pointer-events-none absolute bottom-3 border border-edge/[0.12] bg-bg/45 backdrop-blur-xl left-3 z-10 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-x-4 gap-y-1 rounded-control px-3.5 py-2 text-xs tabular-nums text-muted sm:bottom-4 sm:left-4">
          <span>
            <span className="font-medium text-fg">{counts.project}</span> projects
          </span>
          <span>
            <span className="font-medium text-fg">{counts.episode}</span> episodes
          </span>
          {facts && (
            <span>
              <span className="font-medium text-fg">{counts.fact}</span> facts
            </span>
          )}
          <span>
            <span className="font-medium text-fg">{graph.data?.links.length ?? 0}</span> links
          </span>
        </div>

        {graph.isPending && (
          <div className="absolute inset-0 grid place-items-center">
            <span className="glass-strong flex items-center gap-2.5 rounded-control px-4 py-2.5 text-sm text-muted">
              <Loader2 size={16} strokeWidth={1.75} className="animate-spin text-accent" /> Loading graph…
            </span>
          </div>
        )}
        {graph.isError && (
          <div className="absolute inset-x-4 bottom-16 z-10">
            <ErrorNote error={graph.error} />
          </div>
        )}
        {graph.data && graph.data.nodes.length === 0 && (
          <div className="absolute inset-0 grid place-items-center px-6 text-center">
            <div>
              <p className="text-[15px] font-medium text-fg">Nothing here yet</p>
              <p className="mt-1 text-sm text-muted">Import an export first.</p>
            </div>
          </div>
        )}

        {selected && (
          <NodeDrawer
            node={selected}
            swatch={color(selected)}
            agent={agent}
            onOpen={() => navigate(`/vault?path=${encodeURIComponent(selected.path!)}`)}
            onClose={() => setSelected(null)}
          />
        )}
      </section>
    </div>
  )
}
