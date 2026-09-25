import { useState } from 'react'
import type { FormEvent } from 'react'
import { useQuickText } from './quickText'

export interface QuickSourceDraft {
  file: File | null
}

interface Props {
  busy: boolean
  onSubmit: (draft: QuickSourceDraft) => void
}

export default function SourceInputPanel({ busy, onSubmit }: Props) {
  const text = useQuickText()
  const [file, setFile] = useState<File | null>(null)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit({ file })
  }

  return <section className="panel quick-input-panel" aria-labelledby="quick-source-heading">
    <div className="panel-heading"><div><p className="eyebrow">{text.sourceFirst}</p><h2 id="quick-source-heading">{text.sourceHeading}</h2></div><span className="step-number">1</span></div>
    <p className="muted">{text.sourceDescription}</p>
    <form className="form-stack" onSubmit={submit}>
      <label>{text.sourceImage}<input type="file" accept="image/*" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /><span className="helper">{text.imageHint}</span></label>
      <button className="primary-button" type="submit" disabled={busy}>{busy ? text.preparingSource : text.useThisSource}</button>
    </form>
  </section>
}
