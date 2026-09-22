import { useState } from 'react'
import type { QuickAcceptedArtifact, QuickDither, QuickPalette, QuickPixelSize, QuickSession, QuickSourceSelection, QuickPixelizeResult, QuickOutline, QuickPixelMasterStrategy } from '../../api'
import { useQuickText } from './quickText'

type SubjectMode = 'auto' | 'manual'
type Detail = 'clean' | 'balanced' | 'detailed'

interface Props {
  session: QuickSession
  result: QuickPixelizeResult | null
  busy: boolean
  onRun: (options: Record<string, unknown>) => void
  onSelectSource: (source: QuickSourceSelection) => void
  onBack: () => void
}

export default function QuickPixelizePanel({ session, result, busy, onRun, onSelectSource, onBack }: Props) {
  const text = useQuickText()
  const [strategy, setStrategy] = useState<QuickPixelMasterStrategy>('reference_pixel_master_128')
  const accepted: QuickAcceptedArtifact = 'post'
  const [subjectMode, setSubjectMode] = useState<SubjectMode>('auto')
  const [crop, setCrop] = useState<[number, number, number, number]>([0, 0, 0, 0])
  const [size, setSize] = useState<QuickPixelSize>(128)
  const [detail, setDetail] = useState<Detail>('balanced')
  const [palette, setPalette] = useState<QuickPalette>('auto')
  const [dither, setDither] = useState<QuickDither>('none')
  const [background, setBackground] = useState<'keep' | 'cleanup'>('keep')
  const [outline, setOutline] = useState<QuickOutline>('preserve')
  const [alphaThreshold, setAlphaThreshold] = useState(128)
  const [manifestText, setManifestText] = useState('')
  const [resolutionOverride, setResolutionOverride] = useState<'auto' | 128 | 160 | 192 | 256>('auto')
  const [validation, setValidation] = useState('')

  function setCropValue(index: number, value: string) {
    setCrop((current) => current.map((item, position) => position === index ? Number(value) : item) as [number, number, number, number])
  }

  function run() {
    if (subjectMode === 'manual' && (crop[2] <= crop[0] || crop[3] <= crop[1])) {
      setValidation(`${text.cropRight} > ${text.cropLeft}, ${text.cropBottom} > ${text.cropTop}`)
      return
    }
    let identityManifest: Record<string, unknown> | undefined
    if (strategy === 'identity_preserving_auto') {
      if (!manifestText.trim()) {
        setValidation('Identity Feature Manifest is required for Auto Resolution.')
        return
      }
      try {
        identityManifest = JSON.parse(manifestText) as Record<string, unknown>
      } catch {
        setValidation('Identity Feature Manifest must be valid JSON.')
        return
      }
    }
    setValidation('')
    onRun({ strategy, accepted, size: strategy === 'reference_pixel_master_128' ? 128 : size, detail, palette, dither, background, outline, alpha_threshold: alphaThreshold, subject_mode: subjectMode, ...(subjectMode === 'manual' ? { subject_bbox: crop } : {}), ...(identityManifest ? { identity_manifest: identityManifest, resolution_mode: 'AUTO', ...(resolutionOverride === 'auto' ? {} : { resolution_override: resolutionOverride }) } : {}) })
  }

  const subjectSource = result?.subject_source ?? session.subject_source
  return <section className="panel quick-pixelize-panel" aria-labelledby="quick-pixelize-heading">
    <div className="panel-heading"><div><p className="eyebrow">{text.pixelize}</p><h2 id="quick-pixelize-heading">{text.makePixelMaster}</h2></div><span className="step-number">2A</span></div>
    <p className="muted">{text.pixelizeDescription}</p><fieldset className="choice-group"><legend>Pixel Master strategy</legend><div className="segmented-options" role="group" aria-label="Pixel Master strategy"><button className={strategy === 'reference_pixel_master_128' ? 'active' : ''} type="button" aria-pressed={strategy === 'reference_pixel_master_128'} onClick={() => { setStrategy('reference_pixel_master_128'); setSize(128) }}>Stylize · C2</button><button className={strategy === 'identity_preserving_auto' ? 'active' : ''} type="button" aria-pressed={strategy === 'identity_preserving_auto'} onClick={() => setStrategy('identity_preserving_auto')}>Identity · Auto</button><button className={strategy === 'preserve' ? 'active' : ''} type="button" aria-pressed={strategy === 'preserve'} onClick={() => setStrategy('preserve')}>Preserve</button></div>{strategy === 'reference_pixel_master_128' && <span className="helper">Reference-guided AI pixel-style → 128px redesign. Raw, intermediate, and post artifacts are retained.</span>}{strategy === 'identity_preserving_auto' && <span className="helper">Same semantic redraw is projected at 128/160/192/256; the first identity-preserving height is selected.</span>}</fieldset>
    {strategy === 'identity_preserving_auto' && <fieldset className="choice-group">
      <legend>Identity Feature Manifest</legend>
      <textarea value={manifestText} onChange={(event) => setManifestText(event.target.value)} rows={8} placeholder="Paste IFM JSON here" aria-label="Identity Feature Manifest JSON" />
      <div className="segmented-options" role="group" aria-label="Resolution override">
        <button className={resolutionOverride === 'auto' ? 'active' : ''} type="button" aria-pressed={resolutionOverride === 'auto'} onClick={() => setResolutionOverride('auto')}>Auto</button>
        {([128, 160, 192, 256] as const).map((value) => <button className={resolutionOverride === value ? 'active' : ''} type="button" aria-pressed={resolutionOverride === value} key={value} onClick={() => setResolutionOverride(value)}>{value}px</button>)}
      </div>
      <span className="helper">A forced lower resolution is exported with an identity-preservation warning when its gate fails.</span>
    </fieldset>}
    {strategy === 'reference_pixel_master_128' && <fieldset className="choice-group"><legend>Accepted artifact</legend><span className="helper">Only the validated logical post-cleanup master can be accepted. Transport and intermediate files remain available for audit.</span></fieldset>}
    {strategy === 'preserve' && <fieldset className="choice-group"><legend>{text.chooseSubject}</legend><label className="check-row"><input type="radio" name="quick-subject-mode" checked={subjectMode === 'auto'} onChange={() => setSubjectMode('auto')} /> {text.autoDetect}</label><label className="check-row"><input type="radio" name="quick-subject-mode" checked={subjectMode === 'manual'} onChange={() => setSubjectMode('manual')} /> {text.manualCrop}</label><span className="helper">{text.autoSubjectHint}</span></fieldset>}
    {strategy === 'preserve' && subjectMode === 'manual' && <fieldset className="choice-group"><legend>{text.manualCrop}</legend><div className="form-row"><label>{text.cropLeft}<input type="number" min={0} value={crop[0]} onChange={(event) => setCropValue(0, event.target.value)} /></label><label>{text.cropTop}<input type="number" min={0} value={crop[1]} onChange={(event) => setCropValue(1, event.target.value)} /></label></div><div className="form-row"><label>{text.cropRight}<input type="number" min={1} value={crop[2] || ''} onChange={(event) => setCropValue(2, event.target.value)} required /></label><label>{text.cropBottom}<input type="number" min={1} value={crop[3] || ''} onChange={(event) => setCropValue(3, event.target.value)} required /></label></div></fieldset>}
    {strategy === 'preserve' && <fieldset className="choice-group"><legend>{text.spriteSize}</legend><div className="segmented-options" role="group" aria-label={text.spriteSize}>{[64, 96, 128, 192].map((value) => <button className={size === value ? 'active' : ''} type="button" aria-pressed={size === value} key={value} onClick={() => setSize(value as QuickPixelSize)}>{value}px</button>)}</div><span className="helper">{text.subjectDetected}: {text.spriteSize} means the selected character height.</span></fieldset>}
    {strategy === 'preserve' && <fieldset className="choice-group"><legend>{text.detail}</legend><div className="segmented-options" role="group" aria-label={text.detail}>{(['clean', 'balanced', 'detailed'] as Detail[]).map((value) => <button className={detail === value ? 'active' : ''} type="button" aria-pressed={detail === value} key={value} onClick={() => setDetail(value)}>{text[value]}</button>)}</div></fieldset>}
    <details className="advanced-options"><summary>{text.advancedPixelize}</summary><div className="form-row"><label>{text.palette}<select value={palette} onChange={(event) => setPalette(event.target.value === 'auto' ? 'auto' : Number(event.target.value) as QuickPalette)}><option value="auto">{text.auto}</option><option value={16}>16 {text.colors}</option><option value={24}>24 {text.colors}</option><option value={32}>32 {text.colors}</option><option value={48}>48 {text.colors}</option></select></label>{strategy === 'preserve' && <label>{text.dither}<select value={dither} onChange={(event) => setDither(event.target.value as QuickDither)}><option value="none">{text.none}</option><option value="ordered-low">Ordered · {text.low}</option><option value="ordered">{text.ordered}</option></select></label>}</div>{strategy === 'preserve' && <div className="form-row"><label>{text.backgroundAlpha}<select value={background} onChange={(event) => setBackground(event.target.value as 'keep' | 'cleanup')}><option value="keep">{text.keep}</option><option value="cleanup">{text.cleanup}</option></select></label><label>{text.outline}<select value={outline} onChange={(event) => setOutline(event.target.value as QuickOutline)}><option value="preserve">{text.preserve}</option><option value="auto">{text.auto}</option></select></label></div>}<label>{text.alphaThreshold ?? 'Alpha threshold'}<input type="number" min={1} max={254} value={alphaThreshold} onChange={(event) => setAlphaThreshold(Number(event.target.value))} /></label></details>
    {validation && <div className="error-box" role="alert">{validation}</div>}
    <div className="button-row"><button className="primary-button" type="button" disabled={busy} onClick={run}>{busy ? text.pixelizing : text.pixelizeSource}</button><button className="secondary-button" type="button" onClick={onBack}>{text.back}</button></div>
    {result && <div className="stat-grid static-stats" aria-live="polite"><div className="stat"><span>{text.spriteSize}</span><strong>{result.logical_size[0]} × {result.logical_size[1]}</strong></div><div className="stat"><span>{text.palette}</span><strong>{result.palette_size} {text.colors}</strong></div>{result.resolution && <div className="stat"><span>Identity resolution</span><strong>{String(result.resolution.selected ?? 'NO_VALID_RESOLUTION')}px</strong></div>}</div>}{result?.strategy === 'reference_pixel_master_128' && <div className="button-row"><a className="secondary-button" href={result.raw_source}>C2 raw</a>{result.intermediate_source && <a className="secondary-button" href={result.intermediate_source}>C2 intermediate</a>}<a className="secondary-button" href={result.post_source ?? result.output_source}>C2 post</a></div>}
    {session.pixelized_source && <div className="quick-compare"><div className="asset-preview"><img src={session.original_source} alt={text.originalSource} /><span>{text.originalSource}</span></div>{subjectSource && <div className="asset-preview"><img src={subjectSource} alt={text.compareSubject} /><span>{text.compareSubject}</span></div>}<div className="asset-preview"><img src={session.pixelized_preview ?? session.pixelized_source} alt={text.pixelizedSource} className="pixel-art-preview" /><span>{text.pixelizedSource} · 4×</span></div></div>}
    {session.pixelized_source && <fieldset className="choice-group quick-source-choice"><legend>{text.useForMake}</legend><label className="check-row"><input type="radio" name="quick-pixel-source" checked={session.source_selection === 'original'} onChange={() => onSelectSource('original')} /> {text.originalSource}</label><label className="check-row"><input type="radio" name="quick-pixel-source" checked={session.source_selection === 'pixelized'} onChange={() => onSelectSource('pixelized')} /> {text.pixelizedSource}</label></fieldset>}
    {result?.subject_candidates?.length ? <details className="report-details"><summary>{text.detectedSubjects}</summary><ul>{result.subject_candidates.map((candidate, index) => <li key={index}>{Array.isArray(candidate.bbox) ? candidate.bbox.join(' × ') : text.compareSubject}</li>)}</ul></details> : null}
  </section>
}
