import type { ReactNode } from 'react'

/**
 * One titled section of the agent form, separated from its neighbours by a hairline.
 *
 * Behavior:
 *     At `2xl` the title and description sit in a narrow left column beside the
 *     controls; below that they stack above them.
 * Parameters:
 *     title: Section heading.
 *     description: One sentence on what the section controls.
 *     children: The section's controls.
 */
export function FormSection({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 py-7 first:pt-0 last:pb-0 2xl:grid-cols-[13rem_minmax(0,1fr)] 2xl:gap-8">
      <div>
        <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-fg">{title}</h2>
        {description && <p className="mt-1 text-[13px] leading-relaxed text-muted">{description}</p>}
      </div>
      <div className="min-w-0 space-y-5">{children}</div>
    </section>
  )
}

/**
 * Labelled form control with an optional hint underneath.
 *
 * Parameters:
 *     label: Sentence-case caption.
 *     hint: Helper text below the control.
 *     invalid: Shows the hint in the warning color.
 *     children: The control itself.
 */
export function Field({ label, hint, invalid, children }: { label: string; hint?: string; invalid?: boolean; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5">
      <span className="label">{label}</span>
      {children}
      {hint && <span className={`text-xs ${invalid ? 'text-warn' : 'text-muted'}`}>{hint}</span>}
    </label>
  )
}

/** Accent-colored native checkbox or radio, sized for comfortable clicking. */
export const choiceClass = 'h-4 w-4 shrink-0 cursor-pointer accent-accent disabled:cursor-not-allowed'

/**
 * Clickable row wrapping a native checkbox or radio, highlighted while checked.
 *
 * Parameters:
 *     children: The input followed by its text.
 *     className: Extra classes, e.g. padding.
 */
export function ChoiceRow({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <label
      className={`flex min-h-[2.5rem] cursor-pointer items-center gap-3 rounded-control px-3 text-sm transition duration-200 ease-out hover:bg-fg/[0.05] has-[:checked]:bg-accent/[0.12] has-[:disabled]:cursor-not-allowed ${className}`}
    >
      {children}
    </label>
  )
}
