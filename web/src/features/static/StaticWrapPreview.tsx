interface StaticWrapPreviewProps {
  src: string | null
  tileable: boolean
  report?: Record<string, unknown> | null
}

export default function StaticWrapPreview({ src, tileable, report }: StaticWrapPreviewProps) {
  if (!tileable) return null
  const horizontal = report?.horizontal_seam_ok ?? report?.horizontal_ok
  const vertical = report?.vertical_seam_ok ?? report?.vertical_ok
  return <section className="wrap-preview" aria-label="Static 3 by 3 wrap preview"><div className="panel-heading"><div><p className="eyebrow">TILE CONTEXT</p><h3>3 × 3 wrap preview</h3></div><span className="mode-badge">TILEABLE</span></div>{src ? <div className="wrap-grid">{Array.from({ length: 9 }, (_, index) => <div className="wrap-cell" key={index}><img src={src} alt={index === 4 ? 'Center tile' : 'Wrapped tile preview'} loading="lazy" /></div>)}</div> : <p className="helper">Run seam check after refining a tile to preview its repeating context.</p>}<div className="seam-status"><span>{horizontal === undefined ? 'Horizontal seam pending' : `Horizontal seam ${horizontal ? 'pass' : 'warning'}`}</span><span>{vertical === undefined ? 'Vertical seam pending' : `Vertical seam ${vertical ? 'pass' : 'warning'}`}</span></div></section>
}
