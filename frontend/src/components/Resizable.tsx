import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { PaneSize } from '../lib/usePaneSize'

const STEP = 16
const BIG_STEP = 64

/**
 * Draggable divider that resizes the pane on one side of it.
 *
 * Behavior:
 *     Occupies the gap between two panes (`w-4`, the same spacing as `gap-4`).
 *     Dragging with a mouse, pen or finger changes the pane width; the arrow
 *     keys move it by 16 px (64 px with Shift), Home/End jump to the limits,
 *     and a double-click or Enter restores the default. A thin lavender grip
 *     shows on hover, focus and while dragging. Hidden below `breakpoint`,
 *     where the panes stack.
 * Parameters:
 *     pane: The pane state from `usePaneSize`.
 *     side: Where the resized pane is: `before` (left of the handle, grows
 *         when dragged right) or `after` (right of the handle, grows when
 *         dragged left).
 *     label: Accessible name, e.g. "Resize sessions panel".
 *     breakpoint: First breakpoint at which the handle shows.
 *     className: Extra classes, e.g. for absolute positioning.
 */
export function ResizeHandle({
  pane,
  side,
  label,
  breakpoint = 'lg',
  className = '',
}: {
  pane: PaneSize
  side: 'before' | 'after'
  label: string
  breakpoint?: 'md' | 'lg' | 'xl'
  className?: string
}) {
  const drag = useRef<{ x: number; size: number } | null>(null)
  const [dragging, setDragging] = useState(false)
  const sign = side === 'before' ? 1 : -1

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, size: pane.size }
    setDragging(true)
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    pane.setSize(drag.current.size + sign * (e.clientX - drag.current.x))
  }
  const stop = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    drag.current = null
    setDragging(false)
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? BIG_STEP : STEP
    const moves: Record<string, () => void> = {
      ArrowRight: () => pane.setSize(pane.size + sign * step),
      ArrowLeft: () => pane.setSize(pane.size - sign * step),
      Home: () => pane.setSize(pane.min),
      End: () => pane.setSize(pane.max),
      Enter: pane.reset,
    }
    const move = moves[e.key]
    if (move) {
      e.preventDefault()
      move()
    }
  }

  useEffect(() => {
    if (!dragging) return
    const { cursor, userSelect } = document.body.style
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    return () => {
      document.body.style.cursor = cursor
      document.body.style.userSelect = userSelect
    }
  }, [dragging])

  const show = { md: 'md:flex', lg: 'lg:flex', xl: 'xl:flex' }[breakpoint]
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={pane.size}
      aria-valuemin={pane.min}
      aria-valuemax={pane.max}
      title="Drag to resize · double-click to reset"
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={stop}
      onPointerCancel={stop}
      onDoubleClick={pane.reset}
      onKeyDown={onKeyDown}
      className={`group hidden w-4 shrink-0 cursor-col-resize touch-none select-none items-center justify-center self-stretch rounded-full outline-none ${show} ${className}`}
    >
      <span
        aria-hidden
        className={`h-12 w-1 rounded-full transition-colors duration-200 ease-out ${
          dragging ? 'bg-accent' : 'bg-edge/[0.14] group-hover:bg-accent/70 group-focus-visible:bg-accent'
        }`}
      />
    </div>
  )
}
