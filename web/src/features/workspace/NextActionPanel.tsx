import type { JobStatus, MotionPlan, SequentialGenerationResponse } from '../../api'

export type NextAction = 'generate' | 'normalize' | 'extract' | 'refine' | 'repair_analyze' | 'animation_qa' | 'export_compose' | 'sequential_key_poses' | 'sequential_approve' | 'sequential_inbetweens' | 'sequential_promote'

interface NextActionPanelProps {
  state: string
  pipelineStatus: string
  animationQaReady: boolean
  motionPlan: MotionPlan | null
  sequential: SequentialGenerationResponse | null
  activeJob: JobStatus | null
  onAction: (action: NextAction) => void
}

function labelForState(state: string): string {
  return state.replaceAll('_', ' / ')
}

function labelForOperation(operation: string): string {
  return operation.replaceAll('_', ' ')
}

function nextActionFor(status: string, animationQaReady: boolean, motionPlan: MotionPlan | null, sequential: SequentialGenerationResponse | null): { action: NextAction; label: string; detail: string } {
  if (motionPlan?.strategy === 'KEYPOSE_SEQUENTIAL' && !sequential?.promoted) {
    const sequentialStatus = sequential?.status ?? 'planned'
    const generatedKeyPoses = sequential?.key_poses.filter((item) => item.status === 'generated').length ?? 0
    if (sequentialStatus === 'pending_key_pose_approval' && generatedKeyPoses >= 2) return { action: 'sequential_approve', label: 'Approve key poses', detail: 'Choose the generated key poses before creating inbetween frames.' }
    if (sequentialStatus === 'key_poses_approved') return { action: 'sequential_inbetweens', label: 'Generate inbetweens', detail: 'Create the missing motion phases between the approved key poses.' }
    if (sequentialStatus === 'sequential_frames_generated') return { action: 'sequential_promote', label: 'Promote to Refine / QA', detail: 'Publish the approved sequential frames into the shared pipeline.' }
    return { action: 'sequential_key_poses', label: 'Generate key poses', detail: 'Create the planned key poses before approving the sequential motion.' }
  }
  if (status === 'raw') return { action: 'normalize', label: 'Normalize this row', detail: 'Fit the provider output to the declared sprite layout.' }
  if (status === 'normalized') return { action: 'extract', label: 'Extract frames', detail: 'Split the normalized row into canonical animation frames.' }
  if (status === 'extracted') return { action: 'refine', label: 'Refine frames', detail: 'Apply the shared grid, scale, baseline, palette, and pivot locks.' }
  if (status === 'warning') return { action: 'repair_analyze', label: 'Analyze repair candidates', detail: 'Review the QA warning and inspect safe repair proposals.' }
  if (status === 'refined' && !animationQaReady) return { action: 'animation_qa', label: 'Run animation QA', detail: 'Check continuity before publishing the runtime atlas.' }
  if (status === 'repaired' && !animationQaReady) return { action: 'animation_qa', label: 'Run animation QA', detail: 'Verify the adopted repaired frames before publishing.' }
  if (animationQaReady) return { action: 'export_compose', label: 'Compose the atlas', detail: 'QA is available for this state; publish the canonical runtime source.' }
  return { action: 'generate', label: status === 'failed' ? 'Retry generation' : 'Generate this row', detail: 'Start the provider-backed first stage for this animation state.' }
}

export default function NextActionPanel({ state, pipelineStatus, animationQaReady, motionPlan, sequential, activeJob, onAction }: NextActionPanelProps) {
  const jobIsActive = activeJob?.status === 'running' || activeJob?.status === 'cancel_requested'
  const action = nextActionFor(pipelineStatus, animationQaReady, motionPlan, sequential)
  return <section className="next-action-panel" aria-live="polite" aria-busy={jobIsActive}>
    <div><p className="eyebrow">NEXT ACTION</p><h2>{jobIsActive && activeJob ? `${labelForOperation(activeJob.operation)} in progress` : action.label}</h2><p className="muted">{jobIsActive && activeJob ? `${activeJob.state ? labelForState(activeJob.state) : labelForState(state)} · ${activeJob.progress_percent.toFixed(0)}% complete · ${activeJob.current_stage}` : `${labelForState(state)} · ${action.detail}`}</p></div>
    {!jobIsActive && <button className="primary-button" type="button" onClick={() => onAction(action.action)}>{action.label}</button>}
    {jobIsActive && activeJob && <div className="next-action-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, Math.max(0, activeJob.progress_percent))} aria-label={`${labelForOperation(activeJob.operation)} progress`}><span style={{ width: `${Math.min(100, Math.max(0, activeJob.progress_percent))}%` }} /></div>}
  </section>
}
