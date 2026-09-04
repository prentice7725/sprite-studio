import type { BatchStatus, RunSummary } from '../../api'

interface JobDrawerProps {
  open: boolean
  run: RunSummary | null
  states: string[]
  selectedStates: string[]
  status: BatchStatus | null
  jobId: string
  busy: string
  onClose: () => void
  onToggle: (state: string) => void
  onStart: () => void
}

function labelForState(state: string): string {
  return state.replaceAll('_', ' / ')
}

export default function JobDrawer({ open, run, states, selectedStates, status, jobId, busy, onClose, onToggle, onStart }: JobDrawerProps) {
  if (!open) return null
  return <div className="drawer-layer"><button className="drawer-scrim" type="button" aria-label="Close jobs" onClick={onClose} /><aside className="job-drawer" aria-label="Global job drawer"><div className="panel-heading"><div><p className="eyebrow">JOB CENTER</p><h2>Background jobs</h2></div><button className="icon-button" type="button" aria-label="Close jobs" onClick={onClose}>×</button></div>{!run ? <div className="empty-state"><p>Select an asset to start a batch.</p></div> : <><p className="muted">{run.character_id} · {run.preset}</p><fieldset className="check-list"><legend>Batch states</legend>{states.map((state) => <label className="check-row" key={state}><input type="checkbox" checked={selectedStates.includes(state)} onChange={() => onToggle(state)} />{labelForState(state)}<span className="check-detail">{selectedStates.includes(state) ? 'included' : 'skip'}</span></label>)}</fieldset><button className="primary-button" disabled={busy !== '' || !selectedStates.length} type="button" onClick={onStart}>{busy === 'batch' ? 'Starting…' : 'Start batch'}</button>{jobId && <p className="helper">Job ID: <code>{jobId}</code></p>}<div className="job-status-card"><div className="panel-heading"><div><p className="eyebrow">LIVE PROGRESS</p><h3>{status?.status ?? 'Waiting'}</h3></div><strong className="progress-value">{status?.progress_percent?.toFixed(1) ?? '0.0'}%</strong></div><div className="progress-track"><span style={{ width: `${Math.min(100, status?.progress_percent ?? 0)}%` }} /></div>{status ? <><div className="batch-current"><span>Current state</span><strong>{status.current_state ? labelForState(status.current_state) : '—'}</strong><span>Stage</span><strong>{status.current_stage ?? '—'}</strong></div><div className="batch-items">{status.items.map((item) => <div className="batch-item" key={item.state}><div><strong>{labelForState(item.state)}</strong><small>{item.status}</small></div><span className={`status-pill ${item.status.replaceAll(' ', '-')}`}>{item.status}</span></div>)}</div>{status.error && <div className="error-box">{status.error}</div>}</> : <p className="helper">Start a batch to stream generation and deterministic processing progress.</p>}</div></>}</aside></div>
}
