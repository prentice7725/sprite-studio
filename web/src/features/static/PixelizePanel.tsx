import { useMemo, useState } from 'react'
import { API_BASE } from '../../api'

type PaletteChoice = 'auto' | 16 | 24 | 32 | 48
type DitherChoice = 'none' | 'ordered-low' | 'ordered'
type BackgroundChoice = 'keep' | 'cleanup'
type OutlineChoice = 'preserve' | 'auto'

interface PixelizeResponse {
  output_asset: string
  preview_asset: string
  palette_asset: string
  profile_asset: string
  report_asset: string
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
  const [size, setSize] = useState(128)
  const [palette, setPalette] = useState<PaletteChoice>(32)
  const [dither, setDither] = useState<DitherChoice>('none')
  const [background, setBackground] = useState<BackgroundChoice>('keep')
  const [outline, setOutline] = useState<OutlineChoice>('preserve')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<PixelizeResponse | null>(null)

  const sourceAsset = useMemo(
    () => `${API_BASE}/static/${encodeURIComponent(projectId)}/assets/raw/${encodeURIComponent(assetName)}.png`,
    [projectId, assetName],
  )

  async function runPixelize() {
    setBusy(true)
    setError('')
    try {
      const response = await fetch(`${API_BASE}/static/${encodeURIComponent(projectId)}/pixelize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset: assetName, size, palette, dither, background, outline }),
      })
      if (!response.ok) {
        let detail = `${response.status} ${response.statusText}`
        try {
          const body = await response.json() as { detail?: string }
          if (body.detail) detail = body.detail
        } catch {
          // Keep the HTTP status if the backend did not return JSON.
        }
        throw new Error(detail)
      }
      setResult(await response.json() as PixelizeResponse)
    } catch (value: unknown) {
      setError(normalizeError(value))
    } finally {
      setBusy(false)
    }
  }

  return <section className="panel pixelize-panel" aria-labelledby="pixelize-heading">
    <div className="panel-heading">
      <div>
        <p className="eyebrow">PIXELIZE M1</p>
        <h3 id="pixelize-heading">Illustration → pixel master</h3>
      </div>
      <span className="mode-badge">M1</span>
    </div>
    <p className="muted">Create a deterministic logical-resolution master before animation. Palette and profile outputs are reusable for later video-frame canonicalization.</p>
    <div className="form-row">
      <label>Logical longest edge
        <select value={size} onChange={(event) => setSize(Number(event.target.value))}>
          {[64, 96, 128, 192].map((value) => <option key={value} value={value}>{value}px</option>)}
        </select>
      </label>
      <label>Palette
        <select value={palette} onChange={(event) => setPalette(event.target.value === 'auto' ? 'auto' : Number(event.target.value) as PaletteChoice)}>
          <option value="auto">Auto</option>
          {[16, 24, 32, 48].map((value) => <option key={value} value={value}>{value} colors</option>)}
        </select>
      </label>
    </div>
    <div className="form-row">
      <label>Dither
        <select value={dither} onChange={(event) => setDither(event.target.value as DitherChoice)}>
          <option value="none">Off</option>
          <option value="ordered-low">Ordered · low</option>
          <option value="ordered">Ordered</option>
        </select>
      </label>
      <label>Outline
        <select value={outline} onChange={(event) => setOutline(event.target.value as OutlineChoice)}>
          <option value="preserve">Preserve</option>
          <option value="auto">Auto</option>
        </select>
      </label>
    </div>
    <label>Background alpha
      <select value={background} onChange={(event) => setBackground(event.target.value as BackgroundChoice)}>
        <option value="keep">Keep source alpha</option>
        <option value="cleanup">Cleanup / binary alpha</option>
      </select>
      <span className="helper">M1 cleanup normalizes an existing alpha mask. It does not guess segmentation from a fully opaque background.</span>
    </label>
    <button className="primary-button" type="button" disabled={disabled || busy || !assetName.trim()} onClick={() => void runPixelize()}>
      {busy ? 'Pixelizing…' : 'Pixelize current raw asset'}
    </button>
    {error && <div className="error-box" role="alert">{error}</div>}
    {result && <div className="pixelize-result" aria-live="polite">
      <div className="stat-grid static-stats">
        <div className="stat"><span>Logical</span><strong>{result.logical_size[0]} × {result.logical_size[1]}</strong></div>
        <div className="stat"><span>Palette</span><strong>{result.palette_size} colors</strong></div>
        <div className="stat"><span>Dither</span><strong>{dither}</strong></div>
        <div className="stat"><span>Outline</span><strong>{outline}</strong></div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12 }}>
        <div className="asset-preview"><img src={sourceAsset} alt={`Original ${assetName} illustration`} /><span>Original</span></div>
        <div className="asset-preview"><img src={result.preview_asset} alt={`Pixelized ${assetName} preview`} style={{ imageRendering: 'pixelated' }} /><span>Pixelized · 4× nearest preview</span></div>
      </div>
      <div>
        <p className="eyebrow">PALETTE</p>
        <div aria-label={`${result.palette_size} color palette`} style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {result.palette.map((entry, index) => <span key={`${entry.join('-')}-${index}`} title={`#${entry.slice(0, 3).map((value) => value.toString(16).padStart(2, '0')).join('').toUpperCase()}`} style={{ width: 22, height: 22, borderRadius: 4, border: '1px solid currentColor', background: `rgb(${entry[0]} ${entry[1]} ${entry[2]})` }} />)}
        </div>
      </div>
      {result.warnings.length > 0 && <div className="notice info" role="status"><strong>Pixelize warnings</strong><ul>{result.warnings.map((warning, index) => <li key={`${warning.code ?? 'warning'}-${index}`}>{warning.message ?? JSON.stringify(warning)}</li>)}</ul></div>}
      <div className="button-row">
        <a className="secondary-button" href={result.output_asset} target="_blank" rel="noreferrer">Open master PNG</a>
        <a className="secondary-button" href={result.profile_asset} target="_blank" rel="noreferrer">Pixel profile</a>
        <a className="secondary-button" href={result.palette_asset} target="_blank" rel="noreferrer">Palette JSON</a>
      </div>
      <details className="report-details"><summary>Pixelize report</summary><pre className="report-box">{JSON.stringify(result.report, null, 2)}</pre></details>
    </div>}
  </section>
}
