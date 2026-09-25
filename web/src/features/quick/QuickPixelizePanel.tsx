import { useState } from 'react'
import { LOGICAL_HEIGHT_OPTIONS } from '../../api'
import type { QuickDither, QuickLogicalHeight, QuickPalette, QuickSession, QuickSourceSelection, QuickPixelizeResult, QuickOutline } from '../../api'
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
  const [subjectMode, setSubjectMode] = useState<SubjectMode>('auto')
  const [crop, setCrop] = useState<[number, number, number, number]>([0, 0, 0, 0])
  const [size, setSize] = useState<QuickLogicalHeight>(128)
  const [detail, setDetail] = useState<Detail>('balanced')
  const [palette, setPalette] = useState<QuickPalette>('auto')
  const [dither, setDither] = useState<QuickDither>('none')
  const [background, setBackground] = useState<'keep' | 'cleanup'>('keep')
  const [outline, setOutline] = useState<QuickOutline>('preserve')
  const [alphaThreshold, setAlphaThreshold] = useState(128)
  const [validation, setValidation] = useState('')

  function setCropValue(index: number, value: string) {
    setCrop((current) => current.map((item, position) => position === index ? Number(value) : item) as [number, number, number, number])
  }

  function run() {
    if (subjectMode === 'manual' && (crop[2] <= crop[0] || crop[3] <= crop[1])) {
      setValidation(`${text.cropRight} > ${text.cropLeft}, ${text.cropBottom} > ${text.cropTop}`)
      return
    }
    setValidation('')
    onRun({ size, detail, palette, dither, background, outline, alpha_threshold: alphaThreshold, subject_mode: subjectMode, ...(subjectMode === 'manual' ? { subject_bbox: crop } : {}) })
  }

  const subjectSource = result?.subject_source ?? session.subject_source
  return <section className="panel quick-pixelize-panel" aria-labelledby="quick-pixelize-heading">
    <div className="panel-heading"><div><p className="eyebrow">{text.pixelize}</p><h2 id="quick-pixelize-heading">{text.makePixelMaster}</h2></div><span className="step-number">2A</span></div>
    <p className="muted">{text.pixelizeDescription}</p>
    <fieldset className="choice-group"><legend>{text.chooseSubject}</legend><label className="check-row"><input type="radio" name="quick-subject-mode" checked={subjectMode === 'auto'} onChange={() => setSubjectMode('auto')} /> {text.autoDetect}</label><label className="check-row"><input type="radio" name="quick-subject-mode" checked={subjectMode === 'manual'} onChange={() => setSubjectMode('manual')} /> {text.manualCrop}</label><span className="helper">{text.autoSubjectHint}</span></fieldset>
    {subjectMode === 'manual' && <fieldset className="choice-group"><legend>{text.manualCrop}</legend><div className="form-row"><label>{text.cropLeft}<input type="number" min={0} value={crop[0]} onChange={(event) => setCropValue(0, event.target.value)} /></label><label>{text.cropTop}<input type="number" min={0} value={crop[1]} onChange={(event) => setCropValue(1, event.target.value)} /></label></div><div className="form-row"><label>{text.cropRight}<input type="number" min={1} value={crop[2] || ''} onChange={(event) => setCropValue(2, event.target.value)} required /></label><label>{text.cropBottom}<input type="number" min={1} value={crop[3] || ''} onChange={(event) => setCropValue(3, event.target.value)} required /></label></div></fieldset>}
    <fieldset className="choice-group"><legend>{text.logicalHeight}</legend><div className="segmented-options" role="group" aria-label={text.logicalHeight}>{LOGICAL_HEIGHT_OPTIONS.map((value) => <button className={size === value ? 'active' : ''} type="button" aria-pressed={size === value} key={value} onClick={() => setSize(value)}>{value}px</button>)}</div></fieldset>
    <fieldset className="choice-group"><legend>{text.detail}</legend><div className="segmented-options" role="group" aria-label={text.detail}>{(['clean', 'balanced', 'detailed'] as Detail[]).map((value) => <button className={detail === value ? 'active' : ''} type="button" aria-pressed={detail === value} key={value} onClick={() => setDetail(value)}>{text[value]}</button>)}</div></fieldset>
    <details className="advanced-options"><summary>{text.advancedPixelize}</summary><div className="form-row"><label>{text.palette}<select value={palette} onChange={(event) => setPalette(event.target.value === 'auto' ? 'auto' : Number(event.target.value) as QuickPalette)}><option value="auto">{text.auto}</option><option value={16}>16 {text.colors}</option><option value={24}>24 {text.colors}</option><option value={32}>32 {text.colors}</option><option value={48}>48 {text.colors}</option></select></label><label>{text.dither}<select value={dither} onChange={(event) => setDither(event.target.value as QuickDither)}><option value="none">{text.none}</option><option value="ordered-low">Ordered · {text.low}</option><option value="ordered">{text.ordered}</option></select></label></div><div className="form-row"><label>{text.backgroundAlpha}<select value={background} onChange={(event) => setBackground(event.target.value as 'keep' | 'cleanup')}><option value="keep">{text.keep}</option><option value="cleanup">{text.cleanup}</option></select></label><label>{text.outline}<select value={outline} onChange={(event) => setOutline(event.target.value as QuickOutline)}><option value="preserve">{text.preserve}</option><option value="auto">{text.auto}</option></select></label></div><label>{text.alphaThreshold ?? 'Alpha threshold'}<input type="number" min={1} max={254} value={alphaThreshold} onChange={(event) => setAlphaThreshold(Number(event.target.value))} /></label></details>
    {validation && <div className="error-box" role="alert">{validation}</div>}
    <div className="button-row"><button className="primary-button" type="button" disabled={busy} onClick={run}>{busy ? text.pixelizing : text.pixelizeSource}</button><button className="secondary-button" type="button" onClick={onBack}>{text.back}</button></div>
    {result && <div className="stat-grid static-stats" aria-live="polite"><div className="stat"><span>{text.logicalSize}</span><strong>{result.logical_size[0]} × {result.logical_size[1]}</strong></div><div className="stat"><span>{text.palette}</span><strong>{result.palette_size} {text.colors}</strong></div></div>}{result?.warnings.map((warning, index) => warning.message ? <div className="helper" role="status" key={`${warning.code ?? 'warning'}-${index}`}>{warning.message}</div> : null)}
    {session.pixelized_source && <div className="quick-compare"><div className="asset-preview"><img src={session.original_source} alt={text.originalSource} /><span>{text.originalSource}</span></div>{subjectSource && <div className="asset-preview"><img src={subjectSource} alt={text.compareSubject} /><span>{text.compareSubject}</span></div>}<div className="asset-preview"><img src={session.pixelized_preview ?? session.pixelized_source} alt={text.pixelizedSource} className="pixel-art-preview" /><span>{text.pixelizedSource} · 4×</span></div></div>}
    {session.pixelized_source && <fieldset className="choice-group quick-source-choice"><legend>{text.useForMake}</legend><label className="check-row"><input type="radio" name="quick-pixel-source" checked={session.source_selection === 'original'} onChange={() => onSelectSource('original')} /> {text.originalSource}</label><label className="check-row"><input type="radio" name="quick-pixel-source" checked={session.source_selection === 'pixelized'} onChange={() => onSelectSource('pixelized')} /> {text.pixelizedSource}</label></fieldset>}
    {result?.subject_candidates?.length ? <details className="report-details"><summary>{text.detectedSubjects}</summary><ul>{result.subject_candidates.map((candidate, index) => <li key={index}>{Array.isArray(candidate.bbox) ? candidate.bbox.join(' × ') : text.compareSubject}</li>)}</ul></details> : null}
  </section>
}
