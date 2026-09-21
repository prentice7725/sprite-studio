import { useState } from 'react'
import type { QuickDither, QuickFrameCount, QuickMotion, QuickOutline, QuickPalette, QuickPixelMasterStrategy, QuickPixelSize, QuickSession } from '../../api'
import { useQuickText } from './quickText'

interface Props { session: QuickSession; busy: boolean; onSubmit: (options: Record<string, unknown>) => void; onBack: () => void }

const motions: QuickMotion[] = ['idle', 'walk', 'run', 'jump', 'attack', 'hurt', 'custom']

export default function MakeSpritePanel({ session, busy, onSubmit, onBack }: Props) {
  const text = useQuickText()
  const [motion, setMotion] = useState<QuickMotion>((session.motion as QuickMotion) || 'idle')
  const [customMotion, setCustomMotion] = useState('')
  const [directions, setDirections] = useState<1 | 4 | 8>(1)
  const [frames, setFrames] = useState<QuickFrameCount>(6)
  const [pixelize, setPixelize] = useState(false)
  const [pixelMasterStrategy, setPixelMasterStrategy] = useState<QuickPixelMasterStrategy>('reference_pixel_master_128')
  const [pixelSize, setPixelSize] = useState<QuickPixelSize>(128)
  const [palette, setPalette] = useState<QuickPalette>('auto')
  const [dither, setDither] = useState<QuickDither>('none')
  const [outline, setOutline] = useState<QuickOutline>('preserve')
  const [backgroundCleanup, setBackgroundCleanup] = useState(false)
  return <section className="panel quick-make-panel" aria-labelledby="quick-make-heading">
    <div className="panel-heading"><div><p className="eyebrow">{text.makeSprite}</p><h2 id="quick-make-heading">{text.createAnimation}</h2></div><span className="step-number">3</span></div>
    <p className="muted">{text.quickInternalDescription}</p>
    <div className="form-row"><label>{text.motion}<select value={motion} onChange={(event) => setMotion(event.target.value as QuickMotion)}>{motions.map((value) => <option key={value} value={value}>{text[value]}</option>)}</select></label><label>{text.directions}<select value={directions} onChange={(event) => setDirections(Number(event.target.value) as 1 | 4 | 8)}><option value={1}>{text.oneDirection}</option><option value={4}>{text.fourDirections}</option><option value={8}>{text.eightDirections}</option></select></label></div>
    {motion === 'custom' && <label>{text.customMotionDescription}<input value={customMotion} onChange={(event) => setCustomMotion(event.target.value)} placeholder="Describe the motion" required /></label>}
    <label>{text.frames}<select value={frames} onChange={(event) => setFrames(Number(event.target.value) as QuickFrameCount)}><option value={4}>4</option><option value={6}>6</option><option value={8}>8</option></select></label>
    <label className="check-row"><input type="checkbox" checked={pixelize} onChange={(event) => setPixelize(event.target.checked)} /> {text.pixelizeBefore}<span className="check-detail">{pixelMasterStrategy === 'reference_pixel_master_128' ? 'C2 · 128px' : `${pixelSize}px`} · {palette === 'auto' ? text.auto : `${palette} ${text.colors}`}</span></label>
    {pixelize && <fieldset className="choice-group"><legend>Pixel Master strategy</legend><div className="segmented-options" role="group" aria-label="Pixel Master strategy"><button className={pixelMasterStrategy === 'reference_pixel_master_128' ? 'active' : ''} type="button" aria-pressed={pixelMasterStrategy === 'reference_pixel_master_128'} onClick={() => { setPixelMasterStrategy('reference_pixel_master_128'); setPixelSize(128) }}>Stylize · C2</button><button className={pixelMasterStrategy === 'preserve' ? 'active' : ''} type="button" aria-pressed={pixelMasterStrategy === 'preserve'} onClick={() => setPixelMasterStrategy('preserve')}>{text.preserve}</button></div>{pixelMasterStrategy === 'reference_pixel_master_128' && <span className="helper">Reference-guided AI redraw. The source reference is retained through the C2 pipeline.</span>}</fieldset>}
    {pixelize && <details className="advanced-options" open><summary>{text.pixelizeSettings}</summary><div className="form-row"><label>{text.logicalSize}<select value={pixelSize} disabled={pixelMasterStrategy === 'reference_pixel_master_128'} onChange={(event) => setPixelSize(Number(event.target.value) as QuickPixelSize)}><option value={64}>64</option><option value={96}>96</option><option value={128}>128</option><option value={192}>192</option></select></label><label>{text.palette}<select value={palette} onChange={(event) => setPalette(event.target.value === 'auto' ? 'auto' : Number(event.target.value) as QuickPalette)}><option value="auto">{text.auto}</option><option value={16}>16</option><option value={24}>24</option><option value={32}>32</option><option value={48}>48</option></select></label></div>{pixelMasterStrategy === 'preserve' && <><div className="form-row"><label>{text.dither}<select value={dither} onChange={(event) => setDither(event.target.value as QuickDither)}><option value="none">{text.none}</option><option value="ordered-low">{text.low}</option><option value="ordered">{text.ordered}</option></select></label><label>{text.outline}<select value={outline} onChange={(event) => setOutline(event.target.value as QuickOutline)}><option value="preserve">{text.preserve}</option><option value="auto">{text.auto}</option></select></label></div><label className="check-row"><input type="checkbox" checked={backgroundCleanup} onChange={(event) => setBackgroundCleanup(event.target.checked)} /> {text.cleanup}</label></>}</details>}
    <div className="quick-selection-note" role="status">{text.selectedSource}: <strong>{session.source_selection === 'pixelized' ? text.pixelizedSource : text.originalSource}</strong></div>
    <div className="button-row"><button className="primary-button" type="button" disabled={busy} onClick={() => onSubmit({ motion, custom_motion: customMotion, directions, frames, pixelize, pixel_size: pixelMasterStrategy === 'reference_pixel_master_128' ? 128 : pixelSize, palette, dither, outline, background_cleanup: backgroundCleanup, sprite_source: session.source_selection, strategy: pixelMasterStrategy, generation_strategy: 'AUTO' })}>{busy ? text.starting : text.makeSprite}</button><button className="secondary-button" type="button" onClick={onBack}>{text.back}</button></div>
  </section>
}
