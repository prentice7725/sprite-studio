import { useState } from 'react'
import type { FormEvent } from 'react'
import type { Provider, QuickBackground, QuickMotion, QuickStyle } from '../../api'
import { useQuickText } from './quickText'

export interface QuickSourceDraft {
  sourceKind: 'upload' | 'prompt'
  file: File | null
  referenceFile: File | null
  prompt: string
  motion: QuickMotion
  customMotion: string
  style: QuickStyle
  background: QuickBackground
  notes: string
  provider: Provider
}

interface Props {
  providerChoices: Provider[]
  busy: boolean
  onSubmit: (draft: QuickSourceDraft) => void
}

const motions: QuickMotion[] = ['idle', 'walk', 'run', 'jump', 'attack', 'hurt', 'custom']

export default function SourceInputPanel({ providerChoices, busy, onSubmit }: Props) {
  const text = useQuickText()
  const [sourceKind, setSourceKind] = useState<'upload' | 'prompt'>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [referenceFile, setReferenceFile] = useState<File | null>(null)
  const [prompt, setPrompt] = useState('')
  const [motion, setMotion] = useState<QuickMotion>('idle')
  const [customMotion, setCustomMotion] = useState('')
  const [style, setStyle] = useState<QuickStyle>('pixel-art')
  const [background, setBackground] = useState<QuickBackground>('transparent')
  const [notes, setNotes] = useState('')
  const [provider, setProvider] = useState<Provider>(providerChoices[0] ?? 'grok')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit({ sourceKind, file, referenceFile, prompt, motion, customMotion, style, background, notes, provider })
  }

  return <section className="panel quick-input-panel" aria-labelledby="quick-source-heading">
    <div className="panel-heading"><div><p className="eyebrow">{text.sourceFirst}</p><h2 id="quick-source-heading">{text.sourceHeading}</h2></div><span className="step-number">1</span></div>
    <p className="muted">{text.sourceDescription}</p>
    <form className="form-stack" onSubmit={submit}>
      <fieldset className="choice-group">
        <legend>{text.source}</legend>
        <label className="check-row"><input type="radio" name="quick-source" checked={sourceKind === 'upload'} onChange={() => setSourceKind('upload')} /> {text.uploadImage}</label>
        <label className="check-row"><input type="radio" name="quick-source" checked={sourceKind === 'prompt'} onChange={() => setSourceKind('prompt')} /> {text.promptSource}</label>
      </fieldset>
      {sourceKind === 'upload' ? <label>{text.sourceImage}<input type="file" accept="image/*" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /><span className="helper">{text.imageHint}</span></label> : <>
        <label>{text.characterPrompt}<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={4} placeholder="A small forest ranger with a red scarf and a wooden bow" required /></label>
        <label>{text.referenceImage} <span className="optional">{text.optional}</span><input type="file" accept="image/*" onChange={(event) => setReferenceFile(event.target.files?.[0] ?? null)} /></label>
      </>}
      <div className="form-row">
        <label>{text.motion}<select value={motion} onChange={(event) => setMotion(event.target.value as QuickMotion)}>{motions.map((value) => <option key={value} value={value}>{text[value]}</option>)}</select></label>
        <label>{text.style}<select value={style} onChange={(event) => setStyle(event.target.value as QuickStyle)}><option value="pixel-art">{text.pixelArt}</option><option value="cel-shaded">{text.celShaded}</option><option value="hand-painted">{text.handPainted}</option><option value="3d-render">{text.render3d}</option></select></label>
      </div>
      {motion === 'custom' && <label>{text.customMotionDescription}<input value={customMotion} onChange={(event) => setCustomMotion(event.target.value)} placeholder="A careful wave while keeping both feet planted" required /></label>}
      <div className="form-row">
        <label>{text.background}<select value={background} onChange={(event) => setBackground(event.target.value as QuickBackground)}><option value="transparent">{text.transparent}</option><option value="chroma">{text.chromaKey}</option></select></label>
        <label>{text.provider}<select value={provider} onChange={(event) => setProvider(event.target.value as Provider)} onFocus={() => { if (providerChoices.length && !providerChoices.includes(provider)) setProvider(providerChoices[0]) }}>{providerChoices.map((item) => <option key={item} value={item}>{item === 'codex' ? 'Codex image_gen' : 'Grok'}</option>)}</select></label>
      </div>
      <label>{text.notes} <span className="optional">{text.optional}</span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} placeholder={text.notesPlaceholder} /></label>
      <button className="primary-button" type="submit" disabled={busy}>{busy ? text.preparingSource : sourceKind === 'upload' ? text.useThisSource : text.generateSource}</button>
    </form>
  </section>
}