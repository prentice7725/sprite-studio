import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { JobStatus, MotionPlan } from '../../api'
import NextActionPanel from './NextActionPanel'

const sequentialPlan = {
  kind: 'motion_plan',
  version: 1,
  animation: 'walk',
  loop: true,
  frames: 8,
  fps: 8,
  strategy: 'KEYPOSE_SEQUENTIAL',
  requested_strategy: 'KEYPOSE_SEQUENTIAL',
  reason: 'quality fallback',
  phases: [],
  key_pose_indices: [0, 4],
  fallback_on_row_quality_fail: null,
} satisfies MotionPlan

const runningJob = {
  job_id: 'job-1',
  operation: 'refine',
  state: 'walk',
  status: 'running',
  current_stage: 'refining',
  progress_percent: 63.4,
  cancel_requested: false,
  attempt: 1,
  parent_job_id: null,
  result: null,
  error: null,
  created_at: '2026-09-16T00:00:00Z',
  started_at: '2026-09-16T00:00:00Z',
  updated_at: '2026-09-16T00:01:00Z',
  finished_at: null,
  elapsed_seconds: 60,
} satisfies JobStatus

afterEach(() => cleanup())

describe('NextActionPanel', () => {
  it('maps a raw pipeline state to the normalize action', () => {
    render(<NextActionPanel state="walk" pipelineStatus="raw" animationQaReady={false} motionPlan={null} sequential={null} activeJob={null} onAction={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'Normalize this row' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Normalize this row' })).toBeEnabled()
  })

  it('prioritizes sequential key poses when the motion plan is active', () => {
    render(<NextActionPanel state="walk" pipelineStatus="raw" animationQaReady={false} motionPlan={sequentialPlan} sequential={null} activeJob={null} onAction={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'Generate key poses' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate key poses' })).toBeEnabled()
  })

  it('replaces the action button with progress while a job is running', () => {
    render(<NextActionPanel state="walk" pipelineStatus="extracted" animationQaReady={false} motionPlan={null} sequential={null} activeJob={runningJob} onAction={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'refine in progress' })).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'refine progress' })).toHaveAttribute('aria-valuenow', '63.4')
    expect(screen.queryByRole('button', { name: 'Refine frames' })).not.toBeInTheDocument()
  })
})
