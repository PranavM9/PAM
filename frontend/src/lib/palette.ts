/**
 * Stable colors for clusters and token-count formatting.
 *
 * Behavior:
 *     The same `cluster_id` always maps to the same color, so a project keeps
 *     its color across reloads and agents.
 */

const PALETTE = [
  '#b8a9ff', '#f0abfc', '#7dd3fc', '#a5b4fc', '#fda4af', '#86efac',
  '#fcd34d', '#c4b5fd', '#93c5fd', '#f9a8d4', '#67e8f9', '#d8b4fe',
]

/** Color for a cluster; unclustered items get a neutral grey. */
export function clusterColor(clusterId: string | null | undefined): string {
  if (!clusterId) return '#9d93bd'
  let h = 0
  for (let i = 0; i < clusterId.length; i++) h = (Math.imul(h, 31) + clusterId.charCodeAt(i)) >>> 0
  return PALETTE[h % PALETTE.length]
}

/** Format a token count as `1.8k` above 1000. */
export function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k` : String(n)
}
