import type { JobStatus } from '../../api'
import { useQuickText } from './quickText'

export default function QuickProgress({ job, onRetry, onChangeSettings, onOpenDetails }: { job: JobStatus | null; onRetry: () => void; onChangeSettings: () => void; onOpenDetails: () => void }) {
  const text = useQuickText()
  const stage = job?.current_stage?.split(':')[0] ?? 'queued'
  const labels: Record<string, string> = { generate: text.generatingSource, normalize: text.normalizing, extract: text.extractingFrames, refine: text.refiningFrames, animation_qa: text.runningQa, preparing_preview: text.preparingExport, complete: text.complete }
  const label = labels[stage] ?? (job?.status === 'failed' ? text.quickGenerateFailed : text.preparing)
  const failed = job?.status === 'failed' || job?.status === 'interrupted'
  return <section className="panel quick-progress-panel" aria-labelledby="quick-progress-heading" aria-live="polite"><div className="panel-heading"><div><p className="eyebrow">{text.inProgress}</p><h2 id="quick-progress-heading">{label}</h2></div><span className="progress-value">{Math.round(job?.progress_percent ?? 0)}%</span></div><progress max={100} value={job?.progress_percent ?? 0} aria-label={text.progress} /><p className="muted">{failed ? job?.error ?? text.quickGenerateFailed : text.pipelinePersisted}</p><div className="button-row"><button className="secondary-button" type="button" onClick={onOpenDetails}>{text.viewDetails}</button>{failed && <><button className="primary-button" type="button" onClick={onRetry}>{text.retry}</button><button className="secondary-button" type="button" onClick={onChangeSettings}>{text.changeSettings}</button></>}</div></section>
}