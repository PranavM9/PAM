import { useId, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { CardChart } from '../../types/generated'

const W = 320
const H = 180
const PAD = { left: 40, right: 12, top: 14, bottom: 34 }
const SERIES_COLORS = ['var(--accent)', 'var(--ok)', 'var(--warn)', 'var(--bad)']
const TICKS = 4

type Point = { x: number; y: number }

/** Round tick values for an axis from `min` to `max` (at most `count` + 1 ticks). */
function ticks(min: number, max: number, count: number): number[] {
  if (min === max) return [min]
  const raw = (max - min) / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const out: number[] = []
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(Number(v.toFixed(10)))
  return out
}

const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/\.?0+$/, ''))

/**
 * Inline SVG line or bar chart for a connector card (no chart library).
 *
 * Behavior:
 *     Scales every series into one plot with labelled axes and round ticks. A
 *     `marker_x` draws a dashed vertical line labelled "Today". Hovering or
 *     focusing the chart and using the arrow keys shows a tooltip on the
 *     nearest point. Colours come from the theme tokens, so both themes work,
 *     and the SVG scales to its container's width.
 * Parameters:
 *     chart: The card's chart.
 *     title: Accessible name of the chart.
 */
export function ConnectorChart({ chart, title }: { chart: CardChart; title: string }) {
  const titleId = useId()
  const series = chart.series.map((s) => ({
    label: s.label,
    points: s.points.map((p) => ({ x: Number(p[0]), y: Number(p[1]) })).filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y)),
  }))
  const all = series.flatMap((s) => s.points)
  const [active, setActive] = useState<number | null>(null)
  if (all.length === 0) return <p className="text-xs text-muted">No data points.</p>

  const bar = chart.kind === 'bar'
  const xs = all.map((p) => p.x).concat(chart.marker_x ?? [])
  const ys = all.map((p) => p.y)
  const [xMin, xMax] = [Math.min(...xs), Math.max(...xs)]
  const yMin = Math.min(0, ...ys)
  const yMax = Math.max(...ys) * 1.08 || 1
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const sx = (x: number) => PAD.left + (xMax === xMin ? plotW / 2 : ((x - xMin) / (xMax - xMin)) * plotW)
  const sy = (y: number) => PAD.top + plotH - ((y - yMin) / (yMax - yMin)) * plotH
  const first = series[0].points
  const barW = Math.max(2, Math.min(18, (plotW / Math.max(1, first.length)) * 0.6))

  const nearest = (x: number) => first.reduce((best, p, i) => (Math.abs(sx(p.x) - x) < Math.abs(sx(first[best].x) - x) ? i : best), 0)
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect()
    setActive(nearest(((e.clientX - box.left) / box.width) * W))
  }
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const start = active ?? first.findIndex((p) => p.x >= (chart.marker_x ?? xMin))
    setActive(Math.min(first.length - 1, Math.max(0, start + (e.key === 'ArrowRight' ? 1 : -1))))
  }
  const point: Point | null = active === null ? null : first[active]

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full touch-none select-none overflow-visible outline-none focus-visible:ring-2 focus-visible:ring-accent/50 rounded-control"
      role="img"
      aria-labelledby={titleId}
      tabIndex={0}
      onPointerMove={onMove}
      onPointerLeave={() => setActive(null)}
      onFocus={() => setActive((a) => a ?? Math.max(0, first.findIndex((p) => p.x >= (chart.marker_x ?? xMin))))}
      onBlur={() => setActive(null)}
      onKeyDown={onKey}
      data-chart-kind={bar ? 'bar' : 'line'}
    >
      <title id={titleId}>{`${title}: ${chart.y_label} by ${chart.x_label}`}</title>
      {ticks(yMin, yMax, TICKS).map((t) => (
        <g key={`y${t}`}>
          <line x1={PAD.left} x2={W - PAD.right} y1={sy(t)} y2={sy(t)} stroke="rgb(var(--edge) / 0.08)" />
          <text x={PAD.left - 6} y={sy(t) + 3} textAnchor="end" fontSize="9" fill="rgb(var(--muted))">{fmt(t)}</text>
        </g>
      ))}
      {ticks(xMin, xMax, TICKS + 2).map((t) => (
        <text key={`x${t}`} x={sx(t)} y={H - PAD.bottom + 12} textAnchor="middle" fontSize="9" fill="rgb(var(--muted))">{fmt(t)}</text>
      ))}
      <text x={PAD.left + plotW / 2} y={H - 4} textAnchor="middle" fontSize="10" fill="rgb(var(--muted))">{chart.x_label}</text>
      <text x={10} y={PAD.top + plotH / 2} textAnchor="middle" fontSize="10" fill="rgb(var(--muted))" transform={`rotate(-90 10 ${PAD.top + plotH / 2})`}>
        {chart.y_label}
      </text>

      {series.map((s, i) => {
        const color = `rgb(${SERIES_COLORS[i % SERIES_COLORS.length]})`
        if (bar) {
          return s.points.map((p, k) => (
            <rect key={`${i}-${k}`} x={sx(p.x) - barW / 2 + i * 2} y={sy(p.y)} width={barW} height={Math.max(0, sy(yMin) - sy(p.y))} rx={2} fill={color} opacity={0.85} />
          ))
        }
        const d = s.points.map((p, k) => `${k ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ')
        return <path key={i} d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      })}

      {chart.marker_x != null && (
        <g data-marker="today">
          <line x1={sx(chart.marker_x)} x2={sx(chart.marker_x)} y1={PAD.top} y2={PAD.top + plotH} stroke="rgb(var(--fg) / 0.55)" strokeDasharray="3 3" />
          <text x={sx(chart.marker_x) + 4} y={PAD.top + 8} fontSize="9" fontWeight="600" fill="rgb(var(--fg))">Today</text>
        </g>
      )}

      {point && (
        <g data-tooltip pointerEvents="none">
          <circle cx={sx(point.x)} cy={sy(point.y)} r={4} fill="rgb(var(--accent))" stroke="rgb(var(--panel))" strokeWidth={2} />
          {(() => {
            const label = `${chart.x_label.split(' ')[0]} ${fmt(point.x)}: ${fmt(point.y)}`
            const w = label.length * 5.4 + 12
            const x = Math.min(W - PAD.right - w, Math.max(PAD.left, sx(point.x) - w / 2))
            const y = Math.max(0, sy(point.y) - 26)
            return (
              <>
                <rect x={x} y={y} width={w} height={17} rx={5} fill="rgb(var(--raised))" stroke="rgb(var(--edge) / 0.15)" />
                <text x={x + w / 2} y={y + 12} textAnchor="middle" fontSize="10" fill="rgb(var(--fg))">{label}</text>
              </>
            )
          })()}
        </g>
      )}
    </svg>
  )
}
