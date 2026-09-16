import { useEffect, useRef, type KeyboardEvent } from 'react'
import type { BatchStatus, JobStatus, RunSummary } from '../../api'

interface JobDrawerProps {
  open: boolean
  run: RunSummary | null
  states: string[]
  selectedStates: string[]
  status: BatchStatus | null
  jobId: string
  activeJob: JobStatus | null
  activeJobId: string
  activeJobRunId: string
  busy: string
  onClose: () => void
  onToggle: (state: string) => void
  onStart: () => void
  onCancelSingle: () => void
  onRetrySingle: () => void
}

function labelForState(state: string): string {
  return state.replaceAll('_', ' / ')
}

function labelForOperation(operation: string): string {
  return operation.replaceAll('_', ' ')
}

function progressValue(value: number | undefined): number {
  return Math.min(100, Math.max(0, value ?? 0))
}

function ProgressTrack({ value, label }: { value: number; label: string }) {
  const bounded = progressValue(value)
  return <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={bounded} aria-label={label}><span style={{ width: `${bounded}%` }} /></div>
}

function SingleJobCard({ job, jobId, runId, onCancel, onRetry }: { job: JobStatus | null; jobId: string; runId: string; onCancel: () => void; onRetry: () => void }) {
  if (!job) return null
  const active = job.status === 'running' || job.status === 'cancel_requested'
  const retryable = job.status === 'failed' || job.status === 'cancelled' || job.status === 'interrupted'
  const progress = progressValue(job.progress_percent)
  return <section className="job-status-card single-job-card" aria-label="Single operation job" aria-busy={active}>
    <div className="panel-heading"><div><p className="eyebrow">SINGLE OPERATION</p><h3>{labelForOperation(job.operation)}</h3></div><strong className="progress-value">{job.progress_percent.toFixed(1)}%</strong></div>
    <p className="helper">Asset {runId}{job.state ? ` · ${labelForState(job.state)}` : ''} · attempt {job.attempt}</p>
    <ProgressTrack value={progress} label={`${labelForOperation(job.operation)} progress`} />
    <div className="batch-current"><span>Status</span><strong>{job.status}</strong><span>Stage</span><strong>{job.current_stage}</strong></div>
    {job.error && <div className="error-box" role="alert">{job.error}</div>}
    <div className="button-row">
      {active && <button className="secondary-button danger-button" type="button" onClick={onCancel}>{job.status === 'cancel_requested' ? 'Cancelling…' : 'Cancel'}</button>}
      {retryable && <button className="secondary-button" type="button" onClick={onRetry}>Retry</button>}
    </div>
    <p className="helper">Job ID: <code>{jobId}</code></p>
  </section>
}

export default function JobDrawer({ open, run, states, selectedStates, status, jobId, activeJob, activeJobId, activeJobRunId, busy, onClose, onToggle, onStart, onCancelSingle, onRetrySingle }: JobDrawerProps) {
  const drawerRef = useRef<HTMLElement | null>(null)
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const restoreFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const timer = window.setTimeout(() => closeRef.current?.focus(), 0)
    return () => {
      window.clearTimeout(timer)
      const previous = restoreFocusRef.current
      restoreFocusRef.current = null
      if (previous && document.contains(previous)) previous.focus()
    }
  }, [open])

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key !== 'Tab' || !drawerRef.current) return
    const focusable = Array.from(drawerRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'))
    if (!focusable.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  if (!open) return null
  const batchProgress = progressValue(status?.progress_percent)
  const singleAnnouncement = activeJob ? `${labelForOperation(activeJob.operation)} ${activeJob.status}, ${progressValue(activeJob.progress_percent).toFixed(0)} percent complete.` : ''
  const batchAnnouncement = status ? `Batch ${status.status}, ${batchProgress.toFixed(0)} percent complete.` : ''
  return <div className="drawer-layer"><button className="drawer-scrim" type="button" aria-label="Close jobs" onClick={onClose} /><aside id="job-drawer" ref={drawerRef} className="job-drawer" role="dialog" aria-modal="true" aria-labelledby="job-drawer-title" onKeyDown={handleKeyDown}>
    <p className="sr-only" aria-live="polite" aria-atomic="true">{[singleAnnouncement, batchAnnouncement].filter(Boolean).join(' ')}</p>
    <div className="panel-heading"><div><p className="eyebrow">JOB CENTER</p><h2 id="job-drawer-title">Background jobs</h2></div><button ref={closeRef} className="icon-button" type="button" aria-label="Close jobs" onClick={onClose}>×</button></div>
    <SingleJobCard job={activeJob} jobId={activeJobId} runId={activeJobRunId} onCancel={onCancelSingle} onRetry={onRetrySingle} />
    {!run ? <div className="empty-state"><p>Select an asset to start a batch.</p></div> : <><p className="muted">{run.character_id} · {run.preset}</p><fieldset className="check-list"><legend>Batch states</legend>{states.map((state) => <label className="check-row" key={state}><input type="checkbox" checked={selectedStates.includes(state)} onChange={() => onToggle(state)} />{labelForState(state)}<span className="check-detail">{selectedStates.includes(state) ? 'included' : 'skip'}</span></label>)}</fieldset><button className="primary-button" disabled={busy !== '' || !selectedStates.length} type="button" onClick={onStart}>{busy === 'batch' ? 'Starting…' : 'Start batch'}</button>{jobId && <p className="helper">Batch ID: <code>{jobId}</code></p>}<div className="job-status-card" aria-busy={status?.status === 'running'}><div className="panel-heading"><div><p className="eyebrow">BATCH PROGRESS</p><h3>{status?.status ?? 'Waiting'}</h3></div><strong className="progress-value">{batchProgress.toFixed(1)}%</strong></div><ProgressTrack value={batchProgress} label="Batch progress" />{status ? <><div className="batch-current"><span>Current state</span><strong>{status.current_state ? labelForState(status.current_state) : '—'}</strong><span>Stage</span><strong>{status.current_stage ?? '—'}</strong></div><div className="batch-items">{status.items.map((item) => <div className="batch-item" key={item.state}><div><strong>{labelForState(item.state)}</strong><small>{item.status}</small></div><span className={`status-pill ${item.status.replaceAll(' ', '-')}`}>{item.status}</span></div>)}</div>{status.error && <div className="error-box" role="alert">{status.error}</div>}</> : <p className="helper">Start a batch to stream generation and deterministic processing progress.</p>}</div></>}
  </aside></div>
}
