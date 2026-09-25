import { useEffect, useMemo, useState } from 'react'
import type { JobStatus, QuickPixelizeResult, QuickSession } from '../../api'
import { createQuickSession, getJob, getQuickSession, jobWebsocketUrl, makeQuickSprite, quickPixelize, retryJob, selectQuickSource, uploadImage } from '../../api'
import SourceInputPanel, { type QuickSourceDraft } from './SourceInputPanel'
import SourcePreview from './SourcePreview'
import QuickPixelizePanel from './QuickPixelizePanel'
import MakeSpritePanel from './MakeSpritePanel'
import QuickProgress from './QuickProgress'
import QuickResult from './QuickResult'
import { useQuickText } from './quickText'

type Stage = 'input' | 'ready' | 'pixelize' | 'make' | 'progress' | 'result'

interface Props { onOpenStudio: (runId?: string) => void }

export default function QuickGeneratePage({ onOpenStudio }: Props) {
  const text = useQuickText()
  const [stage, setStage] = useState<Stage>('input')
  const [session, setSession] = useState<QuickSession | null>(null)
  const [pixelizeResult, setPixelizeResult] = useState<QuickPixelizeResult | null>(null)
  const [runId, setRunId] = useState('')
  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState<JobStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const terminal = job?.status === 'succeeded' || job?.status === 'failed' || job?.status === 'cancelled' || job?.status === 'interrupted'
  const stageLabel = useMemo(() => ({ input: text.sourceStep, ready: text.readyStep, pixelize: text.pixelizeStep, make: text.makeStep, progress: text.progressStep, result: text.resultStep } satisfies Record<Stage, string>)[stage], [stage, text])

  useEffect(() => {
    const saved = window.localStorage.getItem('sprite-studio-quick-session')
    if (!saved) return
    void getQuickSession(saved).then((next) => {
      setSession(next)
      if (next.run_id && next.job_id) {
        setRunId(next.run_id)
        setJobId(next.job_id)
        setStage('progress')
        void getJob(next.run_id, next.job_id).then((status) => {
          setJob(status)
          if (status.status === 'succeeded') setStage('result')
        }).catch(() => undefined)
      } else {
        setStage('ready')
      }
    }).catch(() => window.localStorage.removeItem('sprite-studio-quick-session'))
  }, [])

  useEffect(() => {
    if (!runId || !jobId || terminal) return
    let disposed = false
    const receive = (next: JobStatus) => {
      if (disposed) return
      setJob(next)
      if (next.status === 'succeeded') setStage('result')
    }
    let socket: WebSocket | null = null
    try {
      socket = new WebSocket(jobWebsocketUrl(runId, jobId))
      socket.onmessage = (event) => {
        try { receive(JSON.parse(event.data) as JobStatus) } catch { /* polling remains the fallback */ }
      }
    } catch {
      // Some embedded WebViews do not expose WebSocket during startup.
    }
    const timer = window.setInterval(() => { void getJob(runId, jobId).then(receive).catch(() => undefined) }, 600)
    void getJob(runId, jobId).then(receive).catch(() => undefined)
    return () => { disposed = true; window.clearInterval(timer); socket?.close() }
  }, [jobId, runId, terminal])

  async function createSource(draft: QuickSourceDraft) {
    setBusy(true)
    setError('')
    try {
      if (!draft.file) throw new Error('Choose a source image first.')
      const uploadId = (await uploadImage(draft.file)).upload_id
      const next = await createQuickSession({
        source_kind: 'upload',
        upload_id: uploadId,
      })
      setSession(next)
      setPixelizeResult(null)
      window.localStorage.setItem('sprite-studio-quick-session', next.session_id)
      setStage('ready')
    } catch (value: unknown) {
      setError(value instanceof Error ? value.message : String(value))
    } finally { setBusy(false) }
  }

  async function runPixelize(options: Record<string, unknown>) {
    if (!session) return
    setBusy(true)
    setError('')
    try {
      const result = await quickPixelize(session.session_id, options)
      setPixelizeResult(result)
      setSession(await getQuickSession(session.session_id))
    } catch (value: unknown) { setError(value instanceof Error ? value.message : String(value))
    } finally { setBusy(false) }
  }

  async function chooseSource(source: 'original' | 'pixelized') {
    if (!session) return
    try { setSession(await selectQuickSource(session.session_id, source)) } catch (value: unknown) { setError(value instanceof Error ? value.message : String(value)) }
  }

  async function startMakeSprite(options: Record<string, unknown>) {
    if (!session) return
    setBusy(true)
    setError('')
    try {
      const result = await makeQuickSprite(session.session_id, options)
      setSession(result.session)
      setRunId(result.run_id)
      setJobId(result.job_id)
      setJob(null)
      setStage('progress')
    } catch (value: unknown) { setError(value instanceof Error ? value.message : String(value))
    } finally { setBusy(false) }
  }

  async function retry() {
    if (!runId || !jobId) return
    setBusy(true)
    setError('')
    try {
      const result = await retryJob(runId, jobId)
      setJobId(result.job_id)
      setJob(null)
      setStage('progress')
    } catch (value: unknown) { setError(value instanceof Error ? value.message : String(value))
    } finally { setBusy(false) }
  }

  function replaceSource() {
    setSession(null)
    setPixelizeResult(null)
    setRunId('')
    setJobId('')
    setJob(null)
    setError('')
    window.localStorage.removeItem('sprite-studio-quick-session')
    setStage('input')
  }

  return <div className="quick-page">
    <section className="quick-hero" aria-labelledby="quick-page-heading"><div><p className="eyebrow">{text.quickGenerate}</p><h2 id="quick-page-heading">{text.sourceToSprite}</h2><p className="muted">{text.sourceDescription}</p></div><button className="secondary-button" type="button" onClick={() => onOpenStudio()}>{text.advancedStudio}</button></section>
    <nav className="quick-stepper" aria-label={text.quickGenerate}>{(['input', 'ready', 'pixelize', 'make', 'progress', 'result'] as Stage[]).map((item, index) => <span className={item === stage ? 'active' : ''} key={item}><b>{index + 1}</b>{item === 'input' ? text.sourceStep : item === 'ready' ? text.readyStep : item === 'pixelize' ? text.pixelizeStep : item === 'make' ? text.makeStep : item === 'progress' ? text.progressStep : text.resultStep}</span>)}</nav>
    {error && <div className="error-box" role="alert">{error}</div>}
    {!session && <SourceInputPanel busy={busy} onSubmit={(draft) => void createSource(draft)} />}
    {session && stage === 'ready' && <SourcePreview session={session} onReplace={replaceSource} onPixelize={() => setStage('pixelize')} onMakeSprite={() => setStage('make')} onSelectSource={(source) => void chooseSource(source)} onOpenStudio={() => onOpenStudio(session.run_id ?? undefined)} />}
    {session && stage === 'pixelize' && <QuickPixelizePanel session={session} result={pixelizeResult} busy={busy} onRun={(options) => void runPixelize(options)} onSelectSource={(source) => void chooseSource(source)} onBack={() => setStage('ready')} />}
    {session && stage === 'make' && <MakeSpritePanel session={session} busy={busy} onSubmit={(options) => void startMakeSprite(options)} onBack={() => setStage('ready')} />}
    {session && stage === 'progress' && <QuickProgress job={job} onRetry={() => void retry()} onChangeSettings={() => setStage('make')} onOpenDetails={() => onOpenStudio(runId)} />}
    {session && stage === 'result' && job?.status === 'succeeded' && <QuickResult runId={runId} job={job} onOpenStudio={() => onOpenStudio(runId)} />}
    <p className="quick-current-stage" aria-live="polite">{text.progress}: <strong>{stageLabel}</strong></p>
  </div>
}
