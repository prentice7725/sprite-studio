import { useEffect, useMemo, useState } from 'react'
import {
  BatchStatus,
  AnimationQaResponse,
  ReviewData,
  StaticProject,
  StaticPreset,
  StaticQaResponse,
  adoptRepair,
  analyzeRepair,
  composeExport,
  createRun,
  createStaticProject,
  extract,
  generate,
  getCurrentBatch,
  getGenerationStrategy,
  getSequential,
  generateKeyPoses,
  approveKeyPoses,
  generateInbetweens,
  getPrompt,
  getReview,
  getRun,
  getRunStatus,
  getPreset,
  GenerateResponse,
  getStaticPrompt,
  getStaticPreset,
  getStaticStatus,
  listRuns,
  listProviders,
  listPresets,
  listStaticProjects,
  listStaticPresets,
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
  saveGenerationStrategy,
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
import type { Provider, ProviderStatus, SpritePreset } from './api'
import type { GenerationStrategy, MotionPlan, SequentialGenerationResponse } from './api'
import AssetLibrary from './features/assets/AssetLibrary'
import CreateAssetForm, { type CreateAssetDraft } from './features/assets/CreateAssetForm'
import JobDrawer from './features/jobs/JobDrawer'
import { WorkspaceSelectionProvider, useWorkspaceSelection } from './features/workspace/WorkspaceSelectionContext'
import AnimationTimeline from './features/workspace/AnimationTimeline'
import CanvasViewer from './features/workspace/CanvasViewer'
import VariantsPanel from './features/workspace/VariantsPanel'
import StrategyPlanner from './features/workspace/StrategyPlanner'
import StaticWorkspace, { type StaticCreateDraft } from './features/static/StaticWorkspace'
import { useI18n } from './i18n'

type Tab = 'project' | 'static' | 'workspace' | 'jobs'
type WorkspaceTool = 'generate' | 'refine' | 'review' | 'qa' | 'export'
type Notice = { kind: 'success' | 'error' | 'info'; text: string }
type StaticAction = 'generate' | 'refine' | 'cleanup' | 'seam-check' | 'seam-repair' | 'layers-split' | 'layers-cutout' | 'qa' | 'export'

const fallbackProviderChoices: Provider[] = ['grok']

const tabs: Array<{ id: Tab; label: string; hint: string }> = [
  { id: 'project', label: 'Project', hint: 'Create and select assets' },
  { id: 'static', label: 'Static', hint: 'Scene and tile assets' },
  { id: 'workspace', label: 'Workspace', hint: 'Generate, refine, repair, QA' },
  { id: 'jobs', label: 'Jobs', hint: 'Background batch progress' },
]

const workspaceTools: Array<{ id: WorkspaceTool; label: string; hint: string }> = [
  { id: 'generate', label: 'Generate', hint: 'Create a raw row' },
  { id: 'refine', label: 'Refine', hint: 'Apply shared locks' },
  { id: 'review', label: 'Repair', hint: 'Inspect and adopt fixes' },
  { id: 'qa', label: 'QA', hint: 'Check continuity' },
  { id: 'export', label: 'Export', hint: 'Publish runtime files' },
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
  const { t, toggleLocale } = useI18n()
  const [tab, setTab] = useState<Tab>('project')
  const [workspaceTool, setWorkspaceTool] = useState<WorkspaceTool>('generate')
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [presets, setPresets] = useState<SpritePreset[]>([])
  const [selectedRunId, setSelectedRunId] = useState('')
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null)
  const [runStatus, setRunStatus] = useState<Record<string, string>>({})
  const [selectedState, setSelectedState] = useState('')
  const [selectedFrame, setSelectedFrame] = useState(0)
  const [prompt, setPrompt] = useState('')
  const [promptSource, setPromptSource] = useState<'generated' | 'override' | null>(null)
  const [generationStrategy, setGenerationStrategy] = useState<GenerationStrategy>('AUTO')
  const [motionPlan, setMotionPlan] = useState<MotionPlan | null>(null)
  const [sequential, setSequential] = useState<SequentialGenerationResponse | null>(null)
  const [strategyBusy, setStrategyBusy] = useState(false)
  const [sequentialBusy, setSequentialBusy] = useState('')
  const [rawAsset, setRawAsset] = useState('')
  const [refinedAsset, setRefinedAsset] = useState('')
  const [refineSummary, setRefineSummary] = useState('')
  const [review, setReview] = useState<ReviewData | null>(null)
  const [selectedCandidates, setSelectedCandidates] = useState<string[]>([])
  const [animationQa, setAnimationQa] = useState<AnimationQaResponse | null>(null)
  const [exportResult, setExportResult] = useState<{ kind: 'compose' | 'runtime'; manifest_asset: string; atlas_asset?: string; sprite_sheet_asset?: string; size?: [number, number] } | null>(null)
  const [curationUrl, setCurationUrl] = useState('')
  const [staticProjects, setStaticProjects] = useState<StaticProject[]>([])
  const [staticPresets, setStaticPresets] = useState<StaticPreset[]>([])
  const [selectedStaticId, setSelectedStaticId] = useState('')
  const [staticAssetName, setStaticAssetName] = useState('scene')
  const [staticStatus, setStaticStatus] = useState<Record<string, string>>({})
  const [staticPrompt, setStaticPrompt] = useState('')
  const [staticOutput, setStaticOutput] = useState('')
  const [staticWrapPreview, setStaticWrapPreview] = useState('')
  const [staticWrapReport, setStaticWrapReport] = useState<Record<string, unknown> | null>(null)
  const [staticReport, setStaticReport] = useState('')
  const [batchStates, setBatchStates] = useState<string[]>([])
  const [batchJobId, setBatchJobId] = useState('')
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [busy, setBusy] = useState('')
  const [jobDrawerOpen, setJobDrawerOpen] = useState(false)

  const selectedRun = useMemo(
    () => runs.find((run) => run.run_id === selectedRunId) ?? null,
    [runs, selectedRunId],
  )
  const activeState = selectedRun?.states.includes(selectedState)
    ? selectedState
    : selectedRun?.states[0] ?? ''
  const activePreset = presets.find((preset) => preset.id === selectedRun?.preset) ?? null
  const timelineFrames = review?.repaired_frames.length
    ? review.repaired_frames
    : review?.refined_frames.length
      ? review.refined_frames
      : review?.frames ?? []
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
    void listPresets().then((ids) => Promise.all(ids.map(getPreset))).then(setPresets).catch((error: unknown) => {
      setNotice({ kind: 'error', text: `Preset을 불러오지 못했습니다: ${error instanceof Error ? error.message : String(error)}` })
    })
  }, [])

  useEffect(() => {
    void listStaticProjects().then((items) => {
      setStaticProjects(items)
      setSelectedStaticId((current) => current && items.some((item) => item.project_id === current) ? current : items[0]?.project_id ?? '')
    }).catch(() => {
      // Static Mode may have no projects yet; the create form remains usable.
    })
    void listStaticPresets().then((ids) => Promise.all(ids.map(getStaticPreset))).then(setStaticPresets).catch(() => {
      // Static project creation remains available when the preset catalog is unavailable.
    })
  }, [])

  useEffect(() => {
    if (!selectedStaticId) {
      setStaticStatus({})
      setStaticWrapPreview('')
      setStaticWrapReport(null)
      return
    }
    setStaticWrapPreview('')
    setStaticWrapReport(null)
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
    if (!selectedRunId || !activeState) return
    void getGenerationStrategy(selectedRunId, activeState).then((result) => {
      setGenerationStrategy(result.requested)
      setMotionPlan(result.motion_plan)
    }).catch(() => {
      setGenerationStrategy('AUTO')
      setMotionPlan(null)
    })
    void getSequential(selectedRunId, activeState).then(setSequential).catch(() => setSequential(null))
  }, [selectedRunId, activeState])

  useEffect(() => {
    if (!selectedRunId || !activeState) return
    void getReview(selectedRunId, activeState).then(setReview).catch(() => {
      // A newly created state has no review assets yet; the empty timeline is expected.
      setReview(null)
    })
  }, [selectedRunId, activeState])

  useEffect(() => {
    setReview(null)
    setSelectedCandidates([])
    setAnimationQa(null)
    setExportResult(null)
    setCurationUrl('')
    setSelectedFrame(0)
    setGenerationStrategy('AUTO')
    setMotionPlan(null)
    setSequential(null)
  }, [selectedRunId, activeState])

  useEffect(() => {
    if (!selectedRunId) return
    void getCurrentBatch(selectedRunId).then((status) => {
      setBatchStatus(status)
      if (status.job_id) setBatchJobId(status.job_id)
    }).catch(() => {
      // A run without a previous batch is a normal empty state.
    })
  }, [selectedRunId])

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
    setSelectedFrame(0)
    setBatchJobId('')
    setBatchStatus(null)
    setNotice(null)
  }

  async function handleCreateRun(draft: CreateAssetDraft) {
    if (!draft.runId || !draft.characterId || !draft.directions.length || !draft.stateNames.length) {
      setNotice({ kind: 'error', text: 'Asset name, Character identity, 방향, 애니메이션을 모두 입력하세요.' })
      return
    }
    setBusy('create')
    setNotice(null)
    try {
      let uploadId: string | undefined
      if (draft.baseImage && draft.baseImage.size > 0) uploadId = (await uploadImage(draft.baseImage)).upload_id
      const states = Object.fromEntries(draft.stateNames.map((state) => [state, draft.preset.states[state]]))
      const detail = await createRun({
        run_id: draft.runId,
        character_id: draft.characterId,
        provider: draft.provider,
        preset: draft.preset.id,
        directions: draft.directions,
        mirrors: draft.preset.mirror,
        states,
        cell_size: draft.preset.working_cell,
        runtime_size: draft.preset.runtime_cell,
        generation_profile: draft.preset.default_generation_profile,
        background_policy: draft.preset.background_policy,
        locks: draft.preset.locks,
        ...(uploadId ? { base_image_upload_id: uploadId } : {}),
      })
      await refreshRuns(detail.run_id)
      setSelectedRunId(detail.run_id)
      setTab('workspace')
      setWorkspaceTool('generate')
      setNotice({ kind: 'success', text: `Asset ${detail.run_id} created from ${draft.preset.display_name}.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleSaveStrategy() {
    if (!selectedRunId || !activeState) return
    setStrategyBusy(true)
    setNotice(null)
    try {
      const result = await saveGenerationStrategy(selectedRunId, activeState, generationStrategy)
      setMotionPlan(result.motion_plan)
      setNotice({ kind: 'success', text: `${activeState}: ${result.resolved} strategy saved and Motion Plan persisted.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setStrategyBusy(false)
    }
  }

  async function handleSequential(action: 'key-poses' | 'approve' | 'inbetweens', indices: number[] = []) {
    if (!selectedRunId || !activeState) return
    setSequentialBusy(action)
    setNotice(null)
    try {
      const result = action === 'key-poses'
        ? await generateKeyPoses(selectedRunId, activeState)
        : action === 'approve'
          ? await approveKeyPoses(selectedRunId, activeState, indices)
          : await generateInbetweens(selectedRunId, activeState)
      setSequential(result)
      setMotionPlan(result.motion_plan)
      setNotice({ kind: 'success', text: `${activeState}: ${action === 'key-poses' ? 'key poses generated' : action === 'approve' ? 'key poses approved' : 'bidirectional inbetweens generated'}.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setSequentialBusy('')
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
      setJobDrawerOpen(true)
      setNotice({ kind: 'success', text: `Batch ${result.job_id} started.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleCreateStatic(draft: StaticCreateDraft) {
    if (!draft.projectId || !draft.description) {
      setNotice({ kind: 'error', text: 'Static project ID와 설명을 입력하세요.' })
      return
    }
    setBusy('static-create')
    setNotice(null)
    try {
      let uploadId: string | undefined
      if (draft.baseImage && draft.baseImage.size > 0) uploadId = (await uploadImage(draft.baseImage)).upload_id
      const project = await createStaticProject({
        project_id: draft.projectId,
        provider: draft.provider,
        asset_type: draft.preset.asset_type,
        style_profile: draft.preset.style_profile,
        description: draft.description,
        tileable: draft.tileable,
        export_size: draft.preset.export_size,
        layer_intent: draft.preset.layer_intent,
        background_policy: draft.preset.background_policy,
        ...(uploadId ? { base_image_upload_id: uploadId } : {}),
      })
      const projects = await listStaticProjects()
      setStaticProjects(projects)
      setSelectedStaticId(project.project_id)
      setNotice({ kind: 'success', text: `Static project ${project.project_id} created.` })
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
        const result = await staticRefine(selectedStaticId, { asset: staticAssetName })
        setStaticOutput(result.output_asset)
        setStaticReport(JSON.stringify(result.report, null, 2))
        setNotice({ kind: 'success', text: `Refined ${staticAssetName}.` })
      } else if (action === 'cleanup') {
        const result = await staticCleanup(selectedStaticId, { asset: staticAssetName })
        setStaticOutput(result.output_asset)
        setStaticReport(JSON.stringify(result.report, null, 2))
        setNotice({ kind: 'success', text: `Cleaned ${staticAssetName}.` })
      } else if (action === 'seam-check' || action === 'seam-repair') {
        const repair = action === 'seam-repair'
        const result = await staticSeam(selectedStaticId, { asset: staticAssetName, repair }, repair)
        setStaticOutput(result.wrap_preview_asset)
        setStaticWrapPreview(result.wrap_preview_asset)
        setStaticWrapReport(result.report)
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
    <WorkspaceSelectionProvider runs={runs} activeAssetId={selectedRunId} activeState={activeState} activeFrame={selectedFrame} onAssetChange={selectRun} onStateChange={setSelectedState} onFrameChange={setSelectedFrame}>
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
              onClick={() => { setTab(item.id); if (item.id === 'jobs') setJobDrawerOpen(true); else setJobDrawerOpen(false) }}
              aria-current={tab === item.id ? 'page' : undefined}
            >
              <span>{t(item.id)}</span>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>
        <AssetLibrary runs={runs} />
        <div className="sidebar-footer">
          <span className="status-dot" aria-hidden="true" />
          <div><strong>Migration Phase 6</strong><small>React over FastAPI</small></div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="eyebrow">LOCAL WORKSPACE / {tab === 'workspace' ? workspaceTool.toUpperCase() : tab.toUpperCase()}</p>
            <h1>{tab === 'project' ? t('createAsset') : tab === 'static' ? t('buildStatic') : tab === 'workspace' ? workspaceTools.find((tool) => tool.id === workspaceTool)?.hint ?? 'Work on the active asset' : t('backgroundJobs')}</h1>
          </div>
          <div className="topbar-actions">
          <div className="run-selector">
            <label htmlFor="global-run">{t('activeAsset')}</label>
            <select id="global-run" value={selectedRunId} onChange={(event) => selectRun(event.target.value)}>
              <option value="">{t('selectAsset')}</option>
              {runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.character_id} · {run.preset}</option>)}
            </select>
          </div>
          {selectedRun && <span className="selection-chip">{activeState || 'No state'} · Frame {selectedFrame + 1}</span>}
          <button className="tool-button text-button locale-toggle" type="button" onClick={toggleLocale}>{t('language')}</button>
          <button className="job-trigger" type="button" onClick={() => setJobDrawerOpen(true)} aria-expanded={jobDrawerOpen}>Jobs{batchStatus?.status === 'running' ? <span className="status-dot" aria-label="running" /> : null}</button>
          </div>
        </header>

        {notice && <div className={`notice ${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</div>}

        {tab === 'project' && (
          <div className="content-grid project-grid">
            <CreateAssetForm presets={presets} providerChoices={providerChoices} busy={busy === 'create'} onSubmit={(draft) => void handleCreateRun(draft)} />
            <section className="panel">
              <div className="panel-heading"><div><p className="eyebrow">ASSET OVERVIEW</p><h2>Recent assets</h2></div><span className="count-badge">{runs.length}</span></div>
              {runs.length === 0 ? <EmptyState text="No assets yet. Create one from a preset to begin." /> : <div className="run-list">{runs.map((run) => <RunCard key={run.run_id} run={run} selected={run.run_id === selectedRunId} onSelect={() => selectRun(run.run_id)} />)}</div>}
            </section>
            {runDetail && <AssetFacade detail={runDetail} status={runStatus} />}
          </div>
        )}

        {tab === 'static' && <StaticWorkspace projects={staticProjects} presets={staticPresets} providerChoices={providerChoices} selectedProjectId={selectedStaticId} onProjectChange={setSelectedStaticId} onCreate={(draft) => void handleCreateStatic(draft)} status={staticStatus} assetName={staticAssetName} onAssetChange={setStaticAssetName} prompt={staticPrompt} onPromptChange={setStaticPrompt} outputAsset={staticOutput} wrapPreview={staticWrapPreview} wrapReport={staticWrapReport} report={staticReport} busy={busy} onImport={(file) => void handleStaticImport(file)} onAction={(action) => void handleStaticAction(action)} />}
        {tab === 'workspace' && <><div className="workspace-tools" aria-label="Asset tools">{workspaceTools.map((tool) => <button className={`workspace-tool ${workspaceTool === tool.id ? 'active' : ''}`} type="button" key={tool.id} onClick={() => setWorkspaceTool(tool.id)}><strong>{tool.label}</strong><small>{tool.hint}</small></button>)}</div>{workspaceTool === 'generate' && <GeneratePanel run={selectedRun} state={activeState} states={selectedRun?.states ?? []} prompt={prompt} promptSource={promptSource} onPromptChange={setPrompt} onSavePrompt={() => void handleSavePrompt()} rawAsset={rawAsset} busy={busy} onGenerate={() => void handleGenerate()} onNormalize={() => void handleNormalize()} onExtract={() => void handleExtract()} status={runStatus} />}{workspaceTool === 'refine' && <RefinePanel run={selectedRun} state={activeState} states={selectedRun?.states ?? []} busy={busy} onRefine={() => void handleRefine()} previewAsset={refinedAsset} summary={refineSummary} />}{workspaceTool === 'review' && <ReviewPanel run={selectedRun} state={activeState} states={selectedRun?.states ?? []} review={review} selectedCandidates={selectedCandidates} onToggleCandidate={(id) => setSelectedCandidates((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])} busy={busy} onAction={(action) => void handleReviewAction(action)} />}{workspaceTool === 'qa' && <QaPanel run={selectedRun} states={selectedRun?.states ?? []} result={animationQa} busy={busy} onRun={() => void handleAnimationQa()} />}{workspaceTool === 'export' && <ExportPanel run={selectedRun} exportResult={exportResult} curationUrl={curationUrl} busy={busy} onCuration={() => void handleCuration()} onExport={(kind) => void handleExport(kind)} />}</>}
        {tab === 'workspace' && <WorkspaceContextPanel frames={timelineFrames} activeFrame={selectedFrame} fps={activePreset?.states[activeState]?.fps ?? 8} loop={activePreset?.states[activeState]?.loop ?? true} repairedFrames={review?.repaired_frames} rawAsset={rawAsset} state={activeState} onFrameChange={setSelectedFrame} />}
        {tab === 'workspace' && workspaceTool === 'generate' && <StrategyPlanner value={generationStrategy} plan={motionPlan} sequential={sequential} busy={strategyBusy} sequentialBusy={sequentialBusy} onChange={setGenerationStrategy} onSave={() => void handleSaveStrategy()} onGenerateKeyPoses={() => void handleSequential('key-poses')} onApproveKeyPoses={(indices) => void handleSequential('approve', indices)} onGenerateInbetweens={() => void handleSequential('inbetweens')} />}
        {tab === 'workspace' && workspaceTool === 'review' && <VariantsPanel review={review} />}
        {tab === 'jobs' && <section className="panel jobs-page"><p className="eyebrow">GLOBAL JOB CENTER</p><h2>Batch jobs stay available while you work on an asset.</h2><p className="muted">Use the Jobs button in the top bar to open the drawer without leaving the current workspace.</p><button className="primary-button" type="button" onClick={() => setJobDrawerOpen(true)}>Open job drawer</button></section>}

      </main>
      <JobDrawer open={jobDrawerOpen} run={selectedRun} states={selectedRun?.states ?? []} selectedStates={batchStates} status={batchStatus} jobId={batchJobId} busy={busy} onClose={() => setJobDrawerOpen(false)} onToggle={(state) => setBatchStates((current) => current.includes(state) ? current.filter((item) => item !== state) : [...current, state])} onStart={() => void handleStartBatch()} />
    </div>
    </WorkspaceSelectionProvider>
  )
}

function WorkspaceContextPanel({ frames, activeFrame, fps, loop, repairedFrames, rawAsset, state, onFrameChange }: { frames: string[]; activeFrame: number; fps: number; loop: boolean; repairedFrames?: string[]; rawAsset: string; state: string; onFrameChange: (index: number) => void }) {
  return <section className="workspace-context"><CanvasViewer src={(frames[activeFrame] ?? rawAsset) || null} alt={`${state || 'Active'} frame ${activeFrame + 1}`} label="Animation canvas viewer" /><AnimationTimeline frames={frames} activeFrame={activeFrame} fps={fps} loop={loop} repairedFrames={repairedFrames} onFrameChange={onFrameChange} /></section>
}

function RunCard({ run, selected, onSelect }: { run: RunSummary; selected: boolean; onSelect: () => void }) {
  return <button className={`run-card ${selected ? 'selected' : ''}`} type="button" onClick={onSelect}><span className="run-card-title">{run.run_id}</span><span>{run.character_id} · {run.provider}</span><small>{run.states.length} states · {run.directions.join(', ')}</small></button>
}

function AssetFacade({ detail, status }: { detail: RunDetail; status: Record<string, string> }) {
  const selection = useWorkspaceSelection()
  return <section className="panel overview-panel"><div className="panel-heading"><div><p className="eyebrow">ACTIVE ASSET</p><h2>{detail.character_id}</h2></div><span className="mode-badge">{detail.preset}</span></div><div className="stat-grid"><Stat label="Asset ID" value={detail.run_id} /><Stat label="Cell" value={`${detail.cell_size} px`} /><Stat label="Runtime" value={`${detail.runtime_size} px`} /><Stat label="Profile" value={detail.generation_profile} /></div><div className="state-strip">{detail.states.map((state) => <button className={`state-chip ${selection.activeState === state ? 'selected' : ''}`} type="button" key={state} onClick={() => { selection.setActiveAsset(detail.run_id); selection.setActiveState(state) }}><span className={`mini-status ${status[state] ?? 'not-generated'}`} />{labelForState(state)}<small>{status[state] ?? 'not-generated'}</small></button>)}</div></section>
}

function Stat({ label, value }: { label: string; value: string }) { return <div className="stat"><span>{label}</span><strong>{value}</strong></div> }

function GeneratePanel({ run, state, states, prompt, promptSource, onPromptChange, onSavePrompt, rawAsset, busy, onGenerate, onNormalize, onExtract, status }: { run: RunSummary | null; state: string; states: string[]; prompt: string; promptSource: 'generated' | 'override' | null; onPromptChange: (value: string) => void; onSavePrompt: () => void; rawAsset: string; busy: string; onGenerate: () => void; onNormalize: () => void; onExtract: () => void; status: Record<string, string> }) {
  if (!run) return <EmptyState text="Select or create an asset in Project first." />
  return <div className="content-grid work-grid"><section className="panel prompt-panel"><div className="panel-heading"><div><p className="eyebrow">STATE INPUT</p><h2>Generate</h2></div><StatusPill value={status[state] ?? 'not-generated'} /></div><StatePicker states={states} /><div className="prompt-meta"><span>Prompt source: <strong>{promptSource ?? 'loading'}</strong></span><span>Asset: <strong>{run.character_id}</strong></span></div><div className="prompt-preview"><span>Effective prompt</span><p>{prompt || 'Loading the server-assembled prompt…'}</p></div><details className="advanced-options" open={promptSource === 'override'}><summary>Edit prompt override</summary><div className="form-stack compact-stack"><label>Override prompt<textarea value={prompt} onChange={(event) => onPromptChange(event.target.value)} rows={12} /><span className="helper">Use this only for deliberate exceptions. Reset is handled by the server contract.</span></label><button className="secondary-button" disabled={busy === 'prompt' || !prompt.trim()} type="button" onClick={onSavePrompt}>{busy === 'prompt' ? 'Saving…' : 'Save override'}</button></div></details><button className="primary-button" disabled={busy !== ''} type="button" onClick={onGenerate}>{busy === 'generate' ? 'Generating…' : 'Generate row'}</button></section><section className="panel output-panel"><div className="panel-heading"><div><p className="eyebrow">PIPELINE OUTPUT</p><h2>Raw → extracted</h2></div><span className="step-number">02</span></div><p className="muted">Generate is provider-backed. Normalize, Extract, and Refine remain deterministic backend stages.</p><div className="pipeline-actions"><PipelineAction label="Generate" state={status[state]} active={busy === 'generate'} onClick={onGenerate} disabled={busy !== ''} /><PipelineAction label="Normalize" state={status[state]} active={busy === 'normalize'} onClick={onNormalize} disabled={busy !== ''} /><PipelineAction label="Extract" state={status[state]} active={busy === 'extract'} onClick={onExtract} disabled={busy !== ''} /></div>{rawAsset ? <div className="asset-preview"><img src={rawAsset} alt={`Generated raw row for ${labelForState(state)}`} /><span>Latest asset preview</span></div> : <EmptyState text="Generate a row to preview the provider output." />}</section></div>
}
function RefinePanel({ run, state, states, busy, onRefine, previewAsset, summary }: { run: RunSummary | null; state: string; states: string[]; busy: string; onRefine: () => void; previewAsset: string; summary: string }) {
  if (!run) return <EmptyState text="Select or create a run in Project first." />
  return <div className="content-grid work-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">DETERMINISTIC REFINEMENT</p><h2>Refine state</h2></div><span className="step-number">03</span></div><StatePicker states={states} /><p className="muted">Refine applies the shared lattice, phase bounds, palette, baseline, scale, and pivot decisions from the existing Studio engine.</p><button className="primary-button" disabled={busy !== ''} type="button" onClick={onRefine}>{busy === 'refine' ? 'Refining…' : 'Run refine'}</button>{summary && <pre className="report-box">{summary}</pre>}</section><section className="panel output-panel"><div className="panel-heading"><div><p className="eyebrow">REFINED PREVIEW</p><h2>{state ? labelForState(state) : 'No state selected'}</h2></div></div>{previewAsset ? <div className="asset-preview refined"><img src={previewAsset} alt={`Refined preview for ${labelForState(state)}`} /><span>Refined preview asset</span></div> : <EmptyState text="Extract the selected state before refining it." />}</section></div>
}

type ReviewAction = 'load' | 'analyze' | 'safe' | 'undo' | 'adopt' | 'unadopt' | 'accept' | 'reject'

function StatePicker({ states }: { states: string[] }) {
  const selection = useWorkspaceSelection()
  return <label>State<select value={selection.activeState} onChange={(event) => selection.setActiveState(event.target.value)}>{states.map((item) => <option key={item} value={item}>{labelForState(item)}</option>)}</select></label>
}

function AssetStrip({ title, assets, state }: { title: string; assets: string[]; state: string }) {
  return <div className="asset-group"><div className="asset-group-heading"><h3>{title}</h3><span>{assets.length} files</span></div>{assets.length ? <div className="asset-grid">{assets.map((asset, index) => <img key={asset} src={asset} alt={`${title} ${labelForState(state)} frame ${index + 1}`} loading="lazy" />)}</div> : <EmptyState text={`No ${title.toLowerCase()} available yet.`} />}</div>
}

function ReviewPanel({ run, state, states, review, selectedCandidates, onToggleCandidate, busy, onAction }: { run: RunSummary | null; state: string; states: string[]; review: ReviewData | null; selectedCandidates: string[]; onToggleCandidate: (id: string) => void; busy: string; onAction: (action: ReviewAction) => void }) {
  if (!run) return <EmptyState text="Select or create a run in Project first." />
  return <div className="content-grid review-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">REPAIR WORKBENCH</p><h2>Review state</h2></div><span className="step-number">04</span></div><StatePicker states={states} /><p className="muted">Analyze refined frames first. Safe repair writes derived outputs only; adopt makes them the curation/export source.</p><div className="button-grid"><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('load')}>{busy === 'review-load' ? 'Loading…' : 'Load review'}</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('analyze')}>{busy === 'review-analyze' ? 'Analyzing…' : 'Analyze candidates'}</button><button className="primary-button" disabled={busy !== ''} type="button" onClick={() => onAction('safe')}>{busy === 'review-safe' ? 'Repairing…' : 'Apply safe repair'}</button></div>{review && <><div className="summary-stack"><p>{review.repair_summary}</p><p>{review.qa_summary}</p></div><fieldset className="check-list"><legend>Candidate decisions</legend>{review.repair_candidates.length ? review.repair_candidates.map((id) => <label className="check-row" key={id}><input type="checkbox" checked={selectedCandidates.includes(id)} onChange={() => onToggleCandidate(id)} /><code>{id}</code><span className="check-detail">selected for decision</span></label>) : <p className="helper">No repair candidates returned for this state.</p>}</fieldset><div className="button-grid compact"><button className="secondary-button" disabled={busy !== '' || !selectedCandidates.length} type="button" onClick={() => onAction('accept')}>Accept selected</button><button className="secondary-button danger-button" disabled={busy !== '' || !selectedCandidates.length} type="button" onClick={() => onAction('reject')}>Reject selected</button></div><div className="button-row"><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('adopt')}>Adopt repaired</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('unadopt')}>Use canonical</button><button className="secondary-button" disabled={busy !== ''} type="button" onClick={() => onAction('undo')}>Undo repairs</button></div></>}</section><section className="panel review-output"><div className="panel-heading"><div><p className="eyebrow">VISUAL REVIEW</p><h2>{labelForState(state)}</h2></div></div>{review ? <><AssetStrip title="Extracted" assets={review.frames} state={state} /><AssetStrip title="Refined" assets={review.refined_frames} state={state} /><AssetStrip title="Proposals" assets={review.repair_proposals} state={state} /><AssetStrip title="Repaired" assets={review.repaired_frames} state={state} /><AssetStrip title="Diff" assets={review.repair_diff} state={state} /><details className="report-details"><summary>History</summary><pre className="report-box">{review.history_summary}</pre></details></> : <EmptyState text="Load review to compare extracted, refined, proposal, and repaired frames." />}</section></div>
}

function QaPanel({ run, states, result, busy, onRun }: { run: RunSummary | null; states: string[]; result: AnimationQaResponse | null; busy: string; onRun: () => void }) {
  if (!run) return <EmptyState text="Select or create a run in Project first." />
  return <div className="content-grid single-grid"><section className="panel qa-panel"><div className="panel-heading"><div><p className="eyebrow">ANIMATION QA</p><h2>Continuity checks</h2></div><span className="step-number">05</span></div><StatePicker states={states} /><p className="muted">QA reads refined frames, or the currently adopted repaired frames, through the existing deterministic animation analyzer.</p><button className="primary-button" disabled={busy !== ''} type="button" onClick={onRun}>{busy === 'animation-qa' ? 'Running QA…' : 'Run animation QA'}</button>{result && <div className={`qa-result ${result.ok ? 'pass' : 'fail'}`} role="status"><strong>{result.ok ? 'PASS' : 'ATTENTION REQUIRED'}</strong><p>{result.summary}</p>{result.warnings.length ? <ul>{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : <p className="helper">No continuity warnings.</p>}</div>}</section></div>
}

function ExportPanel({ run, exportResult, curationUrl, busy, onCuration, onExport }: { run: RunSummary | null; exportResult: { kind: 'compose' | 'runtime'; manifest_asset: string; atlas_asset?: string; sprite_sheet_asset?: string; size?: [number, number] } | null; curationUrl: string; busy: string; onCuration: () => void; onExport: (kind: 'compose' | 'runtime') => void }) {
  if (!run) return <EmptyState text="Select or create a run in Project first." />
  return <div className="content-grid single-grid"><section className="panel export-panel"><div className="panel-heading"><div><p className="eyebrow">CURATION / EXPORT</p><h2>Publish runtime assets</h2></div><span className="step-number">06</span></div><p className="muted">Compose creates the canonical atlas and manifest. Runtime export creates a nearest-neighbor fixed-size package for the game runtime.</p><div className="button-row"><button className="secondary-button" disabled={busy !== ''} type="button" onClick={onCuration}>{busy === 'curation' ? 'Opening…' : 'Open curation'}</button><button className="primary-button" disabled={busy !== ''} type="button" onClick={() => onExport('compose')}>{busy === 'export-compose' ? 'Composing…' : 'Compose atlas'}</button><button className="primary-button" disabled={busy !== ''} type="button" onClick={() => onExport('runtime')}>{busy === 'export-runtime' ? 'Exporting…' : 'Runtime export'}</button></div>{curationUrl && <p className="helper">Curation URL: <a href={curationUrl} target="_blank" rel="noreferrer">{curationUrl}</a></p>}{exportResult && <div className="export-result" role="status"><strong>{exportResult.kind === 'compose' ? 'Compose complete' : 'Runtime export complete'}</strong>{exportResult.size && <span>Sheet size: {exportResult.size[0]} × {exportResult.size[1]} px</span>}<a href={exportResult.sprite_sheet_asset ?? exportResult.atlas_asset} target="_blank" rel="noreferrer">Open atlas image</a><a href={exportResult.manifest_asset} target="_blank" rel="noreferrer">Open manifest JSON</a></div>}</section></div>
}

function PipelineAction({ label, state, active, onClick, disabled }: { label: string; state?: string; active: boolean; onClick: () => void; disabled: boolean }) { return <button className={`pipeline-action ${active ? 'working' : ''}`} type="button" onClick={onClick} disabled={disabled}><span className={`pipeline-indicator ${state ?? 'not-generated'}`} /> <strong>{label}</strong><small>{active ? 'working…' : state ?? 'ready'}</small></button> }
function StatusPill({ value }: { value: string }) { return <span className={`status-pill ${value.replaceAll(' ', '-')}`}>{value}</span> }
function EmptyState({ text }: { text: string }) { return <div className="empty-state"><span className="empty-line" aria-hidden="true" /><p>{text}</p></div> }

export default App
