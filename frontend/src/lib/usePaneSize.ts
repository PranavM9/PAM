/** Remembered, clamped pane widths for resizable layouts. */
import { useCallback, useEffect, useState, type CSSProperties } from 'react'

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)))
}

function load(key: string, fallback: number, min: number, max: number): number {
  try {
    const saved = Number(localStorage.getItem(key))
    return Number.isFinite(saved) && saved > 0 ? clamp(saved, min, max) : fallback
  } catch {
    return fallback
  }
}

/** Size limits and persistence key for one resizable pane. */
export interface PaneSpec {
  id: string
  initial: number
  min: number
  max: number
}

/** State returned by `usePaneSize`: the width and a setter that clamps. */
export interface PaneSize extends PaneSpec {
  size: number
  setSize: (px: number) => void
  reset: () => void
  /** Inline style that exposes the width as `--pane-w` for `lg:w-[var(--pane-w)]`. */
  style: CSSProperties
}

/**
 * Remember a pane's width in pixels within sensible limits.
 *
 * Behavior:
 *     The width is clamped to `[min, max]` and stored in `localStorage`
 *     (`pam-pane:<id>`), so each layout keeps the user's choice across reloads.
 *     The width is exposed as the CSS variable `--pane-w`; components apply it
 *     only at the breakpoint where panes sit side by side.
 * Returns:
 *     The current size, a clamping setter, a reset to the default, and `style`.
 * Parameters:
 *     spec: Persistence id, default width and the allowed range.
 */
export function usePaneSize(spec: PaneSpec): PaneSize {
  const key = `pam-pane:${spec.id}`
  const [size, setRaw] = useState(() => load(key, spec.initial, spec.min, spec.max))
  const setSize = useCallback((px: number) => setRaw(clamp(px, spec.min, spec.max)), [spec.min, spec.max])
  const reset = useCallback(() => setRaw(spec.initial), [spec.initial])

  useEffect(() => {
    try {
      localStorage.setItem(key, String(size))
    } catch {
      // Storage unavailable: the size lasts for this page view.
    }
  }, [key, size])

  return { ...spec, size, setSize, reset, style: { '--pane-w': `${size}px` } as CSSProperties }
}
