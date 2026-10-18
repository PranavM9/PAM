import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Circle, FileUp, Loader2, Network, RotateCcw, XCircle } from 'lucide-react'
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { ErrorNote } from '../components/ErrorNote'
import { Markdown } from '../components/Markdown'
import { PageHeader } from '../components/PageHeader'
import { guide } from '../guides'
import { cliHints } from '../lib/cliHints'
import type { JobStatus } from '../types/generated'

type ImportSource = 'claude' | 'chatgpt' | 'gemini'

const SOURCES: { id: ImportSource; label: string; hint: string }[] = [
  { id: 'claude', label: 'Claude', hint: 'conversations zip' },
  { id: 'chatgpt', label: 'ChatGPT', hint: 'data export zip' },
  { id: 'gemini', label: 'Gemini', hint: 'Google Takeout' },
]

const STEPS: { stage: JobStatus['stage']; label: string }[] = [
  { stage: 'extract', label: 'Extract' },
  { stage: 'normalize', label: 'Normalize' },
  { stage: 'derive', label: 'Derive' },
  { stage: 'index', label: 'Index' },
  { stage: 'cluster', label: 'Cluster' },
]
const ORDER: JobStatus['stage'][] = ['queued', 'extract', 'normalize', 'derive', 'index', 'cluster', 'done']

/**
 * Import wizard: source picker, export guide, dropzone, live stage stepper, report.
 *
 * Behavior:
 *     Uploads with `POST /imports`, keeps the job id in the URL (`?job=`), and
 *     polls `GET /imports/{id}` every second until `done` or `error`. On `done`
 *     it invalidates graph, vault, search and agent queries so other pages refetch.
 */
export default function ImportPage() {
  const [params, setParams] = useSearchParams()
  const [source, setSource] = useState<ImportSource>((params.get('source') as ImportSource) || 'claude')
  const [fileName, setFileName] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const jobId = params.get('job')

  const upload = useMutation({
    mutationFn: (file: File) => api.createImport(file, { source }),
    onSuccess: (job) => setParams({ source, job: job.job_id }),
  })
  const job = useQuery({
    queryKey: ['import', jobId],
    queryFn: () => api.getImport(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (q) => (q.state.data && ['done', 'error'].includes(q.state.data.stage) ? false : 1000),
  })
  const status = job.data ?? (upload.data?.job_id === jobId ? upload.data : undefined)
  const finished = status?.stage === 'done'

  useEffect(() => {
    if (!finished) return
    for (const key of ['graph', 'vault-tree', 'vault-file', 'search', 'agents']) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
  }, [finished, queryClient])

  const start = (file: File | undefined) => {
    if (!file) return
    setFileName(file.name)
    upload.mutate(file)
  }
  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    start(event.dataTransfer.files[0])
  }
  const reset = () => {
    upload.reset()
    setFileName(null)
    setParams({ source })
  }
  const pickSource = (id: ImportSource) => {
    setSource(id)
    setParams(jobId ? { source: id, job: jobId } : { source: id })
  }
  const exportGuide = guide(`export-${source}`)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="Import"
        subtitle="Bring your conversation history into the vault. Runs extract → normalize → derive → index → cluster."
        cli={cliHints.importRun(fileName ? `/demo/${fileName}` : undefined)}
      />
      <div className="grid min-h-0 flex-1 gap-6 overflow-auto p-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="space-y-5" aria-label="Import steps">
          <fieldset>
            <legend className="label mb-2">1 · Source</legend>
            <div className="grid grid-cols-3 gap-2" role="radiogroup">
              {SOURCES.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  role="radio"
                  aria-checked={source === s.id}
                  onClick={() => pickSource(s.id)}
                  className={`card px-3 py-3 text-left transition-colors ${
                    source === s.id ? 'border-accent bg-accent/10' : 'hover:border-accent/50'
                  }`}
                >
                  <div className="font-medium">{s.label}</div>
                  <div className="text-xs text-muted">{s.hint}</div>
                </button>
              ))}
            </div>
          </fieldset>

          <div>
            <div className="label mb-2">2 · Export file</div>
            <div
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={`flex flex-col items-center gap-3 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors ${
                dragging ? 'border-accent bg-accent/10' : 'border-line bg-panel'
              }`}
            >
              <FileUp size={28} className="text-muted" aria-hidden />
              <p className="text-sm">
                Drop your {SOURCES.find((s) => s.id === source)?.label} export here
                <span className="text-muted"> (.zip or .json)</span>
              </p>
              <button type="button" className="btn btn-primary" onClick={() => input.current?.click()} disabled={upload.isPending}>
                {upload.isPending ? <Loader2 size={14} className="animate-spin" /> : <FileUp size={14} />}
                Choose file
              </button>
              <input
                ref={input}
                type="file"
                accept=".zip,.json,application/zip,application/json"
                className="sr-only"
                tabIndex={-1}
                aria-label="Export file"
                onChange={(e) => {
                  start(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
            </div>
          </div>

          <ErrorNote error={upload.error ?? job.error} />

          {status && <JobProgress status={status} onReset={reset} onViewGraph={() => navigate('/graph')} />}
        </section>

        <aside className="card min-h-0 overflow-auto p-5" aria-label="Export guide">
          {exportGuide ? <Markdown>{exportGuide.body}</Markdown> : <p className="text-muted">No guide for this source.</p>}
        </aside>
      </div>
    </div>
  )
}

/**
 * Stage stepper, progress bar and final `ImportReport` for one import job.
 *
 * Parameters:
 *     status: Latest `JobStatus` from the backend.
 *     onReset: Start another import.
 *     onViewGraph: Navigate to the graph page.
 */
function JobProgress({ status, onReset, onViewGraph }: { status: JobStatus; onReset: () => void; onViewGraph: () => void }) {
  const current = ORDER.indexOf(status.stage)
  const failed = status.stage === 'error'
  const report = status.report
  return (
    <section className="card space-y-4 p-4" aria-live="polite" aria-label="Import progress">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">
          {failed ? 'Import failed' : status.stage === 'done' ? 'Import complete' : status.stage === 'queued' ? 'Queued…' : 'Importing…'}
        </span>
        <span className="font-mono text-xs text-muted">
          {status.job_id} · {Math.round(status.progress * 100)}%
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-raised">
        <div
          className={`h-full rounded-full transition-[width] duration-700 ${failed ? 'bg-bad' : 'bg-accent'}`}
          style={{ width: `${Math.max(3, status.progress * 100)}%` }}
        />
      </div>
      <ol className="grid grid-cols-5 gap-2">
        {STEPS.map((step) => {
          const index = ORDER.indexOf(step.stage)
          const done = current > index && !failed
          const active = current === index && !failed
          return (
            <li key={step.stage} className="flex flex-col items-center gap-1 text-xs">
              {done ? (
                <CheckCircle2 size={18} className="text-ok" aria-hidden />
              ) : active ? (
                <Loader2 size={18} className="animate-spin text-accent" aria-hidden />
              ) : failed && current === index ? (
                <XCircle size={18} className="text-bad" aria-hidden />
              ) : (
                <Circle size={18} className="text-line" aria-hidden />
              )}
              <span className={done || active ? 'text-fg' : 'text-muted'}>{step.label}</span>
            </li>
          )
        })}
      </ol>
      {failed && <ErrorNote error={new Error(status.error ?? 'Import failed')} />}
      {report && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-md bg-raised/60 p-3 text-sm sm:grid-cols-4">
          <Stat label="found" value={report.conversations_found} />
          <Stat label="written" value={report.episodes_written} />
          <Stat label="skipped" value={report.episodes_skipped_existing} />
          <Stat label="errors" value={report.errors?.length ?? 0} />
          <div className="col-span-full mt-1 font-mono text-xs text-muted">
            {report.source} · {report.archived_path} · {report.commit_sha ? `commit ${report.commit_sha}` : 'no commit'} ·{' '}
            {(report.duration_ms / 1000).toFixed(1)}s
          </div>
          {report.errors?.map((e) => (
            <div key={e} className="col-span-full text-xs text-bad">
              {e}
            </div>
          ))}
        </dl>
      )}
      {(status.stage === 'done' || failed) && (
        <div className="flex gap-2">
          {status.stage === 'done' && (
            <button type="button" className="btn btn-primary" onClick={onViewGraph}>
              <Network size={14} /> View graph
            </button>
          )}
          <button type="button" className="btn" onClick={onReset}>
            <RotateCcw size={14} /> Import another
          </button>
        </div>
      )}
    </section>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  )
}
