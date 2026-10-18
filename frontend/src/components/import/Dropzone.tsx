import { FileArchive, FileUp, Loader2 } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'

/**
 * Drop target and file picker for an export archive.
 *
 * Behavior:
 *     Accepts a dropped file or one chosen through the hidden
 *     `input[type=file]` behind the "Choose file" button, and passes the first
 *     file to `onFile`. The input is cleared after each pick so the same file
 *     can be chosen again.
 * Parameters:
 *     sourceLabel: Display name of the selected source.
 *     fileName: Name of the last chosen file, if any.
 *     busy: Disables the button and shows a spinner while uploading.
 *     compact: Render as a single short row, used once a job is running so
 *         the stage stepper becomes the focal point.
 *     onFile: Called with the chosen file.
 */
export function Dropzone({
  sourceLabel,
  fileName,
  busy,
  compact = false,
  onFile,
}: {
  sourceLabel?: string
  fileName: string | null
  busy: boolean
  compact?: boolean
  onFile: (file: File | undefined) => void
}) {
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    onFile(event.dataTransfer.files[0])
  }
  return (
    <div>
      <div className="label mb-3">Export file</div>
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`relative flex overflow-hidden rounded-card border border-dashed transition duration-200 ease-out ${
          compact
            ? 'flex-wrap items-center gap-4 px-4 py-4 sm:px-5'
            : 'flex-col items-center gap-4 px-6 py-10 text-center sm:py-12'
        } ${
          dragging ? 'border-accent/70 bg-accent/10' : 'border-edge/20 bg-edge/[0.03]'
        }`}
      >
        <div
          aria-hidden
          className="pointer-events-none absolute left-1/2 top-0 h-40 w-72 max-w-full -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent/20 blur-3xl"
        />
        <div
          className={`relative flex shrink-0 items-center justify-center border border-edge/15 bg-gradient-to-b from-accent/30 to-accent-strong/15 text-accent shadow-[inset_0_1px_0_rgb(var(--edge)/0.18),0_10px_30px_rgb(var(--accent-strong)/0.25)] ${
            compact ? 'h-11 w-11 rounded-[14px]' : 'h-14 w-14 rounded-2xl'
          }`}
        >
          <FileUp size={compact ? 20 : 24} strokeWidth={1.75} aria-hidden />
        </div>
        <div className="relative space-y-1">
          <p className="text-[17px] font-medium tracking-[-0.01em] text-fg">Drop your {sourceLabel} export here</p>
          <p className="text-sm text-muted">A .zip or .json file, or choose one below</p>
        </div>
        <button
          type="button"
          className="btn btn-primary relative min-h-[2.75rem] px-5"
          onClick={() => input.current?.click()}
          disabled={busy}
        >
          {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <FileUp size={16} strokeWidth={1.75} aria-hidden />}
          Choose file
        </button>
        {fileName && (
          <p className="relative flex max-w-full items-center gap-2 text-xs text-muted">
            <FileArchive size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
            <span className="truncate font-mono">{fileName}</span>
          </p>
        )}
        <input
          ref={input}
          type="file"
          accept=".zip,.json,application/zip,application/json"
          className="sr-only"
          tabIndex={-1}
          aria-label="Export file"
          onChange={(e) => {
            onFile(e.target.files?.[0])
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}
