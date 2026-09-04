import { useEffect, useRef, useState } from 'react'

interface AnimationTimelineProps {
  frames: string[]
  activeFrame: number
  fps?: number
  loop?: boolean
  repairedFrames?: string[]
  onFrameChange: (index: number) => void
}

export default function AnimationTimeline({ frames, activeFrame, fps = 8, loop = true, repairedFrames = [], onFrameChange }: AnimationTimelineProps) {
  const [playing, setPlaying] = useState(false)
  const [shouldLoop, setShouldLoop] = useState(loop)
  const timer = useRef<number | null>(null)
  const current = frames.length ? Math.min(activeFrame, frames.length - 1) : 0

  useEffect(() => {
    if (!playing || frames.length < 2) return undefined
    timer.current = window.setInterval(() => {
      const next = current + 1
      if (next >= frames.length) {
        if (shouldLoop) onFrameChange(0)
        else setPlaying(false)
      } else onFrameChange(next)
    }, 1000 / Math.max(1, fps))
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current)
    }
  }, [current, fps, frames.length, onFrameChange, playing, shouldLoop])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!frames.length || (event.target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName))) return
      if (event.key === 'ArrowLeft') { event.preventDefault(); onFrameChange(Math.max(0, current - 1)) }
      if (event.key === 'ArrowRight') { event.preventDefault(); onFrameChange(Math.min(frames.length - 1, current + 1)) }
      if (event.key === ' ') { event.preventDefault(); setPlaying((value) => !value) }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [current, frames.length, onFrameChange])

  return <section className="timeline" aria-label="Animation timeline">
    <div className="timeline-heading"><div><p className="eyebrow">FRAME TIMELINE</p><h3>{frames.length ? `${frames.length} frames` : 'No frames yet'}</h3></div><div className="timeline-controls"><button className="tool-button" type="button" disabled={!frames.length} onClick={() => onFrameChange(Math.max(0, current - 1))} aria-label="Previous frame">◀</button><button className="tool-button text-button" type="button" disabled={!frames.length} onClick={() => setPlaying((value) => !value)}>{playing ? 'Pause' : 'Play'}</button><button className="tool-button" type="button" disabled={!frames.length} onClick={() => onFrameChange(Math.min(frames.length - 1, current + 1))} aria-label="Next frame">▶</button><label className="timeline-toggle"><input type="checkbox" checked={shouldLoop} onChange={(event) => setShouldLoop(event.target.checked)} />Loop</label></div></div>
    <div className="timeline-strip" role="listbox" tabIndex={0} aria-label="Frames" aria-activedescendant={frames.length ? `timeline-frame-${current}` : undefined}>
      {frames.length ? frames.map((frame, index) => <button id={`timeline-frame-${index}`} className={`timeline-frame ${index === current ? 'selected' : ''}`} type="button" role="option" aria-selected={index === current} key={`${frame}-${index}`} onClick={() => onFrameChange(index)}><img src={frame} alt={`Frame ${index + 1}`} loading="lazy" /><span>F{index}</span>{repairedFrames[index] && <i className="timeline-marker repaired" title="Repaired frame" />}</button>) : <p className="helper">Run Extract or Refine to populate the timeline.</p>}
    </div>
    <div className="timeline-footer"><span>Frame {frames.length ? current + 1 : 0} / {frames.length}</span><span>{fps} FPS · ← → to scrub · Space to play</span></div>
  </section>
}
