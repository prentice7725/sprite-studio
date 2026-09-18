from pathlib import Path


path = Path("web/src/features/quick/QuickPixelizePanel.tsx")
text = path.read_text(encoding="utf-8")
nl = "\n"
q = chr(39)

text = text.replace(
    "QuickDither, QuickPalette, QuickPixelSize, QuickSession, QuickSourceSelection, QuickPixelizeResult, QuickOutline",
    "QuickDither, QuickPalette, QuickPixelSize, QuickSession, QuickSourceSelection, QuickPixelizeResult, QuickOutline, QuickPixelMasterStrategy",
    1,
)
text = text.replace(
    "  const [subjectMode, setSubjectMode] = useState<SubjectMode>(" + q + "auto" + q + ")",
    "  const [strategy, setStrategy] = useState<QuickPixelMasterStrategy>(" + q + "preserve" + q + ")" + nl
    + "  const [subjectMode, setSubjectMode] = useState<SubjectMode>(" + q + "auto" + q + ")",
    1,
)
text = text.replace(
    "    onRun({ size, detail, palette",
    "    onRun({ strategy, size: strategy === " + q + "reference_pixel_master_128" + q + " ? 128 : size, detail, palette",
    1,
)
marker = "    <p className=\"muted\">{text.pixelizeDescription}</p>"
insert = marker + (
    "<fieldset className=\"choice-group\"><legend>Pixel Master strategy</legend>"
    "<div className=\"segmented-options\" role=\"group\" aria-label=\"Pixel Master strategy\">"
    "<button className={strategy === " + q + "preserve" + q + " ? " + q + "active" + q + " : " + q + q + "} type=\"button\" aria-pressed={strategy === " + q + "preserve" + q + "} onClick={() => setStrategy(" + q + "preserve" + q + ")}>Preserve</button>"
    "<button className={strategy === " + q + "reference_pixel_master_128" + q + " ? " + q + "active" + q + " : " + q + q + "} type=\"button\" aria-pressed={strategy === " + q + "reference_pixel_master_128" + q + "} onClick={() => { setStrategy(" + q + "reference_pixel_master_128" + q + "); setSize(128) }}>Stylize · C2</button>"
    "</div>{strategy === " + q + "reference_pixel_master_128" + q + " && <span className=\"helper\">Reference-guided AI pixel-style → 128px redraw. Raw, intermediate, and post artifacts are retained.</span>}</fieldset>"
)
assert marker in text
text = text.replace(marker, insert, 1)
old_sizes = "{[64, 96, 128, 192].map((value) => <button className={size === value ? 'active' : ''} type=\"button\" aria-pressed={size === value} key={value} onClick={() => setSize(value as QuickPixelSize)}>{value}px</button>)}"
new_sizes = "{[64, 96, 128, 192].map((value) => <button className={size === value ? 'active' : ''} type=\"button\" disabled={strategy === 'reference_pixel_master_128' && value !== 128} aria-pressed={size === value} key={value} onClick={() => setSize(value as QuickPixelSize)}>{value}px</button>)}"
assert old_sizes in text
text = text.replace(old_sizes, new_sizes, 1)
marker2 = "    {result && <div className=\"stat-grid static-stats\"><div className=\"stat\"><span>{text.spriteSize}</span><strong>{result.logical_size[0]} × {result.logical_size[1]}</strong></div><div className=\"stat\"><span>{text.palette}</span><strong>{result.palette_size} {text.colors}</strong></div></div>}"
insert2 = marker2 + "{result?.strategy === 'reference_pixel_master_128' && <div className=\"button-row\"><a className=\"secondary-button\" href={result.raw_source}>C2 raw</a>{result.intermediate_source && <a className=\"secondary-button\" href={result.intermediate_source}>C2 intermediate</a>}<a className=\"secondary-button\" href={result.post_source ?? result.output_source}>C2 post</a></div>}"
assert marker2 in text
path.write_text(text.replace(marker2, insert2, 1), encoding="utf-8")
