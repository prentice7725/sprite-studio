import type { RunSummary } from '../../api'
import { useWorkspaceSelection } from '../workspace/WorkspaceSelectionContext'

interface AssetLibraryProps {
  runs: RunSummary[]
}

export default function AssetLibrary({ runs }: AssetLibraryProps) {
  const selection = useWorkspaceSelection()
  return <section className="asset-library" aria-label="Asset library"><div className="library-heading"><div><p className="eyebrow">ASSET LIBRARY</p><h2>Characters</h2></div><span className="count-badge">{runs.length}</span></div>{runs.length ? <div className="asset-tree">{runs.map((run) => <div className="asset-tree-item" key={run.run_id}><button className={`asset-tree-root ${selection.activeAssetId === run.run_id ? 'selected' : ''}`} type="button" onClick={() => selection.setActiveAsset(run.run_id)}><span aria-hidden="true">▾</span><strong>{run.character_id}</strong><small>{run.preset}</small></button>{selection.activeAssetId === run.run_id && <div className="asset-tree-children">{run.states.map((state) => <button className={`asset-tree-state ${selection.activeState === state ? 'selected' : ''}`} type="button" key={state} onClick={() => { selection.setActiveAsset(run.run_id); selection.setActiveState(state) }}><span className="mini-status" aria-hidden="true" />{state}</button>)}</div>}</div>)}</div> : <p className="helper">No assets yet. Create one from Project.</p>}</section>
}
