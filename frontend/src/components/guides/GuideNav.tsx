import type { CSSProperties } from 'react'
import type { Guide } from '../../guides'
import { guideKind } from './guideKind'

/**
 * Quiet glass navigation listing the guides, grouped by kind.
 *
 * Behavior:
 *     Groups keep the order of first appearance in `guides`. The selected
 *     guide is marked with `aria-current="page"`.
 * Parameters:
 *     guides: All guides, already sorted.
 *     selected: Slug of the guide being read.
 *     onSelect: Called with the slug of a clicked guide.
 *     style: Inline style; sets `--pane-w`, the width from `lg` up.
 */
export function GuideNav({
  guides,
  selected,
  onSelect,
  style,
}: {
  guides: Guide[]
  selected: string | undefined
  onSelect: (slug: string) => void
  style?: CSSProperties
}) {
  const groups = new Map<string, Guide[]>()
  for (const g of guides) {
    const label = guideKind(g.slug).label
    groups.set(label, [...(groups.get(label) ?? []), g])
  }
  return (
    <nav aria-label="Guides" style={style} className="panel shrink-0 p-3 sm:p-4 lg:max-h-full lg:w-[var(--pane-w)] lg:self-start lg:overflow-auto">
      {[...groups].map(([label, items]) => (
        <div key={label} className="mb-3 last:mb-0">
          <h2 className="px-3 pb-1.5 pt-2 text-[13px] font-medium text-muted">{label}</h2>
          <ul className="stagger space-y-1">
            {items.map((g) => {
              const active = g.slug === selected
              const Icon = guideKind(g.slug).icon
              return (
                <li key={g.slug}>
                  <button
                    type="button"
                    onClick={() => onSelect(g.slug)}
                    aria-current={active ? 'page' : undefined}
                    className={`flex min-h-[2.75rem] w-full items-center gap-3 rounded-[14px] px-3 py-2 text-left text-sm leading-snug transition duration-200 ease-out ${
                      active
                        ? 'bg-accent/15 font-medium text-fg shadow-[inset_0_1px_0_rgb(var(--edge)/0.12)]'
                        : 'text-muted hover:bg-fg/[0.06] hover:text-fg'
                    }`}
                  >
                    <Icon size={16} strokeWidth={1.75} className={`shrink-0 ${active ? 'text-accent' : ''}`} aria-hidden />
                    <span className="min-w-0">{g.title}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </nav>
  )
}
