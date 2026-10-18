/**
 * Stable colors for clusters and token-count formatting.
 *
 * Behavior:
 *     The same `cluster_id` always maps to the same color, so a project keeps
 *     its color across reloads and agents.
 */

const PALETTE = [
  '#818cf8', '#f472b6', '#34d399', '#fbbf24', '#60a5fa', '#f87171',
  '#a78bfa', '#2dd4bf', '#fb923c', '#a3e635', '#e879f9', '#38bdf8',
]

/** Color for a cluster; unclustered items get a neutral grey. */
export function clusterColor(clusterId: string | null | undefined): string {
  if (!clusterId) return '#8c93a3'
  let h = 0
  for (let i = 0; i < clusterId.length; i++) h = (Math.imul(h, 31) + clusterId.charCodeAt(i)) >>> 0
  return PALETTE[h % PALETTE.length]
}

/** Format a token count as `1.8k` above 1000. */
export function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k` : String(n)
}
