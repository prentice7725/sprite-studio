export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export type Provider = 'grok' | 'codex'

export interface StateSpec {
  frames: number
  fps: number
  loop: boolean
  action: string
}

export interface RunSummary {
  run_id: string
  character_id: string
  provider: Provider
  preset: string
  mode: string
  directions: string[]
  states: string[]
}

export interface RunDetail extends RunSummary {
  cell_size: number
  runtime_size: number
  generation_profile: string
  background_policy: string
  refine: Record<string, unknown>
  locks: Record<string, string>
}

export interface PromptResponse {
  state: string
  prompt: string
  source: 'generated' | 'override'
}

export interface GenerateResponse {
  provider: Provider
  prompt: string
  raw_asset: string
  raw_bytes: number
  elapsed_seconds: number
  model: string | null
  refs: string[]
  transparent: boolean
  prompt_source: 'generated' | 'override'
}

export interface NormalizeResponse {
  result: 'pass' | 'fail'
  output_asset: string
  output_size: [number, number]
  expected_subjects: number
  valid_subjects: number
  report: Record<string, unknown>
}

export interface ExtractResponse {
  exit_code: number
  summary: string
}

export interface RefineResponse {
  refined_preview_asset: string | null
  report: Record<string, unknown>
  summary: string
}

export interface ReviewData {
  frames: string[]
  refined_frames: string[]
  repair_proposals: string[]
  repaired_frames: string[]
  repair_diff: string[]
  repair_candidates: string[]
  repair_summary: string
  qa_summary: string
  history_summary: string
}

export interface AnimationQaResponse {
  ok: boolean
  warnings: string[]
  summary: string
}

export interface ExportResponse {
  atlas_asset?: string
  manifest_asset: string
  sprite_sheet_asset?: string
  size?: [number, number]
}

export interface StaticProject {
  project_id: string
  provider: Provider
  asset_type: 'PIXEL_SCENE' | 'TILE_SET' | 'PROP_OBJECT' | 'FLAT_SCENE'
  style_profile: string
  tileable: boolean
  export_size: [number, number]
  layer_intent: string
  background_policy: string
}

export interface StaticStatus {
  assets: Record<string, string>
}

export interface StaticQaResponse {
  ok: boolean
  asset_type: string
  warnings: Array<Record<string, unknown>>
}

export interface BatchItemStatus {
  state: string
  status: string
  generate: Record<string, unknown> | null
  normalize: Record<string, unknown> | null
  normalize_error: string | null
  refine: Record<string, unknown> | null
  repair_analysis: Record<string, unknown> | null
  repair: Record<string, unknown> | null
  qa: Record<string, unknown> | null
}

export interface BatchStatus {
  job_id: string | null
  status: string
  current_state: string | null
  current_stage: string | null
  completed_items: number
  total_items: number
  progress_percent: number
  items: BatchItemStatus[]
  error: string | null
  failed_state?: string | null
  failed_stage?: string | null
  started_at?: string | null
  updated_at?: string | null
  finished_at?: string | null
  elapsed_seconds?: number | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json() as { detail?: string | { message?: string } }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail?.message) detail = body.detail.message
    } catch {
      // Keep the HTTP status when the server did not return JSON.
    }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function listRuns(): Promise<RunSummary[]> {
  return request<RunSummary[]>('/runs')
}

export function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/runs/${encodeURIComponent(runId)}`)
}

export function getRunStatus(runId: string): Promise<{ states: Record<string, string> }> {
  return request<{ states: Record<string, string> }>(`/runs/${encodeURIComponent(runId)}/status`)
}

export function uploadImage(file: File): Promise<{ upload_id: string; filename: string }> {
  const body = new FormData()
  body.append('file', file)
  return request<{ upload_id: string; filename: string }>('/uploads', { method: 'POST', body })
}

export function createRun(body: Record<string, unknown>): Promise<RunDetail> {
  return request<RunDetail>('/runs', { method: 'POST', body: JSON.stringify(body) })
}

export function getPrompt(runId: string, state: string): Promise<PromptResponse> {
  return request<PromptResponse>(`/runs/${encodeURIComponent(runId)}/states/${encodeURIComponent(state)}/prompt`)
}

export function savePrompt(runId: string, state: string, prompt: string): Promise<PromptResponse> {
  return request<PromptResponse>(`/runs/${encodeURIComponent(runId)}/states/${encodeURIComponent(state)}/prompt/override`, {
    method: 'PUT',
    body: JSON.stringify({ prompt }),
  })
}

export function generate(runId: string, state: string): Promise<GenerateResponse> {
  return request<GenerateResponse>(`/runs/${encodeURIComponent(runId)}/states/${encodeURIComponent(state)}/generate`, { method: 'POST' })
}

export function normalize(runId: string, state: string): Promise<NormalizeResponse> {
  return request<NormalizeResponse>(`/runs/${encodeURIComponent(runId)}/states/${encodeURIComponent(state)}/normalize`, { method: 'POST' })
}

export function extract(runId: string, state: string): Promise<ExtractResponse> {
  return request<ExtractResponse>(`/runs/${encodeURIComponent(runId)}/states/${encodeURIComponent(state)}/extract`, { method: 'POST' })
}

export function refine(runId: string, state: string): Promise<RefineResponse> {
  return request<RefineResponse>(`/runs/${encodeURIComponent(runId)}/states/${encodeURIComponent(state)}/refine`, { method: 'POST' })
}

export function getReview(runId: string, state: string): Promise<ReviewData> {
  return request<ReviewData>(`/runs/${encodeURIComponent(runId)}/states/${encodeURIComponent(state)}/review`)
}

function repairAction(runId: string, state: string, action: string, body?: unknown): Promise<ReviewData> {
  return request<ReviewData>(`/runs/${encodeURIComponent(runId)}/states/${encodeURIComponent(state)}/repair/${action}`, {
    method: 'POST',
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
}

export function analyzeRepair(runId: string, state: string): Promise<ReviewData> {
  return repairAction(runId, state, 'analyze')
}

export function safeRepair(runId: string, state: string): Promise<ReviewData> {
  return repairAction(runId, state, 'safe')
}

export function decideRepair(runId: string, state: string, candidateIds: string[], accept: boolean): Promise<ReviewData> {
  return repairAction(runId, state, 'decide', { candidate_ids: candidateIds, accept })
}

export function undoRepair(runId: string, state: string): Promise<ReviewData> {
  return repairAction(runId, state, 'undo')
}

export function adoptRepair(runId: string, state: string): Promise<ReviewData> {
  return repairAction(runId, state, 'adopt')
}

export function unadoptRepair(runId: string, state: string): Promise<ReviewData> {
  return repairAction(runId, state, 'unadopt')
}

export function runAnimationQa(runId: string, state: string): Promise<AnimationQaResponse> {
  return request<AnimationQaResponse>(`/runs/${encodeURIComponent(runId)}/states/${encodeURIComponent(state)}/animation-qa`, { method: 'POST' })
}

export function launchCuration(runId: string): Promise<{ url: string }> {
  return request<{ url: string }>(`/runs/${encodeURIComponent(runId)}/curation`, { method: 'POST' })
}

export function composeExport(runId: string): Promise<ExportResponse> {
  return request<ExportResponse>(`/runs/${encodeURIComponent(runId)}/export/compose`, { method: 'POST' })
}

export function runtimeExport(runId: string): Promise<ExportResponse> {
  return request<ExportResponse>(`/runs/${encodeURIComponent(runId)}/export/runtime`, { method: 'POST' })
}

export function listStaticProjects(): Promise<StaticProject[]> {
  return request<StaticProject[]>('/static')
}

export function listStaticPresets(): Promise<string[]> {
  return request<string[]>('/static/presets')
}

export function createStaticProject(body: Record<string, unknown>): Promise<StaticProject> {
  return request<StaticProject>('/static', { method: 'POST', body: JSON.stringify(body) })
}

export function getStaticStatus(projectId: string): Promise<StaticStatus> {
  return request<StaticStatus>(`/static/${encodeURIComponent(projectId)}/status`)
}

export function getStaticPrompt(projectId: string): Promise<{ prompt: string; issues: string[] }> {
  return request<{ prompt: string; issues: string[] }>(`/static/${encodeURIComponent(projectId)}/prompt`)
}

export function staticGenerate(projectId: string, body: { asset: string; prompt_override?: string; provider?: Provider }): Promise<{ asset: string; provider: string; elapsed_seconds: number; out_asset: string }> {
  return request(`/static/${encodeURIComponent(projectId)}/generate`, { method: 'POST', body: JSON.stringify(body) })
}

export function staticImport(projectId: string, body: { asset: string; upload_id: string }): Promise<{ out_asset: string }> {
  return request(`/static/${encodeURIComponent(projectId)}/import`, { method: 'POST', body: JSON.stringify(body) })
}

export function staticRefine(projectId: string, body: { asset: string; cleanup: boolean; dither_mode: string; fft_candidate_search: boolean }): Promise<{ output_asset: string; report: Record<string, unknown> }> {
  return request(`/static/${encodeURIComponent(projectId)}/refine`, { method: 'POST', body: JSON.stringify(body) })
}

export function staticCleanup(projectId: string, body: { asset: string; orphan_max_area: number; hole_max_area: number }): Promise<{ output_asset: string; report: Record<string, unknown> }> {
  return request(`/static/${encodeURIComponent(projectId)}/cleanup`, { method: 'POST', body: JSON.stringify(body) })
}

export function staticSeam(projectId: string, body: { asset: string; repair: boolean }, repair: boolean): Promise<{ wrap_preview_asset: string; report: Record<string, unknown> }> {
  return request(`/static/${encodeURIComponent(projectId)}/${repair ? 'seam-repair' : 'seam-check'}`, { method: 'POST', body: JSON.stringify({ ...body, repair }) })
}

export function staticLayers(projectId: string, body: { asset: string; cutout: boolean }, cutout: boolean): Promise<{ layer_assets: string[]; report: Record<string, unknown> }> {
  return request(`/static/${encodeURIComponent(projectId)}/layers/${cutout ? 'cutout' : 'split'}`, { method: 'POST', body: JSON.stringify({ ...body, cutout }) })
}

export function staticQa(projectId: string, asset: string): Promise<StaticQaResponse> {
  return request<StaticQaResponse>(`/static/${encodeURIComponent(projectId)}/qa?asset=${encodeURIComponent(asset)}`, { method: 'POST' })
}

export function staticExport(projectId: string, asset: string): Promise<{ export_asset: string }> {
  return request<{ export_asset: string }>(`/static/${encodeURIComponent(projectId)}/export?asset=${encodeURIComponent(asset)}`, { method: 'POST' })
}

export function startBatch(runId: string, body: { states: string[]; normalize: boolean; refine: boolean; repair: boolean; qa: boolean }): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(`/runs/${encodeURIComponent(runId)}/batches`, { method: 'POST', body: JSON.stringify(body) })
}

export function getCurrentBatch(runId: string): Promise<BatchStatus> {
  return request<BatchStatus>(`/runs/${encodeURIComponent(runId)}/batches/current`)
}

export function websocketUrl(runId: string, jobId: string): string {
  const path = `${API_BASE}/runs/${encodeURIComponent(runId)}/batches/${encodeURIComponent(jobId)}/events`
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path.replace(/^http/, 'ws')
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}
