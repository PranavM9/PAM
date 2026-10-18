import { Check, Copy, Terminal } from 'lucide-react'
import { useState } from 'react'

/**
 * Show the equivalent `pam …` command with a copy button.
 *
 * Behavior:
 *     Renders the command in monospace. The button copies it to the clipboard
 *     and shows a check mark for 1.5 s.
 * Parameters:
 *     command: The CLI command, usually from `cliHints`.
 *     label: Caption shown before the command.
 */
export function CliHint({ command, label = 'CLI' }: { command: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-md border border-line bg-raised/60 px-2.5 py-1.5 text-xs">
      <Terminal size={14} className="shrink-0 text-muted" aria-hidden />
      <span className="shrink-0 text-muted">{label}</span>
      <code className="min-w-0 flex-1 truncate font-mono text-fg" title={command}>
        {command}
      </code>
      <button
        type="button"
        onClick={copy}
        className="shrink-0 rounded p-1 text-muted hover:text-fg"
        aria-label={copied ? 'Copied' : `Copy command: ${command}`}
      >
        {copied ? <Check size={14} className="text-ok" /> : <Copy size={14} />}
      </button>
    </div>
  )
}
