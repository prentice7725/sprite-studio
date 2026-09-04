import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Provider, SpritePreset } from '../../api'

export interface CreateAssetDraft {
  runId: string
  characterId: string
  provider: Provider
  preset: SpritePreset
  directions: string[]
  stateNames: string[]
  baseImage: File | null
}

interface CreateAssetFormProps {
  presets: SpritePreset[]
  providerChoices: Provider[]
  busy: boolean
  onSubmit: (draft: CreateAssetDraft) => void
}

function providerLabel(provider: Provider): string {
  return provider === 'codex' ? 'Codex image_gen' : 'Grok'
}

export default function CreateAssetForm({ presets, providerChoices, busy, onSubmit }: CreateAssetFormProps) {
  const [presetId, setPresetId] = useState('')
  const [directions, setDirections] = useState<string[]>([])
  const [stateNames, setStateNames] = useState<string[]>([])

  const preset = presets.find((item) => item.id === presetId) ?? presets[0] ?? null

  useEffect(() => {
    if (!preset) {
      setPresetId('')
      setDirections([])
      setStateNames([])
      return
    }
    setPresetId(preset.id)
    setDirections(preset.directions)
    setStateNames(Object.keys(preset.states))
  }, [preset?.id])

  function toggle(items: string[], value: string, setItems: (next: string[]) => void) {
    setItems(items.includes(value) ? items.filter((item) => item !== value) : [...items, value])
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!preset || !directions.length || !stateNames.length) return
    const form = new FormData(event.currentTarget)
    onSubmit({
      runId: String(form.get('run_id') || '').trim(),
      characterId: String(form.get('character_id') || '').trim(),
      provider: String(form.get('provider') || providerChoices[0] || 'grok') as Provider,
      preset,
      directions,
      stateNames,
      baseImage: (form.get('base_image') as File | null) ?? null,
    })
  }

  return <section className="panel hero-panel"><div className="panel-heading"><div><p className="eyebrow">ASSET SETUP</p><h2>Create a character asset</h2></div><span className="step-number">01</span></div><p className="muted">Choose a data-backed preset first. Directions, animations, cell sizes, locks, and generation policy are inherited from the preset.</p><form className="form-stack" onSubmit={submit}><div className="form-row"><label>Asset name<input name="run_id" defaultValue="hero-demo" required /></label><label>Character identity<input name="character_id" defaultValue="hero" required /></label></div><label>Preset<select name="preset" value={preset?.id ?? ''} onChange={(event) => setPresetId(event.target.value)} required><option value="" disabled>{presets.length ? 'Select a preset' : 'Loading presets…'}</option>{presets.map((item) => <option key={item.id} value={item.id}>{item.display_name} · {item.character_description}</option>)}</select><span className="helper">Preset values are loaded from GET /api/presets/{'{preset_id}'}.</span></label><div className="form-row"><fieldset className="choice-group"><legend>Directions</legend>{preset?.directions.map((direction) => <label className="check-row" key={direction}><input type="checkbox" checked={directions.includes(direction)} onChange={() => toggle(directions, direction, setDirections)} />{direction}</label>)}</fieldset><fieldset className="choice-group"><legend>Animations</legend>{preset ? Object.keys(preset.states).map((state) => <label className="check-row" key={state}><input type="checkbox" checked={stateNames.includes(state)} onChange={() => toggle(stateNames, state, setStateNames)} />{state}<span className="check-detail">{preset.states[state].frames} frames</span></label>) : <span className="helper">Choose a preset first.</span>}</fieldset></div><details className="advanced-options"><summary>Advanced generation</summary><div className="form-stack compact-stack"><label>Provider<select name="provider" defaultValue={providerChoices[0]}>{providerChoices.map((item) => <option key={item} value={item}>{providerLabel(item)}</option>)}</select><span className="helper">Only providers reported as image-generation capable are shown.</span></label>{preset && <div className="preset-summary"><span>Working cell <strong>{preset.working_cell}px</strong></span><span>Runtime cell <strong>{preset.runtime_cell}px</strong></span><span>Profile <strong>{preset.default_generation_profile}</strong></span></div>}</div></details><label>Base image <span className="optional">optional</span><input name="base_image" type="file" accept="image/*" /><span className="helper">Use an existing identity image, or let the run start from the preset identity prompt.</span></label><button className="primary-button" disabled={busy || !preset || !directions.length || !stateNames.length} type="submit">{busy ? 'Creating asset…' : 'Create asset'}</button></form></section>
}
