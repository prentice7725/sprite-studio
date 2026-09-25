import type { QuickSession, QuickSourceSelection } from '../../api'
import { useQuickText } from './quickText'

interface Props {
  session: QuickSession
  onReplace: () => void
  onPixelize: () => void
  onMakeSprite: () => void
  onSelectSource: (source: QuickSourceSelection) => void
  onOpenStudio: () => void
}

export default function SourcePreview({ session, onReplace, onPixelize, onMakeSprite, onSelectSource, onOpenStudio }: Props) {
  const text = useQuickText()
  const selectedUrl = session.source_selection === 'pixelized' ? session.pixelized_source : session.original_source
  return <section className="panel quick-source-ready" aria-labelledby="quick-source-ready-heading">
    <div className="panel-heading"><div><p className="eyebrow">{text.sourceReady}</p><h2 id="quick-source-ready-heading">{text.chooseSource}</h2></div><span className="step-number">2</span></div>
    <div className="quick-source-hero"><img src={selectedUrl ?? session.original_source} alt={text.selectedSource} /><div><strong>{session.source_kind === 'upload' ? text.uploadedSource : text.legacyGeneratedSource}</strong><p className="muted">{text.originalAvailable}</p><div className="button-row"><button className="secondary-button" type="button" onClick={onReplace}>{text.replaceSource}</button><button className="secondary-button" type="button" onClick={onOpenStudio}>{text.openInStudio}</button></div></div></div>
    {session.pixelized_source && <fieldset className="choice-group quick-source-choice"><legend>{text.spriteSource}</legend><label className="check-row"><input type="radio" name="quick-selected-source" checked={session.source_selection === 'original'} onChange={() => onSelectSource('original')} /> {text.originalSource}</label><label className="check-row"><input type="radio" name="quick-selected-source" checked={session.source_selection === 'pixelized'} onChange={() => onSelectSource('pixelized')} /> {text.pixelizedSource}</label></fieldset>}
    <div className="button-row quick-source-actions"><button className="primary-button" type="button" onClick={onMakeSprite}>{text.makeSprite}</button><button className="secondary-button" type="button" onClick={onPixelize}>{text.pixelizeFirst}</button><a className="secondary-button" href={selectedUrl ?? session.original_source} download>{text.saveSource}</a></div>
  </section>
}
