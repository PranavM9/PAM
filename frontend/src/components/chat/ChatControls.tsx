import { Check, ChevronDown, Cpu } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import type { ModelEntry } from '../../types/generated'
import type { Mode } from './types'

/**
 * Model picker for the conversation header.
 *
 * Behavior:
 *     Lists the models from `GET /models`, marking those that support tool
 *     calls. Shows a disabled-looking "Loading…" option until the list arrives, and a link to
 *     Settings when the list has loaded and is empty.
 * Parameters:
 *     models: Available models.
 *     loaded: True once `GET /models` has answered.
 *     value: Selected model id.
 *     onChange: Called with the new model id.
 */
export function ModelSelect({ models, loaded = false, value, onChange }: { models: ModelEntry[]; loaded?: boolean; value: string; onChange: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const selected = models.find((model) => model.id === value)
  const listId = 'chat-model-options'

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: globalThis.PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const moveOption = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const options = [...(root.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? [])]
    const current = options.indexOf(document.activeElement as HTMLButtonElement)
    const direction = event.key === 'ArrowDown' ? 1 : -1
    const next = (current + direction + options.length) % options.length
    options[next]?.focus()
  }

  if (loaded && models.length === 0) {
    return (
      <Link
        to="/settings"
        className="well flex h-9 w-full items-center gap-2 rounded-xl border border-edge/10 bg-panel/65 px-3 text-sm text-fg shadow-sm transition hover:bg-panel/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent sm:w-[18rem]"
      >
        <Cpu size={15} className="shrink-0 text-accent" aria-hidden />
        <span className="min-w-0 flex-1 truncate">No models yet: add one in Settings</span>
      </Link>
    )
  }

  return (
    <div ref={root} className="relative min-w-0 flex-1 sm:w-[18rem] sm:flex-none">
      <button
        type="button"
        role="combobox"
        aria-label="Model"
        aria-expanded={open}
        aria-controls={listId}
        aria-haspopup="listbox"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            setOpen(true)
            requestAnimationFrame(() => root.current?.querySelector<HTMLButtonElement>('[role="option"]')?.focus())
          }
        }}
        className="well flex h-9 w-full items-center gap-2 rounded-xl border border-edge/10 bg-panel/65 px-3 text-left text-sm text-fg shadow-sm transition hover:bg-panel/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <Cpu size={15} className="shrink-0 text-accent" aria-hidden />
        <span className="min-w-0 flex-1 truncate">{selected?.label ?? (models.length ? 'Choose model' : 'Loading models…')}</span>
        {selected?.supports_tools && <span className="shrink-0 rounded-md bg-accent/10 px-1.5 py-0.5 text-[10px] text-muted">Tools</span>}
        <ChevronDown size={14} className={`shrink-0 text-muted transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
      </button>
      {open && (
        <div id={listId} role="listbox" aria-label="Available models" className="absolute right-0 top-full z-50 mt-2 max-h-72 w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-edge/15 bg-panel/95 p-1.5 shadow-2xl backdrop-blur-2xl">
          {models.map((model) => {
            const active = model.id === value
            return (
              <button
                key={model.id}
                type="button"
                role="option"
                aria-selected={active}
                onKeyDown={moveOption}
                onClick={() => { onChange(model.id); setOpen(false) }}
                className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition ${active ? 'bg-accent/15 text-fg' : 'text-fg/85 hover:bg-fg/[0.06]'}`}
              >
                <span className="min-w-0 flex-1 truncate text-sm">{model.label}</span>
                {model.supports_tools && <span className="text-[10px] text-muted">Tools</span>}
                {active && <Check size={15} className="shrink-0 text-accent" aria-hidden />}
              </button>
            )
          })}
        </div>
      )}
    </div>
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
              ? 'bg-accent/15 font-medium text-fg shadow-[inset_0_1px_0_rgb(var(--edge)/0.14)]'
              : 'text-muted hover:text-fg'
          }`}
        >
          {m}
        </button>
      ))}
    </div>
  )
}
