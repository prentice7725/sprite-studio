import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  BatchStatus,
  AnimationQaResponse,
  ReviewData,
  StaticProject,
  StaticQaResponse,
  adoptRepair,
  analyzeRepair,
  composeExport,
  createRun,
  createStaticProject,
  extract,
  generate,
  getCurrentBatch,
  getPrompt,
  getReview,
  getRun,
  getRunStatus,
  GenerateResponse,
  getStaticPrompt,
  getStaticStatus,
  listRuns,
  listProviders,
  listStaticProjects,
  normalize,
  RefineResponse,
  refine,
  runAnimationQa,
  runtimeExport,
  safeRepair,
  decideRepair,
  launchCuration,
  undoRepair,
  unadoptRepair,
  RunDetail,
  RunSummary,
  savePrompt,
  startBatch,
  staticCleanup,
  staticExport,
  staticGenerate,
  staticImport,
  staticLayers,
  staticQa,
  staticRefine,
  staticSeam,
  uploadImage,
  websocketUrl,
} from './api'
import type { Provider, ProviderStatus } from './api'

type Tab = 'project' | 'static' | 'generate' | 'refine' | 'review' | 'qa' | 'export' | 'batch'
type Notice = { kind: 'success' | 'error' | 'info'; text: string }
type StaticAction = 'generate' | 'refine' | 'cleanup' | 'seam-check' | 'seam-repair' | 'layers-split' | 'layers-cutout' | 'qa' | 'export'

const fallbackProviderChoices: Provider[] = ['grok']

function providerLabel(provider: Provider): string {
  return provider === 'codex' ? 'Codex image_gen' : 'Grok'
}

const tabs: Array<{ id: Tab; label: string; hint: string }> = [
  { id: 'project', label: 'Project', hint: 'Create and select runs' },
  { id: 'static', label: 'Static', hint: 'Scene and tile assets' },
  { id: 'generate', label: 'Generate', hint: 'Prompt and raw row' },
  { id: 'refine', label: 'Refine', hint: 'Shared grid and palette' },
  { id: 'review', label: 'Repair', hint: 'Inspect and adopt fixes' },
  { id: 'qa', label: 'QA', hint: 'Animation continuity checks' },
  { id: 'export', label: 'Export', hint: 'Compose and runtime files' },
  { id: 'batch', label: 'Batch', hint: 'Run multiple states' },
]

function labelForState(state: string): string {
  return state.replaceAll('_', ' / ')
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function App() {
  const [tab, setTab] = useState<Tab>('project')
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [selectedRunId, setSelectedRunId] = useState('')
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null)
  const [runStatus, setRunStatus] = useState<Record<string, string>>({})
  const [selectedState, setSelectedState] = useState('')
  const [prompt, setPrompt] = useState('')
  const [promptSource, setPromptSource] = useState<'generated' | 'override' | null>(null)
  const [rawAsset, setRawAsset] = useState('')
  const [refinedAsset, setRefinedAsset] = useState('')
  const [refineSummary, setRefineSummary] = useState('')
  const [review, setReview] = useState<ReviewData | null>(null)
  const [selectedCandidates, setSelectedCandidates] = useState<string[]>([])
  const [animationQa, setAnimationQa] = useState<AnimationQaResponse | null>(null)
  const [exportResult, setExportResult] = useState<{ kind: 'compose' | 'runtime'; manifest_asset: string; atlas_asset?: string; sprite_sheet_asset?: string; size?: [number, number] } | null>(null)
  const [curationUrl, setCurationUrl] = useState('')
  const [staticProjects, setStaticProjects] = useState<StaticProject[]>([])
  const [selectedStaticId, setSelectedStaticId] = useState('')
  const [staticAssetName, setStaticAssetName] = useState('scene')
  const [staticStatus, setStaticStatus] = useState<Record<string, string>>({})
  const [staticPrompt, setStaticPrompt] = useState('')
  const [staticOutput, setStaticOutput] = useState('')
  const [staticReport, setStaticReport] = useState('')
  const [batchStates, setBatchStates] = useState<string[]>([])
  const [batchJobId, setBatchJobId] = useState('')
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [busy, setBusy] = useState('')

  const selectedRun = useMemo(
    () => runs.find((run) => run.run_id === selectedRunId) ?? null,
    [runs, selectedRunId],
  )
  const activeState = selectedRun?.states.includes(selectedState)
    ? selectedState
    : selectedRun?.states[0] ?? ''
  const providerChoices = useMemo<Provider[]>(() => {
    const available = providers.filter((provider) => provider.available).map((provider) => provider.name)
    return available.length ? available : fallbackProviderChoices
  }, [providers])

  async function refreshRuns(preferredRunId?: string) {
    const nextRuns = await listRuns()
    setRuns(nextRuns)
    const nextId = preferredRunId && nextRuns.some((run) => run.run_id === preferredRunId)
      ? preferredRunId
      : selectedRunId && nextRuns.some((run) => run.run_id === selectedRunId)
        ? selectedRunId
        : nextRuns[0]?.run_id ?? ''
    setSelectedRunId(nextId)
  }

  useEffect(() => {
    void refreshRuns().catch((error: unknown) => {
      setNotice({ kind: 'error', text: `API에 연결할 수 없습니다: ${error instanceof Error ? error.message : String(error)}` })
    })
    void listProviders().then(setProviders).catch(() => {
      // Keep Grok as the safe UI fallback while the API is unavailable.
    })
  }, [])

  useEffect(() => {
    void listStaticProjects().then((items) => {
      setStaticProjects(items)
      setSelectedStaticId((current) => current && items.some((item) => item.project_id === current) ? current : items[0]?.project_id ?? '')
    }).catch(() => {
      // Static Mode may have no projects yet; the create form remains usable.
    })
  }, [])

  useEffect(() => {
    if (!selectedStaticId) {
      setStaticStatus({})
      return
    }
    void Promise.all([getStaticStatus(selectedStaticId), getStaticPrompt(selectedStaticId)]).then(([status, promptResult]) => {
      setStaticStatus(status.assets)
      setStaticPrompt(promptResult.prompt)
    }).catch((error: unknown) => {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    })
  }, [selectedStaticId])

  useEffect(() => {
    if (!selectedRunId) {
      setRunDetail(null)
      setRunStatus({})
      return
    }
    let cancelled = false
    void Promise.all([getRun(selectedRunId), getRunStatus(selectedRunId)])
      .then(([detail, status]) => {
        if (cancelled) return
        setRunDetail(detail)
        setRunStatus(status.states)
        setBatchStates(detail.states)
        setSelectedState((current) => detail.states.includes(current) ? current : detail.states[0] ?? '')
      })
      .catch((error: unknown) => {
        if (!cancelled) setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
      })
    return () => { cancelled = true }
  }, [selectedRunId])

  useEffect(() => {
    if (!selectedRunId || !activeState) return
    let cancelled = false
    void getPrompt(selectedRunId, activeState)
      .then((result) => {
        if (cancelled) return
        setPrompt(result.prompt)
        setPromptSource(result.source)
      })
      .catch((error: unknown) => {
        if (!cancelled) setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
      })
    return () => { cancelled = true }
  }, [selectedRunId, activeState])

  useEffect(() => {
    setReview(null)
    setSelectedCandidates([])
    setAnimationQa(null)
    setExportResult(null)
    setCurationUrl('')
  }, [selectedRunId, activeState])

  useEffect(() => {
    if (!batchJobId || !selectedRunId) return
    const socket = new WebSocket(websocketUrl(selectedRunId, batchJobId))
    socket.onopen = () => setNotice({ kind: 'info', text: 'Batch progress stream connected.' })
    socket.onmessage = (event) => {
      try {
        setBatchStatus(JSON.parse(event.data) as BatchStatus)
      } catch {
        setNotice({ kind: 'error', text: 'Batch progress 응답을 해석하지 못했습니다.' })
      }
    }
    socket.onerror = () => setNotice({ kind: 'error', text: 'Batch WebSocket 연결에 실패했습니다.' })
    socket.onclose = () => { /* terminal status is already persisted by the backend */ }
    return () => socket.close()
  }, [batchJobId, selectedRunId])

  function selectRun(runId: string) {
    setSelectedRunId(runId)
    setBatchJobId('')
    setBatchStatus(null)
    setNotice(null)
  }

  async function handleCreateRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const runId = String(form.get('run_id') || '').trim()
    const characterId = String(form.get('character_id') || '').trim()
    const directionList = String(form.get('directions') || '').split(',').map((value) => value.trim()).filter(Boolean)
    const stateList = String(form.get('states') || '').split(',').map((value) => value.trim()).filter(Boolean)
    const provider = String(form.get('provider') || providerChoices[0] || 'grok') as Provider
    const file = (form.get('base_image') as File | null)
    if (!runId || !characterId || !directionList.length || !stateList.length) {
      setNotice({ kind: 'error', text: 'Run ID, Character ID, 방향, 상태를 모두 입력하세요.' })
      return
    }
    setBusy('create')
    setNotice(null)
    try {
      let uploadId: string | undefined
      if (file && file.size > 0) uploadId = (await uploadImage(file)).upload_id
      const states = Object.fromEntries(stateList.map((state) => [state, {
        frames: 4,
        fps: state === 'idle' ? 4 : 8,
        loop: state === 'idle',
        action: state === 'idle' ? 'subtle breathing and blinking' : `${state} action sequence`,
      }]))
      const detail = await createRun({
        run_id: runId,
        character_id: characterId,
        provider,
        preset: 'sword',
        directions: directionList,
        mirrors: { left: 'side' },
        states,
        cell_size: 256,
        runtime_size: 48,
        generation_profile: 'refine_first',
        background_policy: 'auto',
        ...(uploadId ? { base_image_upload_id: uploadId } : {}),
      })
      await refreshRuns(detail.run_id)
      setSelectedRunId(detail.run_id)
      setTab('generate')
      setNotice({ kind: 'success', text: `Run ${detail.run_id} created.` })
      event.currentTarget.reset()
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleGenerate() {
    if (!selectedRunId || !activeState) return
    setBusy('generate')
    setNotice(null)
    try {
      const result: GenerateResponse = await generate(selectedRunId, activeState)
      setRawAsset(result.raw_asset)
      setNotice({ kind: 'success', text: `Generated ${labelForState(activeState)} in ${result.elapsed_seconds.toFixed(1)}s (${formatBytes(result.raw_bytes)}).` })
      await getRunStatus(selectedRunId).then((status) => setRunStatus(status.states))
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleNormalize() {
    if (!selectedRunId || !activeState) return
    setBusy('normalize')
    setNotice(null)
    try {
      const result = await normalize(selectedRunId, activeState)
      setRawAsset(result.output_asset)
      setNotice({ kind: result.result === 'pass' ? 'success' : 'error', text: `Normalize ${result.result}: ${result.valid_subjects}/${result.expected_subjects} subjects valid.` })
      await getRunStatus(selectedRunId).then((status) => setRunStatus(status.states))
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleExtract() {
    if (!selectedRunId || !activeState) return
    setBusy('extract')
    setNotice(null)
    try {
      const result = await extract(selectedRunId, activeState)
      setNotice({ kind: result.exit_code === 0 ? 'success' : 'error', text: result.summary || `Extract exit code ${result.exit_code}.` })
      await getRunStatus(selectedRunId).then((status) => setRunStatus(status.states))
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleRefine() {
    if (!selectedRunId || !activeState) return
    setBusy('refine')
    setNotice(null)
    try {
      const result: RefineResponse = await refine(selectedRunId, activeState)
      setRefinedAsset(result.refined_preview_asset ?? '')
      setRefineSummary(result.summary)
      setNotice({ kind: 'success', text: `Refined ${labelForState(activeState)}.` })
      await getRunStatus(selectedRunId).then((status) => setRunStatus(status.states))
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleSavePrompt() {
    if (!selectedRunId || !activeState || !prompt.trim()) return
    setBusy('prompt')
    try {
      const result = await savePrompt(selectedRunId, activeState, prompt)
      setPrompt(result.prompt)
      setPromptSource(result.source)
      setNotice({ kind: 'success', text: 'Prompt override saved.' })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleStartBatch() {
    if (!selectedRunId || !batchStates.length) return
    setBusy('batch')
    setNotice(null)
    try {
      const result = await startBatch(selectedRunId, {
        states: batchStates,
        normalize: true,
        refine: true,
        repair: false,
        qa: true,
      })
      setBatchJobId(result.job_id)
      setBatchStatus(await getCurrentBatch(selectedRunId))
      setNotice({ kind: 'success', text: `Batch ${result.job_id} started.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleCreateStatic(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const projectId = String(form.get('project_id') || '').trim()
    const description = String(form.get('description') || '').trim()
    const file = form.get('base_image') as File | null
    if (!projectId || !description) {
      setNotice({ kind: 'error', text: 'Static project ID와 설명을 입력하세요.' })
      return
    }
    setBusy('static-create')
    setNotice(null)
    try {
      let uploadId: string | undefined
      if (file && file.size > 0) uploadId = (await uploadImage(file)).upload_id
      const width = Number(form.get('export_width') || 1024)
      const height = Number(form.get('export_height') || 1024)
      const project = await createStaticProject({
        project_id: projectId,
        provider: String(form.get('provider') || 'grok'),
        asset_type: String(form.get('asset_type') || 'PIXEL_SCENE'),
        style_profile: String(form.get('style_profile') || 'pixel_scene'),
        description,
        tileable: form.get('tileable') === 'on',
        export_size: [width, height],
        layer_intent: String(form.get('layer_intent') || 'none'),
        background_policy: 'auto',
        ...(uploadId ? { base_image_upload_id: uploadId } : {}),
      })
      const projects = await listStaticProjects()
      setStaticProjects(projects)
      setSelectedStaticId(project.project_id)
      setNotice({ kind: 'success', text: `Static project ${project.project_id} created.` })
      event.currentTarget.reset()
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleStaticImport(file: File | null) {
    if (!selectedStaticId) return
    if (!file) {
      const picker = document.createElement('input')
      picker.type = 'file'
      picker.accept = 'image/*'
      picker.onchange = () => void handleStaticImport(picker.files?.[0] ?? null)
      picker.click()
      return
    }
    setBusy('static-import')
    setNotice(null)
    try {
      const upload = await uploadImage(file)
      const result = await staticImport(selectedStaticId, { asset: staticAssetName, upload_id: upload.upload_id })
      setStaticOutput(result.out_asset)
      setStaticStatus((await getStaticStatus(selectedStaticId)).assets)
      setNotice({ kind: 'success', text: `Imported ${staticAssetName}.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleStaticAction(action: StaticAction) {
    if (!selectedStaticId) return
    setBusy(`static-${action}`)
    setNotice(null)
    try {
      if (action === 'generate') {
        const result = await staticGenerate(selectedStaticId, { asset: staticAssetName, prompt_override: staticPrompt })
        setStaticOutput(result.out_asset)
        setNotice({ kind: 'success', text: `Generated ${staticAssetName} via ${result.provider}.` })
      } else if (action === 'refine') {
        const result = await staticRefine(selectedStaticId, { asset: staticAssetName, cleanup: true, dither_mode: 'off', fft_candidate_search: true })
        setStaticOutput(result.output_asset)
        setStaticReport(JSON.stringify(result.report, null, 2))
        setNotice({ kind: 'success', text: `Refined ${staticAssetName}.` })
      } else if (action === 'cleanup') {
        const result = await staticCleanup(selectedStaticId, { asset: staticAssetName, orphan_max_area: 2, hole_max_area: 4 })
        setStaticOutput(result.output_asset)
        setStaticReport(JSON.stringify(result.report, null, 2))
        setNotice({ kind: 'success', text: `Cleaned ${staticAssetName}.` })
      } else if (action === 'seam-check' || action === 'seam-repair') {
        const repair = action === 'seam-repair'
        const result = await staticSeam(selectedStaticId, { asset: staticAssetName, repair }, repair)
        setStaticOutput(result.wrap_preview_asset)
        setStaticReport(JSON.stringify(result.report, null, 2))
        setNotice({ kind: 'success', text: `${repair ? 'Seam repair' : 'Seam check'} completed.` })
      } else if (action === 'layers-split' || action === 'layers-cutout') {
        const cutout = action === 'layers-cutout'
        const result = await staticLayers(selectedStaticId, { asset: staticAssetName, cutout }, cutout)
        setStaticOutput(result.layer_assets[0] ?? '')
        setStaticReport(JSON.stringify(result.report, null, 2))
        setNotice({ kind: 'success', text: `${cutout ? 'Cutout' : 'Layer split'} completed.` })
      } else if (action === 'qa') {
        const result: StaticQaResponse = await staticQa(selectedStaticId, staticAssetName)
        setStaticReport(JSON.stringify(result, null, 2))
        setNotice({ kind: result.ok ? 'success' : 'error', text: result.ok ? 'Static QA passed.' : 'Static QA found warnings.' })
      } else {
        const result = await staticExport(selectedStaticId, staticAssetName)
        setStaticOutput(result.export_asset)
        setNotice({ kind: 'success', text: `Exported ${staticAssetName}.` })
      }
      setStaticStatus((await getStaticStatus(selectedStaticId)).assets)
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleReviewAction(action: 'load' | 'analyze' | 'safe' | 'undo' | 'adopt' | 'unadopt' | 'accept' | 'reject') {
    if (!selectedRunId || !activeState) return
    setBusy(`review-${action}`)
    setNotice(null)
    try {
      let result: ReviewData
      if (action === 'load') result = await getReview(selectedRunId, activeState)
      else if (action === 'analyze') result = await analyzeRepair(selectedRunId, activeState)
      else if (action === 'safe') result = await safeRepair(selectedRunId, activeState)
      else if (action === 'undo') result = await undoRepair(selectedRunId, activeState)
      else if (action === 'adopt') result = await adoptRepair(selectedRunId, activeState)
      else if (action === 'unadopt') result = await unadoptRepair(selectedRunId, activeState)
      else result = await decideRepair(selectedRunId, activeState, selectedCandidates, action === 'accept')
      setReview(result)
      setSelectedCandidates([])
      setNotice({ kind: 'success', text: action === 'load' ? 'Review loaded.' : `Repair ${action} completed.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleAnimationQa() {
    if (!selectedRunId || !activeState) return
    setBusy('animation-qa')
    setNotice(null)
    try {
      const result = await runAnimationQa(selectedRunId, activeState)
      setAnimationQa(result)
      setNotice({ kind: result.ok ? 'success' : 'error', text: result.summary })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleCuration() {
    if (!selectedRunId) return
    setBusy('curation')
    setNotice(null)
    try {
      const result = await launchCuration(selectedRunId)
      setCurationUrl(result.url)
      window.open(result.url, '_blank', 'noopener,noreferrer')
      setNotice({ kind: 'success', text: 'Curation workspace opened in a new tab.' })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleExport(kind: 'compose' | 'runtime') {
    if (!selectedRunId) return
    setBusy(`export-${kind}`)
    setNotice(null)
    try {
      const result = kind === 'compose' ? await composeExport(selectedRunId) : await runtimeExport(selectedRunId)
      setExportResult({ kind, ...result })
      setNotice({ kind: 'success', text: `${kind === 'compose' ? 'Compose' : 'Runtime export'} completed.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand-block">
          <span className="brand-mark" aria-hidden="true">SS</span>
          <div>
            <strong>Sprite Studio</strong>
            <span>Asset production workspace</span>
          </div>
        </div>
        <nav className="nav-list">
          {tabs.map((item) => (
            <button
              className={`nav-item ${tab === item.id ? 'active' : ''}`}
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              aria-current={tab === item.id ? 'page' : undefined}
            >
              <span>{item.label}</span>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="status-dot" aria-hidden="true" />
          <div><strong>Migration Phase 6</strong><small>React over FastAPI</small></div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="eyebrow">LOCAL WORKSPACE / {tab.toUpperCase()}</p>
            <h1>{tab === 'project' ? 'Build a new asset run' : tab === 'static' ? 'Build a static scene or tile' : tab === 'generate' ? 'Generate a clean row' : tab === 'refine' ? 'Refine with shared locks' : tab === 'review' ? 'Inspect and repair frames' : tab === 'qa' ? 'Validate animation continuity' : tab === 'export' ? 'Compose a runtime package' : 'Operate a batch run'}</h1>
          </div>
          <div className="run-selector">
            <label htmlFor="global-run">Active run</label>
            <select id="global-run" value={selectedRunId} onChange={(event) => selectRun(event.target.value)}>
              <option value="">Select a run</option>
              {runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id}</option>)}
            </select>
          </div>
        </header>

        {notice && <div className={`notice ${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</div>}

        {tab === 'project' && (
          <div className="content-grid project-grid">
            <section className="panel hero-panel">
              <div className="panel-heading"><div><p className="eyebrow">PROJECT SETUP</p><h2>Create a run</h2></div><span className="step-number">01</span></div>
              <p className="muted">A run owns the numeric request, prompts, raw rows, frames, and reports. The browser only sends API requests.</p>
              <form className="form-stack" onSubmit={handleCreateRun}>
                <div className="form-row">
                  <label>Run ID<input name="run_id" defaultValue="hero-demo" required /></label>
                  <label>Character ID<input name="character_id" defaultValue="hero" required /></label>
                </div>
                <div className="form-row">
                  <label>Provider<select name="provider" defaultValue={providerChoices[0]}>{providerChoices.map((item) => <option key={item} value={item}>{providerLabel(item)}</option>)}</select><span className="helper">Only providers reported as image-generation capable by the API are shown.</span></label>
                  <label>Directions<input name="directions" defaultValue="down,side,up" /></label>
                </div>
                <label>States<input name="states" defaultValue="idle,attack" /><span className="helper">Comma-separated pose names. Each starts as a 4-frame state.</span></label>
                <label>Base image <span className="optional">optional</span><input name="base_image" type="file" accept="image/*" /><span className="helper">Use an existing identity image, or let the run start from text identity.</span></label>
                <button className="primary-button" disabled={busy === 'create'} type="submit">{busy === 'create' ? 'Creating run…' : 'Create run'}</button>
              </form>
            </section>
            <section className="panel">
              <div className="panel-heading"><div><p className="eyebrow">RUN LIBRARY</p><h2>Recent runs</h2></div><span className="count-badge">{runs.length}</span></div>
              {runs.length === 0 ? <EmptyState text="No runs yet. Create one to begin." /> : <div className="run-list">{runs.map((run) => <RunCard key={run.run_id} run={run} selected={run.run_id === selectedRunId} onSelect={() => selectRun(run.run_id)} />)}</div>}
            </section>
            {runDetail && <RunOverview detail={runDetail} status={runStatus} />}
          </div>
        )}

        {tab === 'static' && <StaticPanel projects={staticProjects} providerChoices={providerChoices} selectedProjectId={selectedStaticId} onProjectChange={setSelectedStaticId} onCreate={(event) => void handleCreateStatic(event)} status={staticStatus} assetName={staticAssetName} onAssetChange={setStaticAssetName} prompt={staticPrompt} onPromptChange={setStaticPrompt} outputAsset={staticOutput} report={staticReport} busy={busy} onImport={(file) => void handleStaticImport(file)} onAction={(action) => void handleStaticAction(action)} />}
        {tab === 'generate' && <GeneratePanel run={selectedRun} state={activeState} states={selectedRun?.states ?? []} onStateChange={setSelectedState} prompt={prompt} promptSource={promptSource} onPromptChange={setPrompt} onSavePrompt={() => void handleSavePrompt()} rawAsset={rawAsset} busy={busy} onGenerate={() => void handleGenerate()} onNormalize={() => void handleNormalize()} onExtract={() => void handleExtract()} status={runStatus} />}
        {tab === 'refine' && <RefinePanel run={selectedRun} state={activeState} states={selectedRun?.states ?? []} onStateChange={setSelectedState} busy={busy} onRefine={() => void handleRefine()} previewAsset={refinedAsset} summary={refineSummary} />}
        {tab === 'review' && <ReviewPanel run={selectedRun} state={activeState} states={selectedRun?.states ?? []} onStateChange={setSelectedState} review={review} selectedCandidates={selectedCandidates} onToggleCandidate={(id) => setSelectedCandidates((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])} busy={busy} onAction={(action) => void handleReviewAction(action)} />}
        {tab === 'qa' && <QaPanel run={selectedRun} state={activeState} states={selectedRun?.states ?? []} onStateChange={setSelectedState} result={animationQa} busy={busy} onRun={() => void handleAnimationQa()} />}
        {tab === 'export' && <ExportPanel run={selectedRun} exportResult={exportResult} curationUrl={curationUrl} busy={busy} onCuration={() => void handleCuration()} onExport={(kind) => void handleExport(kind)} />}
        {tab === 'batch' && <BatchPanel run={selectedRun} states={selectedRun?.states ?? []} selectedStates={batchStates} onToggle={(state) => setBatchStates((current) => current.includes(state) ? current.filter((item) => item !== state) : [...current, state])} onStart={() => void handleStartBatch()} busy={busy} status={batchStatus} jobId={batchJobId} />}

      </main>
    </div>
  )
}

function RunCard({ run, selected, onSelect }: { run: RunSummary; selected: boolean; onSelect: () => void }) {
  return <button className={`run-card ${selected ? 'selected' : ''}`} type="button" onClick={onSelect}><span className="run-card-title">{run.run_id}</span><span>{run.character_id} · {run.provider}</span><small>{run.states.length} states · {run.directions.join(', ')}</small></button>
}

function RunOverview({ detail, status }: { detail: RunDetail; status: Record<string, string> }) {
  return <section className="panel overview-panel"><div className="panel-heading"><div><p className="eyebrow">ACTIVE RUN</p><h2>{detail.run_id}</h2></div><span className="mode-badge">{detail.mode}</span></div><div className="stat-grid"><Stat label="Character" value={detail.character_id} /><Stat label="Cell" value={`${detail.cell_size} px`} /><Stat label="Runtime" value={`${detail.runtime_size} px`} /><Stat label="Profile" value={detail.generation_profile} /></div><div className="state-strip">{detail.states.map((state) => <span className="state-chip" key={state}><span className={`mini-status ${status[state] ?? 'not-generated'}`} />{labelForState(state)}<small>{status[state] ?? 'not-generated'}</small></span>)}</div></section>
}

function Stat({ label, value }: { label: string; value: string }) { return <div className="stat"><span>{label}</span><strong>{value}</strong></div> }

function GeneratePanel({ run, state, states, onStateChange, prompt, promptSource, onPromptChange, onSavePrompt, rawAsset, busy, onGenerate, onNormalize, onExtract, status }: { run: RunSummary | null; state: string; states: string[]; onStateChange: (state: string) => void; prompt: string; promptSource: 'generated' | 'override' | null; onPromptChange: (value: string) => void; onSavePrompt: () => void; rawAsset: string; busy: string; onGenerate: () => void; onNormalize: () => void; onExtract: () => void; status: Record<string, string> }) {
  if (!run) return <EmptyState text="Select or create a run in Project first." />
  return <div className="content-grid work-grid"><section className="panel prompt-panel"><div className="panel-heading"><div><p className="eyebrow">STATE INPUT</p><h2>Generate</h2></div><StatusPill value={status[state] ?? 'not-generated'} /></div><label>State<select value={state} onChange={(event) => onStateChange(event.target.value)}>{states.map((item) => <option key={item} value={item}>{labelForState(item)}</option>)}</select></label><div className="prompt-meta"><span>Prompt source: <strong>{promptSource ?? 'loading'}</strong></span><span>Run: <strong>{run.run_id}</strong></span></div><label>Effective prompt<textarea value={prompt} onChange={(event) => onPromptChange(event.target.value)} rows={16} /></label><div className="button-row"><button className="secondary-button" disabled={busy === 'prompt'} type="button" onClick={onSavePrompt}>{busy === 'prompt' ? 'Saving…' : 'Save override'}</button><button className="primary-button" disabled={busy !== ''} type="button" onClick={onGenerate}>{busy === 'generate' ? 'Generating…' : 'Generate row'}</button></div></section><section className="panel output-panel"><div className="panel-heading"><div><p className="eyebrow">PIPELINE OUTPUT</p><h2>Raw → extracted</h2></div><span className="step-number">02</span></div><p className="muted">Generate is provider-backed. Normalize, Extract, and Refine remain deterministic backend stages.</p><div className="pipeline-actions"><PipelineAction label="Generate" state={status[state]} active={busy === 'generate'} onClick={onGenerate} disabled={busy !== ''} /><PipelineAction label="Normalize" state={status[state]} active={busy === 'normalize'} onClick={onNormalize} disabled={busy !== ''} /><PipelineAction label="Extract" state={status[state]} active={busy === 'extract'} onClick={onExtract} disabled={busy !== ''} /></div>{rawAsset ? <div className="asset-preview"><img src={rawAsset} alt={`Generated raw row for ${labelForState(state)}`} /><span>Latest asset preview</span></div> : <EmptyState text="Generate a row to preview the provider output." />}</section></div>
}

function RefinePanel({ run, state, states, onStateChange, busy, onRefine, previewAsset, summary }: { run: RunSummary | null; state: string; states: string[]; onStateChange: (state: string) => void; busy: string; onRefine: () => void; previewAsset: string; summary: string }) {
  if (!run) return <EmptyState text="Select or create a run in Project first." />
  return <div className="content-grid work-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">DETERMINISTIC REFINEMENT</p><h2>Refine state</h2></div><span className="step-number">03</span></div><label>State<select value={state} onChange={(event) => onStateChange(event.target.value)}>{states.map((item) => <option key={item} value={item}>{labelForState(item)}</option>)}</select></label><p className="muted">Refine applies the shared lattice, phase bounds, palette, baseline, scale, and pivot decisions from the existing Studio engine.</p><button className="primary-button" disabled={busy !== ''} type="button" onClick={onRefine}>{busy === 'refine' ? 'Refining…' : 'Run refine'}</button>{summary && <pre className="report-box">{summary}</pre>}</section><section className="panel output-panel"><div className="panel-heading"><div><p className="eyebrow">REFINED PREVIEW</p><h2>{state ? labelForState(state) : 'No state selected'}</h2></div></div>{previewAsset ? <div className="asset-preview refined"><img src={previewAsset} alt={`Refined preview for ${labelForState(state)}`} /><span>Refined preview asset</span></div> : <EmptyState text="Extract the selected state before refining it." />}</section></div>
}

type ReviewAction = 'load' | 'analyze' | 'safe' | 'undo' | 'adopt' | 'unadopt' | 'accept' | 'reject'

function StatePicker({ state, states, onChange }: { state: string; states: string[]; onChange: (state: string) => void }) {
  return <label>State<select value={state} onChange={(event) => onChange(event.target.value)}>{states.map((item) => <option key={item} value={item}>{labelForState(item)}</option>)}</select></label>
}

function StaticPanel({ projects, providerChoices, selectedProjectId, onProjectChange, onCreate, status, assetName, onAssetChange, prompt, onPromptChange, outputAsset, report, busy, onImport, onAction }: { projects: StaticProject[]; providerChoices: Provider[]; selectedProjectId: string; onProjectChange: (id: string) => void; onCreate: (event: FormEvent<HTMLFormElement>) => void; status: Record<string, string>; assetName: string; onAssetChange: (value: string) => void; prompt: string; onPromptChange: (value: string) => void; outputAsset: string; report: string; busy: string; onImport: (file: File | null) => void; onAction: (action: StaticAction) => void }) {
  const project = projects.find((item) => item.project_id === selectedProjectId) ?? null
  const providerOptions = providerChoices.map((item) => <option key={item} value={item}>{providerLabel(item)}</option>)
  return <div className="content-grid static-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">STATIC PROJECT</p><h2>Create a scene or tile</h2></div><span className="step-number">S1</span></div><p className="muted">Static assets use their own project directory and deterministic refine pipeline. No sprite directions or frame manifest are invented.</p><form className="form-stack" onSubmit={onCreate}><label>Project ID<input name="project_id" defaultValue="scene-demo" required /></label><label>Description<textarea name="description" rows={4} defaultValue="A small pixel-art forest clearing with readable flat color regions." required /></label><div className="form-row"><label>Provider<select name="provider" defaultValue={providerChoices[0]}>{providerOptions}</select><span className="helper">Only providers reported as image-generation capable by the API are shown.</span></label><label>Asset type<select name="asset_type" defaultValue="PIXEL_SCENE"><option value="PIXEL_SCENE">Pixel scene</option><option value="TILE_SET">Tile set</option><option value="PROP_OBJECT">Prop object</option><option value="FLAT_SCENE">Flat scene</option></select></label></div><div className="form-row"><label>Style profile<input name="style_profile" defaultValue="pixel_scene" /></label><label>Layer intent<select name="layer_intent" defaultValue="none"><option value="none">No split requested</option><option value="background">Background</option><option value="midground">Midground</option><option value="foreground">Foreground</option></select></label></div><div className="form-row"><label>Export width<input name="export_width" type="number" min="1" defaultValue="1024" /></label><label>Export height<input name="export_height" type="number" min="1" defaultValue="1024" /></label></div><label className="check-row"><input name="tileable" type="checkbox" />Tileable asset</label><label>Base image <span className="optional">optional</span><input name="base_image" type="file" accept="image/*" /><span className="helper">Upload is staged through POST /api/uploads; the browser never passes a filesystem path.</span></label><button className="primary-button" disabled={busy === 'static-create'} type="submit">{busy === 'static-create' ? 'Creating…' : 'Create static project'}</button></form></section><section className="panel static-workbench"><div className="panel-heading"><div><p className="eyebrow">STATIC PIPELINE</p><h2>Generate → refine → deliver</h2></div><span className="count-badge">{projects.length}</span></div><label>Active static project<select value={selectedProjectId} onChange={(event) => onProjectChange(event.target.value)}><option value="">Select a project</option>{projects.map((item) => <option key={item.project_id} value={item.project_id}>{item.project_id} · {item.asset_type}</option>)}</select></label>{project ? <><div className="stat-grid static-stats"><Stat label="Type" value={project.asset_type} /><Stat label="Tileable" value={project.tileable ? 'yes' : 'no'} /><Stat label="Export" value={`${project.export_size[0]} × ${project.export_size[1]}`} /><Stat label="Asset status" value={status[assetName] ?? 'not started'} /></div><label>Asset name<input value={assetName} onChange={(event) => onAssetChange(event.target.value)} /><span className="helper">Use letters, numbers, hyphens, or underscores.</span></label><label>Effective prompt<textarea value={prompt} onChange={(event) => onPromptChange(event.target.value)} rows={8} /></label><div className="button-grid"><button className="primary-button" disabled={busy !== ''} type="button" onClick={() => onAction('generate')}>{busy === 'static-generate' ? 'Generating…' : 'Generate'}</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onImport(null)}>Import image</button><label className="file-button secondary-button">Choose import file<input type="file" accept="image/*" onChange={(event) => onImport(event.target.files?.[0] ?? null)} /></label><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('refine')}>{busy === 'static-refine' ? 'Refining…' : 'Refine'}</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('cleanup')}>Cleanup</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('seam-check')}>Seam check</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('seam-repair')}>Seam repair</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('layers-split')}>Split layers</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('layers-cutout')}>Cutout</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('qa')}>Run QA</button><button className="primary-button" disabled={busy !== ''} type="button" onClick={() => onAction('export')}>{busy === 'static-export' ? 'Exporting…' : 'Export PNG'}</button></div>{outputAsset ? <div className="asset-preview"><img src={outputAsset} alt={`Static ${assetName} output preview`} /><span>Latest static output</span></div> : <EmptyState text="Generate or import an asset to begin the static pipeline." />}{report && <details className="report-details"><summary>Latest report</summary><pre className="report-box">{report}</pre></details>}</> : <EmptyState text="Create or select a static project to open its pipeline." />}</section></div>
}

function AssetStrip({ title, assets, state }: { title: string; assets: string[]; state: string }) {
  return <div className="asset-group"><div className="asset-group-heading"><h3>{title}</h3><span>{assets.length} files</span></div>{assets.length ? <div className="asset-grid">{assets.map((asset, index) => <img key={asset} src={asset} alt={`${title} ${labelForState(state)} frame ${index + 1}`} loading="lazy" />)}</div> : <EmptyState text={`No ${title.toLowerCase()} available yet.`} />}</div>
}

function ReviewPanel({ run, state, states, onStateChange, review, selectedCandidates, onToggleCandidate, busy, onAction }: { run: RunSummary | null; state: string; states: string[]; onStateChange: (state: string) => void; review: ReviewData | null; selectedCandidates: string[]; onToggleCandidate: (id: string) => void; busy: string; onAction: (action: ReviewAction) => void }) {
  if (!run) return <EmptyState text="Select or create a run in Project first." />
  return <div className="content-grid review-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">REPAIR WORKBENCH</p><h2>Review state</h2></div><span className="step-number">04</span></div><StatePicker state={state} states={states} onChange={onStateChange} /><p className="muted">Analyze refined frames first. Safe repair writes derived outputs only; adopt makes them the curation/export source.</p><div className="button-grid"><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('load')}>{busy === 'review-load' ? 'Loading…' : 'Load review'}</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('analyze')}>{busy === 'review-analyze' ? 'Analyzing…' : 'Analyze candidates'}</button><button className="primary-button" disabled={busy !== ''} type="button" onClick={() => onAction('safe')}>{busy === 'review-safe' ? 'Repairing…' : 'Apply safe repair'}</button></div>{review && <><div className="summary-stack"><p>{review.repair_summary}</p><p>{review.qa_summary}</p></div><fieldset className="check-list"><legend>Candidate decisions</legend>{review.repair_candidates.length ? review.repair_candidates.map((id) => <label className="check-row" key={id}><input type="checkbox" checked={selectedCandidates.includes(id)} onChange={() => onToggleCandidate(id)} /><code>{id}</code><span className="check-detail">selected for decision</span></label>) : <p className="helper">No repair candidates returned for this state.</p>}</fieldset><div className="button-grid compact"><button className="secondary-button" disabled={busy !== '' || !selectedCandidates.length} type="button" onClick={() => onAction('accept')}>Accept selected</button><button className="secondary-button danger-button" disabled={busy !== '' || !selectedCandidates.length} type="button" onClick={() => onAction('reject')}>Reject selected</button></div><div className="button-row"><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('adopt')}>Adopt repaired</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('unadopt')}>Use canonical</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('undo')}>Undo repairs</button></div></>}</section><section className="panel review-output"><div className="panel-heading"><div><p className="eyebrow">VISUAL REVIEW</p><h2>{labelForState(state)}</h2></div></div>{review ? <><AssetStrip title="Extracted" assets={review.frames} state={state} /><AssetStrip title="Refined" assets={review.refined_frames} state={state} /><AssetStrip title="Proposals" assets={review.repair_proposals} state={state} /><AssetStrip title="Repaired" assets={review.repaired_frames} state={state} /><AssetStrip title="Diff" assets={review.repair_diff} state={state} /><details className="report-details"><summary>History</summary><pre className="report-box">{review.history_summary}</pre></details></> : <EmptyState text="Load review to compare extracted, refined, proposal, and repaired frames." />}</section></div>
}

function QaPanel({ run, state, states, onStateChange, result, busy, onRun }: { run: RunSummary | null; state: string; states: string[]; onStateChange: (state: string) => void; result: AnimationQaResponse | null; busy: string; onRun: () => void }) {
  if (!run) return <EmptyState text="Select or create a run in Project first." />
  return <div className="content-grid single-grid"><section className="panel qa-panel"><div className="panel-heading"><div><p className="eyebrow">ANIMATION QA</p><h2>Continuity checks</h2></div><span className="step-number">05</span></div><StatePicker state={state} states={states} onChange={onStateChange} /><p className="muted">QA reads refined frames, or the currently adopted repaired frames, through the existing deterministic animation analyzer.</p><button className="primary-button" disabled={busy !== ''} type="button" onClick={onRun}>{busy === 'animation-qa' ? 'Running QA…' : 'Run animation QA'}</button>{result && <div className={`qa-result ${result.ok ? 'pass' : 'fail'}`} role="status"><strong>{result.ok ? 'PASS' : 'ATTENTION REQUIRED'}</strong><p>{result.summary}</p>{result.warnings.length ? <ul>{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : <p className="helper">No continuity warnings.</p>}</div>}</section></div>
}

function ExportPanel({ run, exportResult, curationUrl, busy, onCuration, onExport }: { run: RunSummary | null; exportResult: { kind: 'compose' | 'runtime'; manifest_asset: string; atlas_asset?: string; sprite_sheet_asset?: string; size?: [number, number] } | null; curationUrl: string; busy: string; onCuration: () => void; onExport: (kind: 'compose' | 'runtime') => void }) {
  if (!run) return <EmptyState text="Select or create a run in Project first." />
  return <div className="content-grid single-grid"><section className="panel export-panel"><div className="panel-heading"><div><p className="eyebrow">CURATION / EXPORT</p><h2>Publish runtime assets</h2></div><span className="step-number">06</span></div><p className="muted">Compose creates the canonical atlas and manifest. Runtime export creates a nearest-neighbor fixed-size package for the game runtime.</p><div className="button-row"><button className="secondary-button" disabled={busy !== ''} type="button" onClick={onCuration}>{busy === 'curation' ? 'Opening…' : 'Open curation'}</button><button className="primary-button" disabled={busy !== ''} type="button" onClick={() => onExport('compose')}>{busy === 'export-compose' ? 'Composing…' : 'Compose atlas'}</button><button className="primary-button" disabled={busy !== ''} type="button" onClick={() => onExport('runtime')}>{busy === 'export-runtime' ? 'Exporting…' : 'Runtime export'}</button></div>{curationUrl && <p className="helper">Curation URL: <a href={curationUrl} target="_blank" rel="noreferrer">{curationUrl}</a></p>}{exportResult && <div className="export-result" role="status"><strong>{exportResult.kind === 'compose' ? 'Compose complete' : 'Runtime export complete'}</strong>{exportResult.size && <span>Sheet size: {exportResult.size[0]} × {exportResult.size[1]} px</span>}<a href={exportResult.sprite_sheet_asset ?? exportResult.atlas_asset} target="_blank" rel="noreferrer">Open atlas image</a><a href={exportResult.manifest_asset} target="_blank" rel="noreferrer">Open manifest JSON</a></div>}</section></div>
}

function BatchPanel({ run, states, selectedStates, onToggle, onStart, busy, status, jobId }: { run: RunSummary | null; states: string[]; selectedStates: string[]; onToggle: (state: string) => void; onStart: () => void; busy: string; status: BatchStatus | null; jobId: string }) {
  if (!run) return <EmptyState text="Select or create a run in Project first." />
  return <div className="content-grid batch-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">PERSISTED QUEUE</p><h2>Batch selection</h2></div><span className="mode-badge">WebSocket</span></div><p className="muted">The queue is persisted by the backend. This screen only starts the job and listens for state changes.</p><fieldset className="check-list"><legend>States</legend>{states.map((state) => <label className="check-row" key={state}><input type="checkbox" checked={selectedStates.includes(state)} onChange={() => onToggle(state)} />{labelForState(state)}<span className="check-detail">{selectedStates.includes(state) ? 'included' : 'skip'}</span></label>)}</fieldset><button className="primary-button" disabled={busy !== '' || !selectedStates.length} type="button" onClick={onStart}>{busy === 'batch' ? 'Starting…' : 'Start batch'}</button>{jobId && <p className="helper">Job ID: <code>{jobId}</code></p>}</section><section className="panel batch-status-panel"><div className="panel-heading"><div><p className="eyebrow">LIVE PROGRESS</p><h2>{status?.status ?? 'Waiting'}</h2></div><strong className="progress-value">{status?.progress_percent?.toFixed(1) ?? '0.0'}%</strong></div><div className="progress-track"><span style={{ width: `${Math.min(100, status?.progress_percent ?? 0)}%` }} /></div>{status ? <><div className="batch-current"><span>Current state</span><strong>{status.current_state ? labelForState(status.current_state) : '—'}</strong><span>Stage</span><strong>{status.current_stage ?? '—'}</strong></div><div className="batch-items">{status.items.map((item) => <div className="batch-item" key={item.state}><div><strong>{labelForState(item.state)}</strong><small>{item.status}</small></div><StatusPill value={item.status} /></div>)}</div>{status.error && <div className="error-box">{status.error}</div>}</> : <EmptyState text="Start a batch to stream generation, normalization, extraction, refine, and QA progress." />}</section></div>
}

function PipelineAction({ label, state, active, onClick, disabled }: { label: string; state?: string; active: boolean; onClick: () => void; disabled: boolean }) { return <button className={`pipeline-action ${active ? 'working' : ''}`} type="button" onClick={onClick} disabled={disabled}><span className={`pipeline-indicator ${state ?? 'not-generated'}`} /> <strong>{label}</strong><small>{active ? 'working…' : state ?? 'ready'}</small></button> }
function StatusPill({ value }: { value: string }) { return <span className={`status-pill ${value.replaceAll(' ', '-')}`}>{value}</span> }
function EmptyState({ text }: { text: string }) { return <div className="empty-state"><span className="empty-line" aria-hidden="true" /><p>{text}</p></div> }

export default App
