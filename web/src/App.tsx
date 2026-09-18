import { useEffect, useMemo, useState } from 'react'
import {
  BatchStatus,
  JobStatus,
  AnimationQaResponse,
  ReviewData,
  StaticProject,
  StaticPreset,
  StaticQaResponse,
  createRun,
  createStaticProject,
  getCurrentBatch,
  getGenerationStrategy,
  getSequential,
  approveKeyPoses,
  getPrompt,
  getReview,
  getRun,
  getRunStatus,
  getPreset,
  listJobs,
  getStaticPrompt,
  getStaticPreset,
  getStaticStatus,
  listRuns,
  listProviders,
  listPresets,
  listStaticProjects,
  listStaticPresets,
  launchCuration,
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
  jobWebsocketUrl,
  startJob,
  cancelJob,
  retryJob,
} from './api'
import type { JobOperation, Provider, ProviderStatus, SpritePreset } from './api'
import type { GenerationStrategy, MotionPlan, SequentialGenerationResponse } from './api'
import AssetLibrary from './features/assets/AssetLibrary'
import CreateAssetForm, { type CreateAssetDraft } from './features/assets/CreateAssetForm'
import JobDrawer from './features/jobs/JobDrawer'
import { WorkspaceSelectionProvider, useWorkspaceSelection } from './features/workspace/WorkspaceSelectionContext'
import VariantsPanel from './features/workspace/VariantsPanel'
import StrategyPlanner from './features/workspace/StrategyPlanner'
import NextActionPanel, { type NextAction } from './features/workspace/NextActionPanel'
import { EmptyState, ExportPanel, GeneratePanel, QaPanel, RefinePanel, ReviewPanel, WorkspaceContextPanel } from './features/workspace/WorkspacePanels'
import type { ReviewAction } from './features/workspace/WorkspacePanels'
import StaticWorkspace, { type StaticCreateDraft } from './features/static/StaticWorkspace'
import { useI18n } from './i18n'
import DisplaySettings from './features/ui/DisplaySettings'
import QuickGeneratePage from './features/quick/QuickGeneratePage'

type Tab = 'quick' | 'project' | 'static' | 'workspace' | 'jobs'
type WorkspaceTool = 'generate' | 'refine' | 'review' | 'qa' | 'export'
type Notice = { kind: 'success' | 'error' | 'info'; text: string }
type StaticAction = 'generate' | 'refine' | 'cleanup' | 'seam-check' | 'seam-repair' | 'layers-split' | 'layers-cutout' | 'qa' | 'export'
type ActiveJob = { jobId: string; runId: string; operation: JobOperation; state: string | null; status: JobStatus | null }
type PreviewSnapshot = { rawAsset: string; refinedAsset: string; refineSummary: string }
type StaticPreviewSnapshot = { output: string; wrapPreview: string; wrapReport: Record<string, unknown> | null; report: string }

const fallbackProviderChoices: Provider[] = ['grok']

const tabs: Array<{ id: Tab; label: string; hint: string }> = [
  { id: 'quick', label: 'Quick Generate', hint: 'Source to sprite' },
  { id: 'project', label: 'Studio', hint: 'Advanced production workflow' },
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
  const { locale, t, toggleLocale } = useI18n()
  const [tab, setTab] = useState<Tab>('quick')
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
  const [previewCache, setPreviewCache] = useState<Record<string, PreviewSnapshot>>({})
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
  const [staticPreviewCache, setStaticPreviewCache] = useState<Record<string, StaticPreviewSnapshot>>({})
  const [batchStates, setBatchStates] = useState<string[]>([])
  const [batchJobId, setBatchJobId] = useState('')
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null)
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null)
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
  const previewKey = selectedRunId && activeState ? `${selectedRunId}:${activeState}` : ''
  const preview = previewCache[previewKey] ?? { rawAsset: '', refinedAsset: '', refineSummary: '' }
  const rawAsset = preview.rawAsset
  const refinedAsset = preview.refinedAsset
  const refineSummary = preview.refineSummary
  const staticPreviewKey = selectedStaticId ? `${selectedStaticId}:${staticAssetName}` : ''
  const staticPreview = staticPreviewCache[staticPreviewKey] ?? { output: '', wrapPreview: '', wrapReport: null, report: '' }
  const staticOutput = staticPreview.output
  const staticWrapPreview = staticPreview.wrapPreview
  const staticWrapReport = staticPreview.wrapReport
  const staticReport = staticPreview.report
  const activeJobIsActive = Boolean(activeJob && (!activeJob.status || activeJob.status.status === 'running' || activeJob.status.status === 'cancel_requested'))
  const currentJob = activeJob?.runId === selectedRunId ? activeJob : null
  const currentJobIsActive = Boolean(currentJob && (!currentJob.status || currentJob.status.status === 'running' || currentJob.status.status === 'cancel_requested'))
  const activeJobBusy = currentJobIsActive ? currentJob?.operation ?? '' : ''
  const workspaceBusy = activeJobBusy || (busy.startsWith('job:') ? '' : busy)
  const sequentialBusyFromJob = currentJobIsActive && currentJob?.operation === 'sequential_key_poses'
    ? 'key-poses'
    : currentJobIsActive && currentJob?.operation === 'sequential_inbetweens'
      ? 'inbetweens'
      : currentJobIsActive && currentJob?.operation === 'sequential_promote'
        ? 'promote'
        : ''
  const timelineFrames = review?.repaired_frames.length
    ? review.repaired_frames
    : review?.refined_frames.length
      ? review.refined_frames
      : review?.frames ?? []
  const providerChoices = useMemo<Provider[]>(() => {
    const available = providers.filter((provider) => provider.available).map((provider) => provider.name)
    return available.length ? available : fallbackProviderChoices
  }, [providers])

  function patchPreview(runId: string, state: string, patch: Partial<PreviewSnapshot>) {
    const key = runId && state ? `${runId}:${state}` : ''
    if (!key) return
    setPreviewCache((current) => {
      const existing = current[key] ?? { rawAsset: '', refinedAsset: '', refineSummary: '' }
      return { ...current, [key]: { ...existing, ...patch } }
    })
  }

  function patchStaticPreview(projectId: string, asset: string, patch: Partial<StaticPreviewSnapshot>) {
    const key = projectId && asset ? `${projectId}:${asset}` : ''
    if (!key) return
    setStaticPreviewCache((current) => {
      const existing = current[key] ?? { output: '', wrapPreview: '', wrapReport: null, report: '' }
      return { ...current, [key]: { ...existing, ...patch } }
    })
  }

  const setStaticOutput = (projectId: string, assetName: string, value: string) => patchStaticPreview(projectId, assetName, { output: value })
  const setStaticWrapPreview = (projectId: string, assetName: string, value: string) => patchStaticPreview(projectId, assetName, { wrapPreview: value })
  const setStaticWrapReport = (projectId: string, assetName: string, value: Record<string, unknown> | null) => patchStaticPreview(projectId, assetName, { wrapReport: value })
  const setStaticReport = (projectId: string, assetName: string, value: string) => patchStaticPreview(projectId, assetName, { report: value })

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
    if (!selectedRunId) return
    let cancelled = false
    void listJobs(selectedRunId).then(({ jobs }) => {
      if (cancelled) return
      const persisted = jobs.find((job) => job.status === 'running' || job.status === 'cancel_requested')
      if (persisted) {
        setActiveJob((current) => {
          const currentIsActive = current?.runId === selectedRunId && (!current.status || current.status.status === 'running' || current.status.status === 'cancel_requested')
          return currentIsActive ? current : { jobId: persisted.job_id, runId: selectedRunId, operation: persisted.operation, state: persisted.state, status: persisted }
        })
      } else {
        setActiveJob((current) => {
          const currentIsActive = current?.runId === selectedRunId && (!current.status || current.status.status === 'running' || current.status.status === 'cancel_requested')
          return currentIsActive ? current : current?.runId === selectedRunId ? null : current
        })
      }
    }).catch(() => {
      // Job recovery is best effort; the API remains available through manual retry.
    })
    return () => { cancelled = true }
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

  useEffect(() => {
    if (!activeJob) return
    const jobId = activeJob.jobId
    const jobRunId = activeJob.runId
    const socket = new WebSocket(jobWebsocketUrl(jobRunId, jobId))
    socket.onmessage = (event) => {
      try {
        const next = JSON.parse(event.data) as JobStatus
        setActiveJob((current) => current?.jobId === jobId ? { ...current, status: next } : current)
        const jobState = next.state ?? ''
        const isCurrentSelection = jobRunId === selectedRunId && jobState === activeState
        if (next.status === 'succeeded') {
          const result = next.result ?? {}
          if (next.operation === 'generate') {
            patchPreview(jobRunId, jobState, { rawAsset: String(result.raw_asset ?? '') })
            if (isCurrentSelection) setNotice({ kind: 'success', text: `Generated ${labelForState(jobState)} in ${Number(result.elapsed_seconds ?? 0).toFixed(1)}s (${formatBytes(Number(result.raw_bytes ?? 0))}).` })
          } else if (next.operation === 'normalize') {
            patchPreview(jobRunId, jobState, { rawAsset: String(result.output_asset ?? '') })
            const passed = result.result === 'pass'
            if (isCurrentSelection) setNotice({ kind: passed ? 'success' : 'error', text: `Normalize ${String(result.result ?? 'complete')}: ${String(result.valid_subjects ?? '?')}/${String(result.expected_subjects ?? '?')} subjects valid.` })
          } else if (next.operation === 'refine') {
            patchPreview(jobRunId, jobState, { refinedAsset: String(result.refined_preview_asset ?? ''), refineSummary: JSON.stringify(result.report ?? {}, null, 2) })
            if (isCurrentSelection) setNotice({ kind: 'success', text: `Refined ${labelForState(jobState)}.` })
          } else if (next.operation === 'animation_qa') {
            const qa = (result.qa ?? {}) as AnimationQaResponse
            if (isCurrentSelection) {
              setAnimationQa(qa)
              setNotice({ kind: qa.ok ? 'success' : 'error', text: qa.summary ?? 'Animation QA completed.' })
            }
          } else if (next.operation === 'export_compose' || next.operation === 'export_runtime') {
            if (jobRunId === selectedRunId) {
              setExportResult({ kind: next.operation === 'export_compose' ? 'compose' : 'runtime', manifest_asset: String(result.manifest_asset ?? ''), ...(result as { atlas_asset?: string; sprite_sheet_asset?: string; size?: [number, number] }) })
              setNotice({ kind: 'success', text: `${next.operation === 'export_compose' ? 'Compose' : 'Runtime export'} completed.` })
            }
          } else if (next.operation.startsWith('repair_')) {
            if (isCurrentSelection) {
              void getReview(jobRunId, jobState).then(setReview)
              setSelectedCandidates([])
              setNotice({ kind: 'success', text: `Repair ${next.operation.replace('repair_', '')} completed.` })
            }
          } else if (next.operation.startsWith('sequential_')) {
            if (isCurrentSelection) {
              void getSequential(jobRunId, jobState).then((value) => { setSequential(value); setMotionPlan(value.motion_plan) })
              setNotice({ kind: 'success', text: `${next.operation.replaceAll('_', ' ')} completed.` })
            }
          }
          void getRunStatus(jobRunId).then((status) => {
            if (jobRunId === selectedRunId) setRunStatus(status.states)
          }).catch(() => { /* the job result remains authoritative */ })
          setBusy('')
        } else if (next.status === 'failed') {
          setBusy('')
          const result = next.result ?? {}
          const fallback = result.fallback as { strategy?: GenerationStrategy; motion_plan?: MotionPlan } | undefined
          if (isCurrentSelection && next.operation === 'normalize' && fallback?.strategy && fallback.motion_plan) {
            setGenerationStrategy(fallback.strategy)
            setMotionPlan(fallback.motion_plan)
            setSequential(null)
            setNotice({ kind: 'info', text: `${jobState || 'state'}: Row Normalize quality failed. A KEYPOSE_SEQUENTIAL Motion Plan is ready; generate and approve key poses to continue.` })
          } else if (isCurrentSelection) {
            setNotice({ kind: 'error', text: next.error ?? 'Background job failed.' })
          }
        } else if (next.status === 'cancelled') {
          setBusy('')
          if (isCurrentSelection) setNotice({ kind: 'info', text: 'Background job cancelled.' })
        }
      } catch {
        setNotice({ kind: 'error', text: 'Job WebSocket 응답을 해석하지 못했습니다.' })
      }
    }
    socket.onerror = () => setNotice({ kind: 'error', text: 'Job WebSocket 연결에 실패했습니다.' })
    return () => socket.close()
  }, [activeJob?.jobId, activeJob?.runId, selectedRunId, activeState])

  async function openStudio(runId?: string) {
    if (runId) {
      await refreshRuns(runId)
      setSelectedRunId(runId)
    }
    setTab('project')
    setWorkspaceTool('generate')
  }
  function selectRun(runId: string) {
    setSelectedRunId(runId)
    setSelectedFrame(0)
    setBatchJobId('')
    setBatchStatus(null)
    setNotice(null)
  }

  async function beginJob(operation: JobOperation, state?: string, options: Record<string, unknown> = {}) {
    if (!selectedRunId) return false
    setBusy(`job:${operation}`)
    setNotice(null)
    try {
      const result = await startJob(selectedRunId, { operation, ...(state ? { state } : {}), options })
      setActiveJob({ jobId: result.job_id, runId: selectedRunId, operation, state: state ?? null, status: null })
      setJobDrawerOpen(true)
      setNotice({ kind: 'info', text: `${operation.replaceAll('_', ' ')} job ${result.job_id} started.` })
      return true
    } catch (error: unknown) {
      setBusy('')
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
      return false
    }
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

  async function handleSequential(action: 'key-poses' | 'approve' | 'inbetweens' | 'promote', indices: number[] = []) {
    if (!selectedRunId || !activeState) return
    if (action !== 'approve') {
      const operation: JobOperation = action === 'key-poses' ? 'sequential_key_poses' : action === 'inbetweens' ? 'sequential_inbetweens' : 'sequential_promote'
      await beginJob(operation, activeState)
      return
    }
    setSequentialBusy(action)
    setNotice(null)
    try {
      const result = await approveKeyPoses(selectedRunId, activeState, indices)
      setSequential(result)
      setMotionPlan(result.motion_plan)
      setNotice({ kind: 'success', text: `${activeState}: key poses approved.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setSequentialBusy('')
    }
  }

  async function handleGenerate() {
    if (!selectedRunId || !activeState) return
    await beginJob('generate', activeState)
  }

  async function handleNormalize() {
    if (!selectedRunId || !activeState) return
    await beginJob('normalize', activeState, { strategy: generationStrategy })
  }

  async function handleExtract() {
    if (!selectedRunId || !activeState) return
    await beginJob('extract', activeState)
  }

  async function handleRefine() {
    if (!selectedRunId || !activeState) return
    await beginJob('refine', activeState)
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
    const projectId = selectedStaticId
    const assetName = staticAssetName
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
    patchStaticPreview(projectId, assetName, { wrapPreview: '', wrapReport: null, report: '' })
    try {
      const upload = await uploadImage(file)
      const result = await staticImport(projectId, { asset: assetName, upload_id: upload.upload_id })
      setStaticOutput(projectId, assetName, result.out_asset)
      setStaticStatus((await getStaticStatus(projectId)).assets)
      setNotice({ kind: 'success', text: `Imported ${assetName}.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleStaticAction(action: StaticAction) {
    if (!selectedStaticId) return
    const projectId = selectedStaticId
    const assetName = staticAssetName
    setBusy(`static-${action}`)
    setNotice(null)
    patchStaticPreview(projectId, assetName, { wrapPreview: '', wrapReport: null, report: '' })
    try {
      if (action === 'generate') {
        const result = await staticGenerate(projectId, { asset: assetName, prompt_override: staticPrompt })
        setStaticOutput(projectId, assetName, result.out_asset)
        setNotice({ kind: 'success', text: `Generated ${assetName} via ${result.provider}.` })
      } else if (action === 'refine') {
        const result = await staticRefine(projectId, { asset: assetName })
        setStaticOutput(projectId, assetName, result.output_asset)
        setStaticReport(projectId, assetName, JSON.stringify(result.report, null, 2))
        setNotice({ kind: 'success', text: `Refined ${assetName}.` })
      } else if (action === 'cleanup') {
        const result = await staticCleanup(projectId, { asset: assetName })
        setStaticOutput(projectId, assetName, result.output_asset)
        setStaticReport(projectId, assetName, JSON.stringify(result.report, null, 2))
        setNotice({ kind: 'success', text: `Cleaned ${assetName}.` })
      } else if (action === 'seam-check' || action === 'seam-repair') {
        const repair = action === 'seam-repair'
        const result = await staticSeam(projectId, { asset: assetName, repair }, repair)
        setStaticOutput(projectId, assetName, result.wrap_preview_asset)
        setStaticWrapPreview(projectId, assetName, result.wrap_preview_asset)
        setStaticWrapReport(projectId, assetName, result.report)
        setStaticReport(projectId, assetName, JSON.stringify(result.report, null, 2))
        setNotice({ kind: 'success', text: `${repair ? 'Seam repair' : 'Seam check'} completed.` })
      } else if (action === 'layers-split' || action === 'layers-cutout') {
        const cutout = action === 'layers-cutout'
        const result = await staticLayers(projectId, { asset: assetName, cutout }, cutout)
        setStaticOutput(projectId, assetName, result.layer_assets[0] ?? '')
        setStaticReport(projectId, assetName, JSON.stringify(result.report, null, 2))
        setNotice({ kind: 'success', text: `${cutout ? 'Cutout' : 'Layer split'} completed.` })
      } else if (action === 'qa') {
        const result: StaticQaResponse = await staticQa(projectId, assetName)
        setStaticReport(projectId, assetName, JSON.stringify(result, null, 2))
        setNotice({ kind: result.ok ? 'success' : 'error', text: result.ok ? 'Static QA passed.' : 'Static QA found warnings.' })
      } else {
        const result = await staticExport(projectId, assetName)
        setStaticOutput(projectId, assetName, result.export_asset)
        setNotice({ kind: 'success', text: `Exported ${assetName}.` })
      }
      setStaticStatus((await getStaticStatus(projectId)).assets)
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy('')
    }
  }

  async function handleReviewAction(action: ReviewAction) {
    if (!selectedRunId || !activeState) return
    if (action === 'load') {
      setBusy('review-load')
      try {
        setReview(await getReview(selectedRunId, activeState))
        setNotice({ kind: 'success', text: 'Review loaded.' })
      } catch (error: unknown) {
        setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
      } finally {
        setBusy('')
      }
      return
    }
    const operation: JobOperation = action === 'analyze' ? 'repair_analyze' : action === 'safe' ? 'repair_safe' : action === 'undo' ? 'repair_undo' : action === 'adopt' ? 'repair_adopt' : action === 'unadopt' ? 'repair_unadopt' : 'repair_decide'
    await beginJob(operation, activeState, action === 'accept' || action === 'reject' ? { candidate_ids: selectedCandidates, accept: action === 'accept' } : {})
  }

  async function handleAnimationQa() {
    if (!selectedRunId || !activeState) return
    await beginJob('animation_qa', activeState)
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
    await beginJob(kind === 'compose' ? 'export_compose' : 'export_runtime')
  }

  async function handleNextAction(action: NextAction) {
    if (action === 'sequential_key_poses') {
      await handleSequential('key-poses')
    } else if (action === 'sequential_approve') {
      const indices = (sequential?.key_poses ?? []).filter((item) => item.status === 'generated').map((item) => item.index)
      await handleSequential('approve', indices)
    } else if (action === 'sequential_inbetweens') {
      await handleSequential('inbetweens')
    } else if (action === 'sequential_promote') {
      await handleSequential('promote')
    } else if (action === 'repair_analyze') {
      setWorkspaceTool('review')
      await handleReviewAction('analyze')
    } else if (action === 'animation_qa') {
      setWorkspaceTool('qa')
      await handleAnimationQa()
    } else if (action === 'export_compose') {
      setWorkspaceTool('export')
      await handleExport('compose')
    } else {
      setWorkspaceTool(action === 'refine' ? 'refine' : 'generate')
      if (action === 'generate') await handleGenerate()
      else if (action === 'normalize') await handleNormalize()
      else if (action === 'extract') await handleExtract()
      else await handleRefine()
    }
  }

  async function handleCancelSingleJob() {
    if (!activeJob) return
    try {
      const status = await cancelJob(activeJob.runId, activeJob.jobId)
      setActiveJob((current) => current?.jobId === activeJob.jobId ? { ...current, status } : current)
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    }
  }

  async function handleRetrySingleJob() {
    if (!activeJob) return
    try {
      const result = await retryJob(activeJob.runId, activeJob.jobId)
      setActiveJob({ ...activeJob, jobId: result.job_id, status: null })
      setBusy(`job:retry`)
      setNotice({ kind: 'info', text: `Retry job ${result.job_id} started.` })
    } catch (error: unknown) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
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
              <span>{item.id === 'quick' ? (locale === 'ko' ? '빠른 생성' : item.label) : item.id === 'project' ? t('project') : item.id === 'static' ? t('static') : item.id === 'workspace' ? t('workspace') : t('jobs')}</span>
              <small>{item.id === 'quick' ? (locale === 'ko' ? '소스에서 스프라이트까지' : item.hint) : item.hint}</small>
            </button>
          ))}
        </nav>
        {tab !== 'quick' && <AssetLibrary runs={runs} />}
        <div className="sidebar-footer">
          <span className="status-dot" aria-hidden="true" />
          <div><strong>Migration Phase 6</strong><small>React over FastAPI</small></div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="eyebrow">LOCAL WORKSPACE / {tab === 'quick' ? (locale === 'ko' ? '빠른 생성' : 'QUICK GENERATE') : tab === 'workspace' ? workspaceTool.toUpperCase() : tab.toUpperCase()}</p>
            <h1>{tab === 'quick' ? (locale === 'ko' ? '소스에서 스프라이트까지' : 'Source to sprite') : tab === 'project' ? t('createAsset') : tab === 'static' ? t('buildStatic') : tab === 'workspace' ? workspaceTools.find((tool) => tool.id === workspaceTool)?.hint ?? 'Work on the active asset' : t('backgroundJobs')}</h1>
          </div>
          <div className="topbar-actions">
          {tab !== 'quick' && <div className="run-selector">
            <label htmlFor="global-run">{t('activeAsset')}</label>
            <select id="global-run" value={selectedRunId} onChange={(event) => selectRun(event.target.value)}>
              <option value="">{t('selectAsset')}</option>
              {runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.character_id} · {run.preset}</option>)}
            </select>
          </div>}
          {tab !== 'quick' && selectedRun && <span className="selection-chip">{activeState || 'No state'} · Frame {selectedFrame + 1}</span>}
          <button className="tool-button text-button locale-toggle" type="button" onClick={toggleLocale}>{t('language')}</button>
          <DisplaySettings />
          {tab !== 'quick' && <button className="job-trigger" type="button" onClick={() => setJobDrawerOpen(true)} aria-expanded={jobDrawerOpen} aria-controls="job-drawer">{t('jobs')}{batchStatus?.status === 'running' || activeJobIsActive ? <span className="status-dot" aria-label="job running" /> : null}</button>}
          </div>
        </header>

        {notice && <div className={`notice ${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</div>}

        {tab === 'quick' && <QuickGeneratePage providerChoices={providerChoices} onOpenStudio={(runId) => void openStudio(runId)} />}

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
        {tab === 'workspace' && <WorkspaceContextPanel frames={timelineFrames} activeFrame={selectedFrame} fps={activePreset?.states[activeState]?.fps ?? 8} loop={activePreset?.states[activeState]?.loop ?? true} repairedFrames={review?.repaired_frames} rawAsset={rawAsset} state={activeState} review={workspaceTool === 'review' ? review : null} onFrameChange={setSelectedFrame} />}
        {tab === 'workspace' && selectedRun && <NextActionPanel state={activeState} pipelineStatus={runStatus[activeState] ?? 'not-generated'} animationQaReady={animationQa !== null} motionPlan={motionPlan} sequential={sequential} activeJob={currentJobIsActive ? currentJob?.status ?? null : null} onAction={(action) => void handleNextAction(action)} />}
        {tab === 'workspace' && <><div className="workspace-tools" aria-label="Asset tools">{workspaceTools.map((tool) => <button className={`workspace-tool ${workspaceTool === tool.id ? 'active' : ''}`} type="button" key={tool.id} onClick={() => setWorkspaceTool(tool.id)}><strong>{tool.label}</strong><small>{tool.hint}</small></button>)}</div>{workspaceTool === 'generate' && <GeneratePanel run={selectedRun} state={activeState} states={selectedRun?.states ?? []} prompt={prompt} promptSource={promptSource} onPromptChange={setPrompt} onSavePrompt={() => void handleSavePrompt()} rawAsset={rawAsset} busy={workspaceBusy} onGenerate={() => void handleGenerate()} onNormalize={() => void handleNormalize()} onExtract={() => void handleExtract()} status={runStatus} />}{workspaceTool === 'refine' && <RefinePanel run={selectedRun} state={activeState} states={selectedRun?.states ?? []} busy={workspaceBusy} onRefine={() => void handleRefine()} previewAsset={refinedAsset} summary={refineSummary} />}{workspaceTool === 'review' && <ReviewPanel run={selectedRun} state={activeState} states={selectedRun?.states ?? []} review={review} selectedCandidates={selectedCandidates} onToggleCandidate={(id) => setSelectedCandidates((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])} busy={workspaceBusy} onAction={(action) => void handleReviewAction(action)} />}{workspaceTool === 'qa' && <QaPanel run={selectedRun} states={selectedRun?.states ?? []} result={animationQa} busy={workspaceBusy} onRun={() => void handleAnimationQa()} />}{workspaceTool === 'export' && <ExportPanel run={selectedRun} exportResult={exportResult} curationUrl={curationUrl} busy={workspaceBusy} onCuration={() => void handleCuration()} onExport={(kind) => void handleExport(kind)} />}</>}
        {tab === 'workspace' && workspaceTool === 'generate' && <StrategyPlanner value={generationStrategy} plan={motionPlan} sequential={sequential} busy={strategyBusy} sequentialBusy={sequentialBusy || sequentialBusyFromJob} onChange={setGenerationStrategy} onSave={() => void handleSaveStrategy()} onGenerateKeyPoses={() => void handleSequential('key-poses')} onApproveKeyPoses={(indices) => void handleSequential('approve', indices)} onGenerateInbetweens={() => void handleSequential('inbetweens')} onPromote={() => void handleSequential('promote')} />}
        {tab === 'workspace' && workspaceTool === 'review' && <VariantsPanel review={review} />}
        {tab === 'jobs' && <section className="panel jobs-page"><p className="eyebrow">GLOBAL JOB CENTER</p><h2>Batch jobs stay available while you work on an asset.</h2><p className="muted">Use the Jobs button in the top bar to open the drawer without leaving the current workspace.</p><button className="primary-button" type="button" onClick={() => setJobDrawerOpen(true)}>Open job drawer</button></section>}

      </main>
      <JobDrawer open={jobDrawerOpen} run={selectedRun} states={selectedRun?.states ?? []} selectedStates={batchStates} status={batchStatus} jobId={batchJobId} activeJob={activeJob?.status ?? null} activeJobId={activeJob?.jobId ?? ''} activeJobRunId={activeJob?.runId ?? ''} busy={busy} onClose={() => setJobDrawerOpen(false)} onToggle={(state) => setBatchStates((current) => current.includes(state) ? current.filter((item) => item !== state) : [...current, state])} onStart={() => void handleStartBatch()} onCancelSingle={() => void handleCancelSingleJob()} onRetrySingle={() => void handleRetrySingleJob()} />
    </div>
    </WorkspaceSelectionProvider>
  )
}

function RunCard({ run, selected, onSelect }: { run: RunSummary; selected: boolean; onSelect: () => void }) {
  return <button className={`run-card ${selected ? 'selected' : ''}`} type="button" onClick={onSelect}><span className="run-card-title">{run.run_id}</span><span>{run.character_id} · {run.provider}</span><small>{run.states.length} states · {run.directions.join(', ')}</small></button>
}

function AssetFacade({ detail, status }: { detail: RunDetail; status: Record<string, string> }) {
  const selection = useWorkspaceSelection()
  return <section className="panel overview-panel"><div className="panel-heading"><div><p className="eyebrow">ACTIVE ASSET</p><h2>{detail.character_id}</h2></div><span className="mode-badge">{detail.preset}</span></div><div className="stat-grid"><Stat label="Asset ID" value={detail.run_id} /><Stat label="Cell" value={`${detail.cell_size} px`} /><Stat label="Runtime" value={`${detail.runtime_size} px`} /><Stat label="Profile" value={detail.generation_profile} /></div><div className="state-strip">{detail.states.map((state) => <button className={`state-chip ${selection.activeState === state ? 'selected' : ''}`} type="button" key={state} onClick={() => { selection.setActiveAsset(detail.run_id); selection.setActiveState(state) }}><span className={`mini-status ${status[state] ?? 'not-generated'}`} />{labelForState(state)}<small>{status[state] ?? 'not-generated'}</small></button>)}</div></section>
}

function Stat({ label, value }: { label: string; value: string }) { return <div className="stat"><span>{label}</span><strong>{value}</strong></div> }

export default App
