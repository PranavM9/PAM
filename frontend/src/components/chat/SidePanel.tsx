import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'

/**
 * Glass side column that becomes an overlay drawer below the `xl` breakpoint.
 *
 * Behavior:
 *     From `xl` up the panel sits in the page row at a fixed width. Below
 *     `xl` it is hidden until `open`, then floats over the page on a scrim
 *     with a close button; Escape or a click on the scrim calls `onClose`.
 *     The children stay mounted in both cases.
 * Parameters:
 *     as: Landmark element to render, `nav` or `aside`.
 *     id: Element id, referenced by the toggle's `aria-controls`.
 *     label: Accessible name of the landmark.
 *     title: Visible heading.
 *     side: Edge the drawer attaches to below `xl`.
 *     open: Whether the drawer is shown below `xl`.
 *     onClose: Called to close the drawer.
 *     width: Width classes used from `xl` up.
 *     actions: Controls shown under the heading.
 *     children: Panel content.
 */
export function SidePanel({
  as: Tag,
  id,
  label,
  title,
  side,
  open,
  onClose,
  width,
  actions,
  children,
}: {
  as: 'nav' | 'aside'
  id: string
  label: string
  title: string
  side: 'left' | 'right'
  open: boolean
  onClose: () => void
  width: string
  actions?: ReactNode
  children: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const drawer = open
    ? `fixed inset-y-3 z-40 flex w-[min(21rem,calc(100vw-1.5rem))] ${side === 'left' ? 'left-3' : 'right-3'}`
    : 'hidden'
  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-bg/60 backdrop-blur-[2px] xl:hidden" onClick={onClose} aria-hidden />}
      <Tag
        id={id}
        aria-label={label}
        className={`panel min-h-0 flex-col overflow-hidden ${drawer} xl:static xl:z-auto xl:flex xl:shrink-0 ${width}`}
      >
        <div className="flex shrink-0 items-center justify-between gap-2 px-5 pb-3 pt-5">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-fg">{title}</h2>
          <button type="button" className="icon-btn -mr-1.5 xl:hidden" onClick={onClose} aria-label={`Close ${title.toLowerCase()}`}>
            <X size={18} strokeWidth={1.75} />
          </button>
        </div>
        {actions && <div className="shrink-0 px-4 pb-3">{actions}</div>}
        {children}
      </Tag>
    </>
  )
}
