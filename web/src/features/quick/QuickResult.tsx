import type { JobStatus } from '../../api'
import { useQuickText } from './quickText'

export default function QuickResult({ runId, job, onOpenStudio }: { runId: string; job: JobStatus; onOpenStudio: () => void }) {
  const text = useQuickText()
  const result = job.result ?? {}
  const preview = String(result.preview_gif_asset ?? '')
  const sheet = String(result.sprite_sheet_asset ?? '')
  const manifest = String(result.manifest_asset ?? '')
  return <section className="panel quick-result-panel" aria-labelledby="quick-result-heading"><div className="panel-heading"><div><p className="eyebrow">{text.result}</p><h2 id="quick-result-heading">{text.spriteReady}</h2></div><span className="mode-badge">{text.complete}</span></div>{preview && <div className="quick-result-preview"><img src={preview} alt={text.downloadGif} /></div>}{sheet && <div className="asset-preview"><img src={sheet} alt={text.downloadPng} className="pixel-art-preview" /><span>{text.downloadPng}</span></div>}<div className="button-row">{sheet && <a className="secondary-button" href={sheet} download>{text.downloadPng}</a>}{preview && <a className="secondary-button" href={preview} download>{text.downloadGif}</a>}{manifest && <a className="secondary-button" href={manifest} download>{text.manifest}</a>}<button className="primary-button" type="button" onClick={onOpenStudio}>{text.openInStudio}</button></div><p className="helper">Run {runId} {text.runAvailable}</p></section>
}