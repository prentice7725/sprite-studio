import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Provider, StaticPreset, StaticProject } from '../../api'
import CanvasViewer from '../workspace/CanvasViewer'
import StaticWrapPreview from './StaticWrapPreview'

export interface StaticCreateDraft {
  projectId: string
  description: string
  provider: Provider
  preset: StaticPreset
  tileable: boolean
  baseImage: File | null
}

interface StaticWorkspaceProps {
  projects: StaticProject[]
  presets: StaticPreset[]
  providerChoices: Provider[]
  selectedProjectId: string
  onProjectChange: (id: string) => void
  onCreate: (draft: StaticCreateDraft) => void
  status: Record<string, string>
  assetName: string
  onAssetChange: (value: string) => void
  prompt: string
  onPromptChange: (value: string) => void
  outputAsset: string
  wrapPreview: string
  wrapReport: Record<string, unknown> | null
  report: string
  busy: string
  onImport: (file: File | null) => void
  onAction: (action: 'generate' | 'refine' | 'cleanup' | 'seam-check' | 'seam-repair' | 'layers-split' | 'layers-cutout' | 'qa' | 'export') => void
}

export default function StaticWorkspace({ projects, presets, providerChoices, selectedProjectId, onProjectChange, onCreate, status, assetName, onAssetChange, prompt, onPromptChange, outputAsset, wrapPreview, wrapReport, report, busy, onImport, onAction }: StaticWorkspaceProps) {
  const [presetId, setPresetId] = useState('')
  const [projectId, setProjectId] = useState('scene-demo')
  const [description, setDescription] = useState('')
  const [provider, setProvider] = useState<Provider>(providerChoices[0] ?? 'grok')
  const [tileable, setTileable] = useState(false)
  const [baseImage, setBaseImage] = useState<File | null>(null)
  const preset = presets.find((item) => item.id === presetId) ?? presets[0] ?? null
  const project = projects.find((item) => item.project_id === selectedProjectId) ?? null

  useEffect(() => {
    if (!preset) return
    setPresetId((current) => current || preset.id)
    setDescription((current) => current || preset.description)
    setTileable(preset.tileable)
  }, [preset])

  useEffect(() => {
    if (providerChoices.length && !providerChoices.includes(provider)) setProvider(providerChoices[0])
  }, [provider, providerChoices])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!preset || !projectId.trim() || !description.trim()) return
    onCreate({ projectId: projectId.trim(), description: description.trim(), provider, preset, tileable, baseImage })
  }

  return <div className="content-grid static-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">STATIC PROJECT</p><h2>Create a scene or tile</h2></div><span className="step-number">S1</span></div><p className="muted">Choose a data-backed static preset. Tile behavior, delivery size, style, and refine settings come from the API contract.</p><form className="form-stack" onSubmit={submit}><label>Project ID<input value={projectId} onChange={(event) => setProjectId(event.target.value)} required /></label><label>Preset<select value={preset?.id ?? ''} onChange={(event) => { setPresetId(event.target.value); const next = presets.find((item) => item.id === event.target.value); if (next) { setDescription(next.description); setTileable(next.tileable) } }} required><option value="" disabled>{presets.length ? 'Select a preset' : 'Loading presets…'}</option>{presets.map((item) => <option key={item.id} value={item.id}>{item.display_name} · {item.asset_type}</option>)}</select></label><label>Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={4} required /></label><div className="form-row"><label>Provider<select value={provider} onChange={(event) => setProvider(event.target.value as Provider)}>{providerChoices.map((item) => <option key={item} value={item}>{item === 'codex' ? 'Codex image_gen' : 'Grok'}</option>)}</select></label><label>Asset type<input value={preset?.asset_type ?? ''} readOnly /></label></div><div className="preset-summary"><span>Style <strong>{preset?.style_profile ?? '—'}</strong></span><span>Export <strong>{preset ? `${preset.export_size[0]} × ${preset.export_size[1]}` : '—'}</strong></span><span>Layers <strong>{preset?.layer_intent ?? '—'}</strong></span></div><label className="check-row"><input type="checkbox" checked={tileable} onChange={(event) => setTileable(event.target.checked)} />Tileable asset</label><label>Base image <span className="optional">optional</span><input type="file" accept="image/*" onChange={(event) => setBaseImage(event.target.files?.[0] ?? null)} /><span className="helper">Upload is staged through the FastAPI upload endpoint.</span></label><button className="primary-button" disabled={busy === 'static-create' || !preset} type="submit">{busy === 'static-create' ? 'Creating…' : 'Create static project'}</button></form></section><section className="panel static-workbench"><div className="panel-heading"><div><p className="eyebrow">STATIC WORKSPACE</p><h2>Canvas + inspector</h2></div><span className="count-badge">{projects.length}</span></div><label>Active static project<select value={selectedProjectId} onChange={(event) => onProjectChange(event.target.value)}><option value="">Select a project</option>{projects.map((item) => <option key={item.project_id} value={item.project_id}>{item.project_id} · {item.asset_type}</option>)}</select></label>{project ? <><div className="stat-grid static-stats"><div className="stat"><span>Type</span><strong>{project.asset_type}</strong></div><div className="stat"><span>Tileable</span><strong>{project.tileable ? 'yes' : 'no'}</strong></div><div className="stat"><span>Export</span><strong>{project.export_size[0]} × {project.export_size[1]}</strong></div><div className="stat"><span>Status</span><strong>{status[assetName] ?? 'not started'}</strong></div></div><label>Asset name<input value={assetName} onChange={(event) => onAssetChange(event.target.value)} /><span className="helper">Use letters, numbers, hyphens, or underscores.</span></label><details className="advanced-options"><summary>Prompt and advanced options</summary><label>Effective prompt<textarea value={prompt} onChange={(event) => onPromptChange(event.target.value)} rows={8} /></label><p className="helper">Keep prompt overrides for deliberate exceptions; the preset remains the source of processing policy.</p></details><div className="button-grid"><button className="primary-button" disabled={busy !== ''} type="button" onClick={() => onAction('generate')}>{busy === 'static-generate' ? 'Generating…' : 'Generate'}</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onImport(null)}>Import image</button><label className="file-button secondary-button">Choose import file<input type="file" accept="image/*" onChange={(event) => onImport(event.target.files?.[0] ?? null)} /></label><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('refine')}>{busy === 'static-refine' ? 'Refining…' : 'Refine'}</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('cleanup')}>Cleanup</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('seam-check')}>Seam check</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('seam-repair')}>Seam repair</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('layers-split')}>Split layers</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('layers-cutout')}>Cutout</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('qa')}>Run QA</button><button className="primary-button" disabled={busy !== ''} type="button" onClick={() => onAction('export')}>{busy === 'static-export' ? 'Exporting…' : 'Export PNG'}</button></div><div className="static-visual-grid"><CanvasViewer src={outputAsset || null} alt={`Static ${assetName} output`} pixelArt={project.asset_type !== 'FLAT_SCENE'} label="Static canvas viewer" /><StaticWrapPreview src={wrapPreview || outputAsset || null} tileable={project.tileable} report={wrapReport} /></div>{report && <details className="report-details"><summary>Latest report</summary><pre className="report-box">{report}</pre></details>}</> : <p className="empty-state">Create or select a static project to open its workspace.</p>}</section></div>
}
