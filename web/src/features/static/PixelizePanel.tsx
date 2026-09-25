import { useMemo, useState } from 'react'
import { API_BASE, LOGICAL_HEIGHT_OPTIONS } from '../../api'
import { useQuickText } from '../quick/quickText'

type PaletteChoice = 'auto' | 16 | 24 | 32 | 48
type DitherChoice = 'none' | 'ordered-low' | 'ordered'
type BackgroundChoice = 'keep' | 'cleanup'
type OutlineChoice = 'preserve' | 'auto'
type SubjectMode = 'auto' | 'manual'
type Detail = 'clean' | 'balanced' | 'detailed'

interface PixelizeResponse {
  output_asset: string
  preview_asset: string
  subject_asset: string
  palette_asset: string
  profile_asset: string
  report_asset: string
  subject_bbox: [number, number, number, number]
  subject_candidates: Array<Record<string, unknown>>
  logical_size: [number, number]
  palette_size: number
  palette: number[][]
  warnings: Array<{ code?: string; message?: string; [key: string]: unknown }>
  report: Record<string, unknown>
}

interface PixelizePanelProps {
  projectId: string
  assetName: string
  disabled?: boolean
}

function normalizeError(value: unknown): string {
  if (value instanceof Error) return value.message
  return String(value)
}

export default function PixelizePanel({ projectId, assetName, disabled = false }: PixelizePanelProps) {
  const text = useQuickText()
  const [size, setSize] = useState(128)
  const [detail, setDetail] = useState<Detail>('balanced')
  const [subjectMode, setSubjectMode] = useState<SubjectMode>('auto')
  const [crop, setCrop] = useState<[number, number, number, number]>([0, 0, 0, 0])
  const [palette, setPalette] = useState<PaletteChoice>('auto')
  const [dither, setDither] = useState<DitherChoice>('none')
  const [background, setBackground] = useState<BackgroundChoice>('keep')
  const [outline, setOutline] = useState<OutlineChoice>('preserve')
  const [alphaThreshold, setAlphaThreshold] = useState(128)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<PixelizeResponse | null>(null)

  const sourceAsset = useMemo(() => `${API_BASE}/static/${encodeURIComponent(projectId)}/assets/raw/${encodeURIComponent(assetName)}.png`, [projectId, assetName])

  function setCropValue(index: number, value: string) {
    setCrop((current) => current.map((item, position) => position === index ? Number(value) : item) as [number, number, number, number])
  }

  async function runPixelize() {
    if (subjectMode === 'manual' && (crop[2] <= crop[0] || crop[3] <= crop[1])) {
      setError(`${text.cropRight} > ${text.cropLeft}, ${text.cropBottom} > ${text.cropTop}`)
      return
    }
    setBusy(true)
    setError('')
    try {
      const response = await fetch(`${API_BASE}/static/${encodeURIComponent(projectId)}/pixelize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset: assetName, size, detail, subject_mode: subjectMode, ...(subjectMode === 'manual' ? { subject_bbox: crop } : {}), palette, dither, background, outline, alpha_threshold: alphaThreshold }),
      })
      if (!response.ok) {
        let detailText = `${response.status} ${response.statusText}`
        try { const body = await response.json() as { detail?: string }; if (body.detail) detailText = body.detail } catch { /* keep status */ }
        throw new Error(detailText)
      }
      setResult(await response.json() as PixelizeResponse)
    } catch (value: unknown) {
      setError(normalizeError(value))
    } finally {
      setBusy(false)
    }
  }

  return <section className="panel pixelize-panel" aria-labelledby="pixelize-heading">
    <div className="panel-heading"><div><p className="eyebrow">PIXEL MASTER</p><h3 id="pixelize-heading">{text.makePixelMaster}</h3></div><span className="mode-badge">M1.1</span></div>
    <p className="muted">{text.pixelizeDescription}</p>
    <fieldset className="choice-group"><legend>{text.chooseSubject}</legend><label className="check-row"><input type="radio" name="static-subject-mode" checked={subjectMode === 'auto'} onChange={() => setSubjectMode('auto')} /> {text.autoDetect}</label><label className="check-row"><input type="radio" name="static-subject-mode" checked={subjectMode === 'manual'} onChange={() => setSubjectMode('manual')} /> {text.manualCrop}</label><span className="helper">{text.autoSubjectHint}</span></fieldset>
    {subjectMode === 'manual' && <fieldset className="choice-group"><legend>{text.manualCrop}</legend><div className="form-row"><label>{text.cropLeft}<input type="number" min={0} value={crop[0]} onChange={(event) => setCropValue(0, event.target.value)} /></label><label>{text.cropTop}<input type="number" min={0} value={crop[1]} onChange={(event) => setCropValue(1, event.target.value)} /></label></div><div className="form-row"><label>{text.cropRight}<input type="number" min={1} value={crop[2] || ''} onChange={(event) => setCropValue(2, event.target.value)} required /></label><label>{text.cropBottom}<input type="number" min={1} value={crop[3] || ''} onChange={(event) => setCropValue(3, event.target.value)} required /></label></div></fieldset>}
    <fieldset className="choice-group"><legend>{text.logicalHeight}</legend><div className="segmented-options" role="group" aria-label={text.logicalHeight}>{LOGICAL_HEIGHT_OPTIONS.map((value) => <button className={size === value ? 'active' : ''} type="button" aria-pressed={size === value} key={value} onClick={() => setSize(value)}>{value}px</button>)}</div></fieldset>
    <fieldset className="choice-group"><legend>{text.detail}</legend><div className="segmented-options" role="group" aria-label={text.detail}>{(['clean', 'balanced', 'detailed'] as Detail[]).map((value) => <button className={detail === value ? 'active' : ''} type="button" aria-pressed={detail === value} key={value} onClick={() => setDetail(value)}>{text[value]}</button>)}</div></fieldset>
    <details className="advanced-options"><summary>{text.advancedPixelize}</summary><div className="form-row"><label>{text.palette}<select value={palette} onChange={(event) => setPalette(event.target.value === 'auto' ? 'auto' : Number(event.target.value) as PaletteChoice)}><option value="auto">{text.auto}</option>{[16, 24, 32, 48].map((value) => <option key={value} value={value}>{value} {text.colors}</option>)}</select></label><label>{text.dither}<select value={dither} onChange={(event) => setDither(event.target.value as DitherChoice)}><option value="none">{text.none}</option><option value="ordered-low">Ordered · {text.low}</option><option value="ordered">{text.ordered}</option></select></label></div><div className="form-row"><label>{text.backgroundAlpha}<select value={background} onChange={(event) => setBackground(event.target.value as BackgroundChoice)}><option value="keep">{text.keep}</option><option value="cleanup">{text.cleanup}</option></select></label><label>{text.outline}<select value={outline} onChange={(event) => setOutline(event.target.value as OutlineChoice)}><option value="preserve">{text.preserve}</option><option value="auto">{text.auto}</option></select></label></div><label>{text.alphaThreshold}<input type="number" min={1} max={254} value={alphaThreshold} onChange={(event) => setAlphaThreshold(Number(event.target.value))} /></label></details>
    <button className="primary-button" type="button" disabled={disabled || busy || !assetName.trim()} onClick={() => void runPixelize()}>{busy ? text.pixelizing : text.pixelizeSource}</button>
    {error && <div className="error-box" role="alert">{error}</div>}
    {result && <div className="pixelize-result" aria-live="polite"><div className="stat-grid static-stats"><div className="stat"><span>{text.spriteSize}</span><strong>{result.logical_size[0]} × {result.logical_size[1]}</strong></div><div className="stat"><span>{text.palette}</span><strong>{result.palette_size} {text.colors}</strong></div><div className="stat"><span>{text.dither}</span><strong>{dither}</strong></div><div className="stat"><span>{text.outline}</span><strong>{outline}</strong></div></div><div className="quick-compare"><div className="asset-preview"><img src={sourceAsset} alt={`${text.originalSource} ${assetName}`} /><span>{text.originalSource}</span></div><div className="asset-preview"><img src={result.subject_asset} alt={text.compareSubject} /><span>{text.compareSubject}</span></div><div className="asset-preview"><img src={result.preview_asset} alt={text.pixelizedSource} style={{ imageRendering: 'pixelated' }} /><span>{text.pixelizedSource} · 4×</span></div></div><div><p className="eyebrow">{text.palette}</p><div aria-label={`${result.palette_size} ${text.colors}`} style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{result.palette.map((entry, index) => <span key={`${entry.join('-')}-${index}`} title={`#${entry.slice(0, 3).map((value) => value.toString(16).padStart(2, '0')).join('').toUpperCase()}`} style={{ width: 22, height: 22, borderRadius: 4, border: '1px solid currentColor', background: `rgb(${entry[0]} ${entry[1]} ${entry[2]})` }} />)}</div></div>{result.warnings.length > 0 && <div className="notice info" role="status"><strong>{text.quickGenerateFailed}</strong><ul>{result.warnings.map((warning, index) => <li key={`${warning.code ?? 'warning'}-${index}`}>{warning.message ?? JSON.stringify(warning)}</li>)}</ul></div>}<div className="button-row"><a className="secondary-button" href={result.output_asset} target="_blank" rel="noreferrer">{text.pixelizeSource}</a><a className="secondary-button" href={result.profile_asset} target="_blank" rel="noreferrer">Pixel profile</a><a className="secondary-button" href={result.palette_asset} target="_blank" rel="noreferrer">Palette JSON</a></div><details className="report-details"><summary>Pixelize report</summary><pre className="report-box">{JSON.stringify(result.report, null, 2)}</pre></details></div>}
  </section>
}
