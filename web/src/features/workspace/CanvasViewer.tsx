import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

interface CanvasViewerProps {
  src: string | null
  alt: string
  pixelArt?: boolean
  label?: string
}

type ZoomMode = 'fit' | 1 | 2 | 4 | 8

const zoomSteps: Array<1 | 2 | 4 | 8> = [1, 2, 4, 8]

function identityFromAlt(alt: string): string {
  return alt.split(' frame ')[0]
}

export default function CanvasViewer({ src, alt, pixelArt = true, label = 'Canvas viewer' }: CanvasViewerProps) {
  const [zoom, setZoom] = useState<ZoomMode>('fit')
  const [grid, setGrid] = useState(false)
  const [checker, setChecker] = useState(true)
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null)
  const [suppressStaleSource, setSuppressStaleSource] = useState(false)
  const previous = useRef<{ identity: string; src: string | null }>({ identity: identityFromAlt(alt), src })
  const identity = identityFromAlt(alt)

  useEffect(() => {
    const prior = previous.current
    const identityChanged = prior.identity !== identity
    const sourceDidNotChange = prior.src === src
    setSuppressStaleSource(Boolean(src && identityChanged && sourceDidNotChange))
    previous.current = { identity, src }
    setNaturalSize(null)
  }, [identity, src])

  const zoomLabel = useMemo(() => zoom === 'fit' ? 'Fit' : `${zoom}×`, [zoom])
  const visibleSrc = suppressStaleSource ? null : src
  const numericZoom = zoom === 'fit' ? null : zoom

  function stepZoom(direction: -1 | 1) {
    if (zoom === 'fit') {
      setZoom(direction > 0 ? 2 : 1)
      return
    }
    const current = zoomSteps.indexOf(zoom)
    const next = Math.max(0, Math.min(zoomSteps.length - 1, current + direction))
    setZoom(zoomSteps[next])
  }

  const imageStyle: CSSProperties = zoom === 'fit'
    ? { width: 'auto', height: 'auto', maxWidth: '100%', maxHeight: '100%' }
    : naturalSize
      ? { width: `${naturalSize.width * zoom}px`, height: `${naturalSize.height * zoom}px`, maxWidth: 'none', maxHeight: 'none' }
      : { width: `${zoom * 100}%`, maxWidth: 'none', maxHeight: 'none' }

  const stageStyle = numericZoom && grid
    ? { '--pixel-grid-size': `${numericZoom}px` } as CSSProperties
    : undefined

  return <section className="canvas-viewer" aria-label={label}>
    <div className="canvas-toolbar">
      <div className="toolbar-group" aria-label="Canvas zoom">
        <button className="tool-button" type="button" onClick={() => stepZoom(-1)} disabled={zoom === 1} aria-label="Zoom out">−</button>
        <span className="zoom-value">{zoomLabel}</span>
        <button className="tool-button" type="button" onClick={() => stepZoom(1)} disabled={zoom === 8} aria-label="Zoom in">+</button>
        <button className={`tool-button text-button ${zoom === 'fit' ? 'active' : ''}`} type="button" onClick={() => setZoom('fit')}>Fit</button>
        {pixelArt && zoomSteps.map((value) => <button className={`tool-button text-button zoom-preset ${zoom === value ? 'active' : ''}`} type="button" key={value} onClick={() => setZoom(value)}>{value}×</button>)}
      </div>
      <div className="toolbar-group">
        {pixelArt && <button className={`tool-button text-button ${grid ? 'active' : ''}`} type="button" disabled={zoom === 'fit'} onClick={() => setGrid((value) => !value)} aria-pressed={grid}>Grid</button>}
        <button className={`tool-button text-button ${checker ? 'active' : ''}`} type="button" onClick={() => setChecker((value) => !value)} aria-pressed={checker}>Checker</button>
      </div>
    </div>
    <div className={`canvas-stage ${checker ? 'checker' : ''} ${grid && numericZoom ? 'pixel-grid' : ''}`} style={stageStyle}>
      {visibleSrc ? <img src={visibleSrc} alt={alt} className={pixelArt ? 'pixelated' : undefined} style={imageStyle} onLoad={(event) => setNaturalSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} /> : <p className="helper">{suppressStaleSource ? 'Loading the selected animation…' : 'Select a generated or refined frame to inspect it here.'}</p>}
    </div>
  </section>
}
