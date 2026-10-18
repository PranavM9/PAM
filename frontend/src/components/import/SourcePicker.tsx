import { SOURCES, type ImportSource } from './stages'

/**
 * Segmented radio group for the export's source platform.
 *
 * Behavior:
 *     Renders the three sources as one small segmented control (label only,
 *     no hint line); the selected segment is lifted with a soft accent fill.
 * Parameters:
 *     value: Selected source.
 *     onChange: Called with the source the user picks.
 */
export function SourcePicker({ value, onChange }: { value: ImportSource; onChange: (id: ImportSource) => void }) {
  return (
    <fieldset>
      <legend className="label mb-2">Source</legend>
      <div className="well grid grid-cols-3 gap-1 p-1" role="radiogroup">
        {SOURCES.map((s) => {
          const selected = value === s.id
          return (
            <button
              key={s.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(s.id)}
              className={`min-h-[2.25rem] rounded-[10px] px-3 py-1.5 text-center transition duration-200 ease-out ${
                selected
                  ? 'bg-accent/15 text-fg shadow-[inset_0_1px_0_rgb(var(--edge)/0.14)]'
                  : 'text-fg/80 hover:bg-fg/[0.05] hover:text-fg'
              }`}
            >
              <div className="text-[13px] font-medium" title={s.hint}>{s.label}</div>
            </button>
          )
        })}
      </div>
    </fieldset>
  )
}
