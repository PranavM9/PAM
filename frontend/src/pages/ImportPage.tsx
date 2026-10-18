import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { ErrorNote } from '../components/ErrorNote'
import { Dropzone } from '../components/import/Dropzone'
import { JobProgress, StageStepper } from '../components/import/JobProgress'
import { SourcePicker } from '../components/import/SourcePicker'
import { SOURCES, type ImportSource } from '../components/import/stages'
import { Markdown } from '../components/Markdown'
import { PageHeader } from '../components/PageHeader'
import { ResizeHandle } from '../components/Resizable'
import { usePaneSize } from '../lib/usePaneSize'
import { guide } from '../guides'
import { cliHints } from '../lib/cliHints'

/**
 * Import wizard: source picker, dropzone, live stage stepper, report and export guide.
 *
 * Behavior:
 *     Uploads with `POST /imports`, keeps the job id in the URL (`?job=`), and
 *     polls `GET /imports/{id}` every second until `done` or `error`. On `done`
 *     it invalidates graph, vault, search and agent queries so other pages refetch.
 *     The wizard sits in one main glass panel; the source's export guide sits
 *     beside it on wide screens and below it on narrow ones.
 */
export default function ImportPage() {
  const guidePane = usePaneSize({ id: 'import-guide', initial: 480, min: 340, max: 720 })
  const [params, setParams] = useSearchParams()
  const [source, setSource] = useState<ImportSource>((params.get('source') as ImportSource) || 'claude')
  const [fileName, setFileName] = useState<string | null>(null)
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
  const sourceLabel = SOURCES.find((s) => s.id === source)?.label

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="Import"
        subtitle="Bring your conversation history into the vault. Runs extract → normalize → derive → index → cluster."
        cli={cliHints.importRun(fileName ? `/demo/${fileName}` : undefined)}
      />
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto lg:flex-row lg:gap-0 lg:overflow-hidden">
        <section className="panel min-w-0 space-y-8 p-5 sm:p-8 lg:min-h-0 lg:flex-1 lg:overflow-y-auto" aria-label="Import steps">
          <SourcePicker value={source} onChange={pickSource} />
          <Dropzone sourceLabel={sourceLabel} fileName={fileName} busy={upload.isPending} onFile={start} />
          <ErrorNote error={upload.error ?? job.error} />
          <div className="divider border-t pt-8">
            {status ? (
              <JobProgress status={status} onReset={reset} onViewGraph={() => navigate('/graph')} />
            ) : (
              <div className="space-y-6">
                <div>
                  <div className="text-[15px] font-medium">Pipeline</div>
                  <p className="mt-1 text-sm text-muted">Each stage lights up here as your export is processed.</p>
                </div>
                <StageStepper />
              </div>
            )}
          </div>
        </section>

        <ResizeHandle pane={guidePane} side="after" label="Resize export guide" />
        <aside style={guidePane.style} className="panel p-5 sm:p-8 lg:min-h-0 lg:w-[var(--pane-w)] lg:shrink-0 lg:overflow-y-auto" aria-label="Export guide">
          <div className="eyebrow mb-4 flex items-center gap-2">
            <BookOpen size={14} strokeWidth={1.75} aria-hidden />
            Export guide
          </div>
          {exportGuide ? (
            <Markdown className="prose-p:leading-relaxed">{exportGuide.body}</Markdown>
          ) : (
            <p className="text-muted">No guide for this source.</p>
          )}
        </aside>
      </div>
    </div>
  )
}
