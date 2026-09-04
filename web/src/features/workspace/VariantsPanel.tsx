import type { ReviewData } from '../../api'

interface VariantsPanelProps {
  review: ReviewData | null
}

export default function VariantsPanel({ review }: VariantsPanelProps) {
  const attempts = review?.generation_variants ?? []
  const revisions = review?.revision_variants ?? []
  return <section className="panel variants-panel"><div className="panel-heading"><div><p className="eyebrow">VARIANTS / REVISIONS</p><h3>Generation history</h3></div><span className="count-badge">{attempts.length + revisions.length}</span></div>{attempts.length || revisions.length ? <div className="variant-list">{attempts.map((variant) => <article className="variant-card" key={variant.id}><div><strong>{variant.id}</strong><small>{variant.provider}{variant.model ? ` · ${variant.model}` : ''}{variant.timestamp ? ` · ${variant.timestamp}` : ''}</small></div>{variant.raw_asset ? <a href={variant.raw_asset} target="_blank" rel="noreferrer">Open raw</a> : <span className="helper">asset unavailable</span>}</article>)}{revisions.map((variant) => <article className="variant-card" key={variant.id}><div><strong>{variant.label}</strong><small>Revision · {variant.frames ?? '—'} frames</small></div>{variant.raw_asset ? <a href={variant.raw_asset} target="_blank" rel="noreferrer">Open take</a> : <span className="helper">{variant.exists ? 'asset unavailable' : 'not generated'}</span>}</article>)}</div> : <p className="helper">No alternate generations or declared takes for this state yet.</p>}<p className="helper">History is read-only here; repair adoption remains an explicit action in the Repair tool.</p></section>
}
