import type { ModelEntry } from '../../types/generated'
import type { Mode } from './types'

/**
 * Model picker for the conversation header.
 *
 * Behavior:
 *     Lists the models from `GET /models`, marking those that support tool
 *     calls. Shows a disabled-looking "Loading…" option until the list arrives.
 * Parameters:
 *     models: Available models.
 *     value: Selected model id.
 *     onChange: Called with the new model id.
 */
export function ModelSelect({ models, value, onChange }: { models: ModelEntry[]; value: string; onChange: (id: string) => void }) {
  return (
    <select
      className="input min-w-0 max-w-full flex-1 sm:max-w-[18rem] sm:flex-none"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Model"
    >
      {models.length === 0 && <option value="">Loading…</option>}
      {models.map((m) => (
        <option key={m.id} value={m.id}>
          {m.label}
          {m.supports_tools ? ' · tools' : ''}
        </option>
      ))}
    </select>
  )
}

/**
 * Segmented control choosing between context injection and tool mode.
 *
 * Behavior:
 *     Tool mode is disabled, with an explanatory tooltip, when the selected
 *     model does not support tool calls.
 * Parameters:
 *     mode: The active mode.
 *     onChange: Called with the chosen mode.
 *     toolsSupported: Whether the selected model supports tool calls.
 */
export function ModeToggle({ mode, onChange, toolsSupported }: { mode: Mode; onChange: (m: Mode) => void; toolsSupported: boolean }) {
  return (
    <div
      role="radiogroup"
      aria-label="Context mode"
      className="inline-flex shrink-0 rounded-control border border-edge/10 bg-bg/30 p-0.5 text-[13px]"
    >
      {(['injection', 'tool'] as const).map((m) => (
        <button
          key={m}
          type="button"
          role="radio"
          aria-checked={mode === m}
          disabled={m === 'tool' && !toolsSupported}
          title={m === 'tool' && !toolsSupported ? 'This model does not support tool calls' : undefined}
          onClick={() => onChange(m)}
          className={`min-h-[2rem] rounded-[11px] px-3 capitalize transition duration-200 ease-out disabled:cursor-not-allowed disabled:opacity-40 ${
            mode === m
              ? 'bg-gradient-to-b from-accent/30 to-accent/15 font-medium text-fg shadow-[inset_0_1px_0_rgb(var(--edge)/0.14)]'
              : 'text-muted hover:text-fg'
          }`}
        >
          {m}
        </button>
      ))}
    </div>
  )
}
