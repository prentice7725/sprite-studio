from pathlib import Path


path = Path("web/src/features/quick/QuickPixelizePanel.tsx")
text = path.read_text(encoding="utf-8")
q = chr(39)
nl = chr(10)

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
description = "    <p className=\"muted\">{text.pixelizeDescription}</p>"
strategy_ui = description + (
    "<fieldset className=\"choice-group\"><legend>Pixel Master strategy</legend>"
    "<div className=\"segmented-options\" role=\"group\" aria-label=\"Pixel Master strategy\">"
    "<button className={strategy === " + q + "preserve" + q + " ? " + q + "active" + q + " : " + q + q + "} type=\"button\" aria-pressed={strategy === " + q + "preserve" + q + "} onClick={() => setStrategy(" + q + "preserve" + q + ")}>Preserve</button>"
    "<button className={strategy === " + q + "reference_pixel_master_128" + q + " ? " + q + "active" + q + " : " + q + q + "} type=\"button\" aria-pressed={strategy === " + q + "reference_pixel_master_128" + q + "} onClick={() => { setStrategy(" + q + "reference_pixel_master_128" + q + "); setSize(128) }}>Stylize · C2</button>"
    "</div>{strategy === " + q + "reference_pixel_master_128" + q + " && <span className=\"helper\">Reference-guided AI pixel-style → 128px redraw. Raw, intermediate, and post artifacts are retained.</span>}</fieldset>"
)
assert description in text
text = text.replace(description, strategy_ui, 1)
sizes = "{[64, 96, 128, 192].map((value) => <button className={size === value ? 'active' : ''} type=\"button\" aria-pressed={size === value} key={value} onClick={() => setSize(value as QuickPixelSize)}>{value}px</button>)}"
sizes_c2 = "{[64, 96, 128, 192].map((value) => <button className={size === value ? 'active' : ''} type=\"button\" disabled={strategy === 'reference_pixel_master_128' && value !== 128} aria-pressed={size === value} key={value} onClick={() => setSize(value as QuickPixelSize)}>{value}px</button>)}"
assert sizes in text
text = text.replace(sizes, sizes_c2, 1)
stats_end = "</div>}" + nl + "    {session.pixelized_source"
artifact_ui = "</div>}{result?.strategy === 'reference_pixel_master_128' && <div className=\"button-row\"><a className=\"secondary-button\" href={result.raw_source}>C2 raw</a>{result.intermediate_source && <a className=\"secondary-button\" href={result.intermediate_source}>C2 intermediate</a>}<a className=\"secondary-button\" href={result.post_source ?? result.output_source}>C2 post</a></div>}" + nl + "    {session.pixelized_source"
assert stats_end in text
text = text.replace(stats_end, artifact_ui, 1)
path.write_text(text, encoding="utf-8")
