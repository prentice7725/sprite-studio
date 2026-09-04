import { useMemo, useState } from 'react'

interface CanvasViewerProps {
  src: string | null
  alt: string
  pixelArt?: boolean
  label?: string
}

export default function CanvasViewer({ src, alt, pixelArt = true, label = 'Canvas viewer' }: CanvasViewerProps) {
  const [zoom, setZoom] = useState(100)
  const [grid, setGrid] = useState(false)
  const [checker, setChecker] = useState(true)
  const zoomLabel = useMemo(() => `${zoom}%`, [zoom])

  return <section className="canvas-viewer" aria-label={label}>
    <div className="canvas-toolbar">
      <div className="toolbar-group" aria-label="Canvas zoom">
        <button className="tool-button" type="button" onClick={() => setZoom((value) => Math.max(25, value - 25))} aria-label="Zoom out">−</button>
        <span className="zoom-value">{zoomLabel}</span>
        <button className="tool-button" type="button" onClick={() => setZoom((value) => Math.min(800, value + 25))} aria-label="Zoom in">+</button>
        <button className="tool-button text-button" type="button" onClick={() => setZoom(100)}>Fit</button>
      </div>
      <div className="toolbar-group">
        <button className={`tool-button text-button ${grid ? 'active' : ''}`} type="button" onClick={() => setGrid((value) => !value)} aria-pressed={grid}>Grid</button>
        <button className={`tool-button text-button ${checker ? 'active' : ''}`} type="button" onClick={() => setChecker((value) => !value)} aria-pressed={checker}>Checker</button>
      </div>
    </div>
    <div className={`canvas-stage ${checker ? 'checker' : ''} ${grid ? 'pixel-grid' : ''}`}>
      {src ? <img src={src} alt={alt} className={pixelArt ? 'pixelated' : undefined} style={{ width: `${zoom}%` }} /> : <p className="helper">Select a generated or refined frame to inspect it here.</p>}
    </div>
  </section>
}
