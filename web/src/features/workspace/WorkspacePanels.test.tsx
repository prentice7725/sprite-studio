import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReviewData } from '../../api'
import { WorkspaceContextPanel } from './WorkspacePanels'

const review = {
  frames: ['/extracted-0.png', '/extracted-1.png'],
  refined_frames: ['/refined-0.png', '/refined-1.png'],
  repair_proposals: ['/proposal-0.png', '/proposal-1.png'],
  repaired_frames: ['/repaired-0.png', '/repaired-1.png'],
  repair_diff: ['/diff-0.png', '/diff-1.png'],
  repair_candidates: [],
  repair_summary: '',
  qa_summary: '',
  history_summary: '',
} satisfies ReviewData

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('WorkspaceContextPanel review comparison', () => {
  it('starts with refined/repaired sources and changes View A independently', () => {
    render(<WorkspaceContextPanel frames={review.frames} activeFrame={0} fps={8} loop rawAsset="" state="walk" review={review} onFrameChange={vi.fn()} />)

    const sourceA = screen.getByRole('combobox', { name: 'Review source A' })
    const sourceB = screen.getByRole('combobox', { name: 'Review source B' })
    expect(sourceA).toHaveValue('refined')
    expect(sourceB).toHaveValue('repaired')
    expect(screen.getByAltText('Refined walk frame 1')).toBeInTheDocument()
    expect(screen.getByAltText('Repaired walk frame 1')).toBeInTheDocument()

    fireEvent.change(sourceA, { target: { value: 'diff' } })

    expect(sourceA).toHaveValue('diff')
    expect(screen.getByAltText('Diff walk frame 1')).toBeInTheDocument()
    expect(sourceB).toHaveValue('repaired')
  })

  it('keeps both views valid when only one review source exists', () => {
    const onlyRefined = {
      ...review,
      frames: [],
      repair_proposals: [],
      repaired_frames: [],
      repair_diff: [],
    } satisfies ReviewData

    render(<WorkspaceContextPanel frames={[]} activeFrame={0} fps={8} loop rawAsset="" state="walk" review={onlyRefined} onFrameChange={vi.fn()} />)

    expect(screen.getByRole('combobox', { name: 'Review source A' })).toHaveValue('refined')
    expect(screen.getByRole('combobox', { name: 'Review source B' })).toHaveValue('refined')
    expect(screen.getAllByAltText('Refined walk frame 1')).toHaveLength(2)
  })
})
