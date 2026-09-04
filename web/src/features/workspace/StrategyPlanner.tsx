import type { GenerationStrategy, MotionPlan, SequentialGenerationResponse } from '../../api'

interface StrategyPlannerProps {
  value: GenerationStrategy
  plan: MotionPlan | null
  sequential: SequentialGenerationResponse | null
  busy: boolean
  sequentialBusy: string
  onChange: (strategy: GenerationStrategy) => void
  onSave: () => void
  onGenerateKeyPoses: () => void
  onApproveKeyPoses: (indices: number[]) => void
  onGenerateInbetweens: () => void
}

const options: Array<{ id: GenerationStrategy; label: string; hint: string }> = [
  { id: 'AUTO', label: 'Auto', hint: 'Use the data policy and frame count.' },
  { id: 'ROW_FAST', label: 'Row fast', hint: 'One provider call for the complete row.' },
  { id: 'KEYPOSE_SEQUENTIAL', label: 'Keypose sequential', hint: 'Plan accepted key poses and inbetweens.' },
]

export default function StrategyPlanner({ value, plan, sequential, busy, sequentialBusy, onChange, onSave, onGenerateKeyPoses, onApproveKeyPoses, onGenerateInbetweens }: StrategyPlannerProps) {
  return <section className="panel strategy-panel"><div className="panel-heading"><div><p className="eyebrow">GENERATION STRATEGY</p><h3>Plan before provider work</h3></div><span className="mode-badge">P2</span></div><div className="strategy-options" role="radiogroup" aria-label="Generation strategy">{options.map((option) => <label className={`strategy-option ${value === option.id ? 'selected' : ''}`} key={option.id}><input type="radio" name="generation-strategy" value={option.id} checked={value === option.id} onChange={() => onChange(option.id)} /><span><strong>{option.label}</strong><small>{option.hint}</small></span></label>)}</div><button className="secondary-button" disabled={busy} type="button" onClick={onSave}>{busy ? 'Planning…' : 'Save strategy & build Motion Plan'}</button>{plan && <div className="motion-plan"><div className="plan-summary"><span>Resolved <strong>{plan.strategy}</strong></span><span>{plan.frames} frames</span><span>{plan.fps} FPS</span></div><p className="helper">{plan.reason}</p><div className="phase-track" aria-label="Motion phases">{plan.phases.map((phase) => <span className={phase.role === 'key' ? 'key-phase' : 'between-phase'} key={`${phase.index}-${phase.id}`}><strong>{phase.id}</strong><small>{phase.role === 'key' ? 'K' : '·'}</small></span>)}</div><p className="helper">Key poses: {plan.key_pose_indices.map((index) => `F${index}`).join(', ') || 'none'} · Sequential image execution will consume this persisted plan.</p>{plan.strategy === 'KEYPOSE_SEQUENTIAL' && <div className="sequential-actions"><button className="secondary-button" disabled={sequentialBusy !== ''} type="button" onClick={onGenerateKeyPoses}>{sequentialBusy === 'key-poses' ? 'Generating key poses…' : 'Generate key poses'}</button>{sequential?.key_poses.length ? <div className="sequential-assets">{sequential.key_poses.map((item) => <span className="sequential-asset" key={item.index}>F{item.index} · {item.phase} <strong>{item.status}</strong></span>)}</div> : null}<button className="secondary-button" disabled={sequentialBusy !== '' || (sequential?.key_poses.filter((item) => item.status === 'generated').length ?? 0) < 2} type="button" onClick={() => onApproveKeyPoses((sequential?.key_poses ?? []).filter((item) => item.status === 'generated').map((item) => item.index))}>{sequentialBusy === 'approve' ? 'Approving…' : 'Approve generated key poses'}</button><button className="primary-button" disabled={sequentialBusy !== '' || sequential?.status !== 'key_poses_approved'} type="button" onClick={onGenerateInbetweens}>{sequentialBusy === 'inbetweens' ? 'Generating inbetweens…' : 'Generate bidirectional inbetweens'}</button></div>}</div>}</section>
}
