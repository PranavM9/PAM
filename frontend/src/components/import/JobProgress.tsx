import { Check, CheckCircle2, Loader2, Network, RotateCcw, XCircle } from 'lucide-react'
import type { JobStatus } from '../../types/generated'
import { ErrorNote } from '../ErrorNote'
import { ORDER, STEPS } from './stages'

/**
 * Horizontal five-stage stepper for the import pipeline.
 *
 * Behavior:
 *     Without a `status` it previews the pipeline with every stage pending.
 *     Otherwise finished stages show a check, the running stage a spinner and
 *     a failed stage a cross, joined by a connector that fills as stages finish.
 * Parameters:
 *     status: Latest `JobStatus`, or undefined before an import starts.
 */
export function StageStepper({ status }: { status?: JobStatus }) {
  const current = status ? ORDER.indexOf(status.stage) : -1
  const failed = status?.stage === 'error'
  return (
    <ol className="grid grid-cols-5" aria-label="Import stages">
      {STEPS.map((step, i) => {
        const index = ORDER.indexOf(step.stage)
        const done = current > index && !failed
        const active = current === index && !failed
        const errored = failed && current === index
        const state = done ? 'done' : active ? 'running' : errored ? 'failed' : 'pending'
        return (
          <li key={step.stage} className="relative flex flex-col items-center gap-2 text-xs" aria-label={`${step.label}: ${state}`}>
            {i < STEPS.length - 1 && (
              <span
                aria-hidden
                className={`absolute left-[calc(50%+1.5rem)] right-[calc(-50%+1.5rem)] top-[1.125rem] h-px transition-colors duration-300 ease-out ${
                  done ? 'bg-accent/60' : 'bg-edge/[0.12]'
                }`}
              />
            )}
            <span
              aria-hidden
              className={`flex h-9 w-9 items-center justify-center rounded-full border transition duration-300 ease-out ${
                done
                  ? 'border-accent/40 bg-accent/20 text-accent'
                  : active
                    ? 'animate-halo border-accent/60 bg-accent/15 text-accent'
                    : errored
                      ? 'border-bad/40 bg-bad/15 text-bad'
                      : 'border-edge/15 bg-edge/[0.03] text-muted'
              }`}
            >
              {done ? (
                <Check size={16} strokeWidth={2} className="animate-pop" />
              ) : active ? (
                <Loader2 size={16} strokeWidth={1.75} className="animate-spin" />
              ) : errored ? (
                <XCircle size={16} strokeWidth={1.75} className="animate-pop" />
              ) : (
                <span className="text-[13px] tabular-nums">{i + 1}</span>
              )}
            </span>
            <span className={done || active ? 'font-medium text-fg' : errored ? 'text-bad' : 'text-muted'}>{step.label}</span>
          </li>
        )
      })}
    </ol>
  )
}

/**
 * Status line, progress bar, stage stepper and final `ImportReport` for one import job.
 *
 * Behavior:
 *     Announces stage changes politely to assistive tech. Shows "View graph"
 *     after a successful import and "Import another" once the job has ended.
 * Parameters:
 *     status: Latest `JobStatus` from the backend.
 *     onReset: Start another import.
 *     onViewGraph: Navigate to the graph page.
 */
export function JobProgress({ status, onReset, onViewGraph }: { status: JobStatus; onReset: () => void; onViewGraph: () => void }) {
  const failed = status.stage === 'error'
  const complete = status.stage === 'done'
  const report = status.report
  const percent = Math.round(status.progress * 100)
  return (
    <section className="space-y-6" aria-live="polite" aria-label="Import progress">
      <div className="flex items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[17px] font-medium tracking-[-0.01em]">
            {complete && <CheckCircle2 size={18} strokeWidth={1.75} className="animate-pop shrink-0 text-ok" aria-hidden />}
            {failed && <XCircle size={18} strokeWidth={1.75} className="shrink-0 text-bad" aria-hidden />}
            {failed ? 'Import failed' : complete ? 'Import complete' : status.stage === 'queued' ? 'Queued…' : 'Importing…'}
          </div>
          <div className="mt-1 truncate font-mono text-xs text-muted">{status.job_id}</div>
        </div>
        <div className="shrink-0 text-2xl font-semibold tabular-nums tracking-[-0.02em] text-fg">
          {percent}
          <span className="ml-0.5 text-sm font-normal text-muted">%</span>
        </div>
      </div>

      <div className="h-1.5 overflow-hidden rounded-full bg-edge/10">
        <div
          className={`h-full rounded-full transition-[width] duration-700 ease-out ${
            failed ? 'bg-bad' : 'bg-gradient-to-r from-accent-strong to-accent'
          }`}
          style={{ width: `${Math.max(3, status.progress * 100)}%` }}
        />
      </div>

      <StageStepper status={status} />

      {failed && <ErrorNote error={new Error(status.error ?? 'Import failed')} />}

      {report && (
        <div className="enter well space-y-4 p-5">
          <dl className="stagger grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-4">
            <Stat label="Found" value={report.conversations_found} />
            <Stat label="Written" value={report.episodes_written} />
            <Stat label="Skipped" value={report.episodes_skipped_existing} />
            <Stat label="Errors" value={report.errors?.length ?? 0} />
          </dl>
          <div className="divider flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t pt-4 text-xs text-muted">
            <span className="badge">{report.source}</span>
            <span className="min-w-0 break-all font-mono">{report.archived_path}</span>
            <span className="font-mono">{report.commit_sha ? `commit ${report.commit_sha}` : 'no commit'}</span>
            <span className="tabular-nums">{(report.duration_ms / 1000).toFixed(1)}s</span>
          </div>
          {report.errors && report.errors.length > 0 && (
            <ul className="space-y-1 text-xs text-bad">
              {report.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {(complete || failed) && (
        <div className="enter flex flex-wrap gap-2 [animation-delay:200ms]">
          {complete && (
            <button type="button" className="btn btn-primary min-h-[2.75rem] px-5" onClick={onViewGraph}>
              <Network size={16} strokeWidth={1.75} aria-hidden /> View graph
            </button>
          )}
          <button type="button" className="btn min-h-[2.75rem] px-5" onClick={onReset}>
            <RotateCcw size={16} strokeWidth={1.75} aria-hidden /> Import another
          </button>
        </div>
      )}
    </section>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-[13px] text-muted">{label}</dt>
      <dd className="mt-0.5 text-2xl font-semibold tabular-nums tracking-[-0.02em]">{value}</dd>
    </div>
  )
}
