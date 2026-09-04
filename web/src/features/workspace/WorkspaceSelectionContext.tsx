import { createContext, useContext, type ReactNode } from 'react'
import type { RunSummary } from '../../api'

export interface WorkspaceSelection {
  activeAssetId: string
  activeAsset: RunSummary | null
  activeState: string
  activeFrame: number
  setActiveAsset: (runId: string) => void
  setActiveState: (state: string) => void
  setActiveFrame: (frame: number) => void
}

interface WorkspaceSelectionProviderProps {
  runs: RunSummary[]
  activeAssetId: string
  activeState: string
  activeFrame: number
  onAssetChange: (runId: string) => void
  onStateChange: (state: string) => void
  onFrameChange: (frame: number) => void
  children: ReactNode
}

const WorkspaceSelectionContext = createContext<WorkspaceSelection | null>(null)

export function WorkspaceSelectionProvider({ runs, activeAssetId, activeState, activeFrame, onAssetChange, onStateChange, onFrameChange, children }: WorkspaceSelectionProviderProps) {
  const activeAsset = runs.find((run) => run.run_id === activeAssetId) ?? null
  return <WorkspaceSelectionContext.Provider value={{ activeAssetId, activeAsset, activeState, activeFrame, setActiveAsset: onAssetChange, setActiveState: onStateChange, setActiveFrame: onFrameChange }}>{children}</WorkspaceSelectionContext.Provider>
}

export function useWorkspaceSelection(): WorkspaceSelection {
  const selection = useContext(WorkspaceSelectionContext)
  if (!selection) throw new Error('useWorkspaceSelection must be used inside WorkspaceSelectionProvider')
  return selection
}
