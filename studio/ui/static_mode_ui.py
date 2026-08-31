# SPDX-License-Identifier: MIT
"""Static Mode UI (spec §12.3).

    STATIC
    ├─ PROJECT
    ├─ GENERATE
    ├─ REFINE
    ├─ CLEANUP
    ├─ TILE / LAYER
    ├─ QA
    └─ EXPORT

Built in its own module rather than inside ``studio/app.py`` for the reason
§12.4 gives: each mode shows only its own options. Keeping the two surfaces
physically separate is what makes that enforceable — there is no shared widget
that could drift into offering a baseline lock on a tile set, or a seam check
on a character.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from studio.backend import static_service
from studio.backend.preset_service import list_static_presets, load_static_preset
from studio.backend.schemas import StaticProjectConfig
from studio.static_mode.prompt import StaticPromptAssembler
from studio.static_mode.refine import DITHER_MODES


ASSET_TYPES = ("PIXEL_SCENE", "TILE_SET", "PROP_OBJECT", "FLAT_SCENE")


def _projects() -> list[str]:
    return [info.project_id for info in static_service.list_projects()]


def _warning_lines(warnings: list[dict[str, Any]]) -> str:
    if not warnings:
        return "- warnings: none"
    return "\n".join(f"- ⚠️ `{item.get('code', '?')}` {item.get('message', '')}" for item in warnings)


def build_static_tabs(gr, t: dict[str, str]):
    """Create the Static Mode tab set and wire it. Returns the container."""
    presets = list_static_presets()
    default_preset = load_static_preset("pixel_scene" if "pixel_scene" in presets else presets[0])

    with gr.Column(visible=False) as container:
        with gr.Tabs():
            with gr.Tab(t.get("static.tab.project", "PROJECT")):
                with gr.Row():
                    with gr.Column():
                        preset = gr.Dropdown(presets, value=default_preset["id"], label=t.get("static.preset", "Preset"))
                        project_id = gr.Textbox(label="Project ID", value="battlefield_bg_001")
                        description = gr.Textbox(label=t.get("static.description", "Scene / Object Description"),
                                                 value=default_preset.get("description", ""), lines=3)
                        asset_type = gr.Dropdown(list(ASSET_TYPES), value=default_preset["asset_type"],
                                                 label=t.get("static.asset_type", "Asset Type"))
                        provider = gr.Radio(["grok", "codex"], value="grok", label="Provider")
                        tileable = gr.Checkbox(value=default_preset.get("tileable", False),
                                               label=t.get("static.tileable", "Tileable"))
                        layer_intent = gr.Textbox(label=t.get("static.layer_intent", "Layer Intent"),
                                                  value=default_preset.get("layer_intent", "none"))
                        export_width = gr.Number(value=default_preset["export_size"][0], precision=0, label="Export Width")
                        export_height = gr.Number(value=default_preset["export_size"][1], precision=0, label="Export Height")
                        create_button = gr.Button(t.get("static.project.create", "CREATE PROJECT"), variant="primary")
                    with gr.Column():
                        project_status = gr.Markdown("Create a Static project to begin.")
                        project_picker = gr.Dropdown(choices=_projects(), label="Existing Projects", allow_custom_value=False)
                        refresh_projects = gr.Button("Refresh Projects")

            with gr.Tab(t.get("static.tab.generate", "GENERATE")):
                generate_project = gr.Dropdown(choices=_projects(), label="Project")
                static_prompt = gr.Textbox(label="Prompt", lines=12)
                prompt_issues = gr.Markdown()
                build_prompt_button = gr.Button(t.get("static.prompt.build", "BUILD PROMPT"), variant="primary")
                import_image = gr.Image(type="filepath", label=t.get("static.import", "Import Source Image"))
                asset_name = gr.Textbox(value="scene", label="Asset Name")
                import_button = gr.Button(t.get("static.import.run", "IMPORT AS RAW ASSET"))
                generate_status = gr.Markdown()

            with gr.Tab(t.get("static.tab.refine", "REFINE")):
                refine_project = gr.Dropdown(choices=_projects(), label="Project")
                refine_asset_name = gr.Textbox(value="scene", label="Asset Name")
                with gr.Row():
                    dither_mode = gr.Dropdown(list(DITHER_MODES), value="off",
                                              label=t.get("static.dither", "Dither Mode"))
                    fft_search = gr.Checkbox(value=True, label=t.get("static.fft", "FFT Candidate Search"))
                    run_cleanup = gr.Checkbox(value=True, label=t.get("static.cleanup", "Cleanup"))
                refine_button = gr.Button(t.get("static.refine.run", "STATIC REFINE"), variant="primary")
                refined_preview = gr.Image(label="REFINED (logical)")
                # §12.3 "Static Refine 표시 항목": candidates, chosen grid, palette/dither,
                # seam preview, tile wrap preview.
                fft_candidates = gr.Markdown(label="FFT candidate list")
                selected_grid = gr.Markdown(label="Selected grid")
                palette_summary = gr.Markdown(label="Palette / dither mode")
                refine_status = gr.Markdown()

            with gr.Tab(t.get("static.tab.cleanup", "CLEANUP")):
                # Its own section (spec §12.3), not just a refine toggle: tuning a
                # speck threshold must not re-run the grid search and re-decide the
                # lattice underneath the operator.
                cleanup_project = gr.Dropdown(choices=_projects(), label="Project")
                cleanup_asset_name = gr.Textbox(value="scene", label="Asset Name")
                orphan_max_area = gr.Number(value=2, precision=0, label=t.get("static.orphan", "Orphan Max Area (px)"))
                hole_max_area = gr.Number(value=4, precision=0, label=t.get("static.hole", "Hole Fill Max Area (px)"))
                cleanup_button = gr.Button(t.get("static.cleanup.run", "RUN CLEANUP"), variant="primary")
                cleaned_preview = gr.Image(label="CLEANED (logical)")
                cleanup_output = gr.Markdown()

            with gr.Tab(t.get("static.tab.tile", "TILE / LAYER")):
                tile_project = gr.Dropdown(choices=_projects(), label="Project")
                tile_asset_name = gr.Textbox(value="scene", label="Asset Name")
                with gr.Row():
                    seam_button = gr.Button(t.get("static.seam.check", "SEAM CHECK"))
                    seam_repair_button = gr.Button(t.get("static.seam.repair", "SEAM REPAIR"))
                wrap_preview = gr.Image(label=t.get("static.wrap", "Tile Wrap Preview"))
                seam_output = gr.Markdown()
                with gr.Row():
                    layer_button = gr.Button(t.get("static.layers", "SPLIT LAYERS"))
                    cutout_button = gr.Button(t.get("static.cutout", "OBJECT CUTOUT"))
                layer_gallery = gr.Gallery(label="LAYERS", columns=3, height="auto")
                layer_output = gr.Markdown()

            with gr.Tab(t.get("static.tab.qa", "QA")):
                qa_project = gr.Dropdown(choices=_projects(), label="Project")
                qa_asset_name = gr.Textbox(value="scene", label="Asset Name")
                qa_button = gr.Button(t.get("static.qa.run", "STATIC QA"), variant="primary")
                qa_output = gr.Markdown()

            with gr.Tab(t.get("static.tab.export", "EXPORT")):
                export_project = gr.Dropdown(choices=_projects(), label="Project")
                export_asset_name = gr.Textbox(value="scene", label="Asset Name")
                export_button = gr.Button(t.get("static.export.run", "EXPORT"), variant="primary")
                export_output = gr.Markdown()

    pickers = [project_picker, generate_project, refine_project, cleanup_project, tile_project, qa_project, export_project]

    def _refresh_all():
        choices = _projects()
        return [gr.Dropdown(choices=choices) for _ in pickers]

    def preset_changed(preset_id: str):
        data = load_static_preset(preset_id)
        return (
            data.get("description", ""),
            gr.Dropdown(list(ASSET_TYPES), value=data["asset_type"]),
            data.get("tileable", False),
            data.get("layer_intent", "none"),
            data["export_size"][0],
            data["export_size"][1],
        )

    preset.change(
        preset_changed, preset,
        [description, asset_type, tileable, layer_intent, export_width, export_height],
    )

    def create_clicked(preset_id, pid, desc, atype, prov, tile, intent, width, height):
        data = load_static_preset(preset_id)
        overrides = dict(data.get("refine") or {})
        config = StaticProjectConfig(
            project_id=str(pid).strip(),
            provider=prov,
            asset_type=atype,
            style_profile=data.get("style_profile", "pixel_scene"),
            description=desc or "",
            tileable=bool(tile),
            export_size=(int(width), int(height)),
            layer_intent=str(intent or "none"),
            refine=overrides,
        )
        info = static_service.create_project(config)
        summary = (
            f"Created `{info.project_id}` — {info.asset_type}, tileable={info.tileable}, "
            f"export {info.export_size[0]}×{info.export_size[1]}\n\n`{info.path}`"
        )
        return [summary, *_refresh_all()]

    create_button.click(
        create_clicked,
        [preset, project_id, description, asset_type, provider, tileable, layer_intent, export_width, export_height],
        [project_status, *pickers],
    )
    refresh_projects.click(lambda: _refresh_all(), outputs=pickers)

    def build_prompt_clicked(pid):
        if not pid:
            return "", "Select a project first."
        info = static_service.load_project(pid)
        result = StaticPromptAssembler().assemble(
            info.project_id, info.description, asset_type=info.asset_type,
            style_profile=info.style_profile, tileable=info.tileable,
            layer_intent=info.layer_intent, background_policy=info.background_policy,
            export_size=info.export_size,
        )
        issues = "\n".join(f"- `{issue.severity}` **{issue.code}** {issue.message}" for issue in result.issues)
        return result.final_prompt, issues or "- prompt validation: clean"

    build_prompt_button.click(build_prompt_clicked, generate_project, [static_prompt, prompt_issues])

    def import_clicked(pid, image_path, asset):
        if not pid or not image_path:
            return "Select a project and an image."
        info = static_service.load_project(pid)
        target = static_service.import_asset(info, Path(image_path), asset=str(asset or "scene").strip())
        return f"Imported raw asset: `{target}`"

    import_button.click(import_clicked, [generate_project, import_image, asset_name], generate_status)

    def refine_clicked(pid, asset, dither, fft, cleanup):
        if not pid:
            return None, "", "", "", "Select a project first."
        info = static_service.load_project(pid)
        # UI toggles are project overrides, persisted the same way a preset's are,
        # so the report always records the settings that actually ran.
        overrides = dict(info.refine or {}) | {"dither_mode": dither, "fft_candidate_search": bool(fft)}
        info = replace(info, refine=overrides)
        report = static_service.refine_asset(info, str(asset or "scene").strip(), cleanup=bool(cleanup))
        candidates = report.get("fft_candidates") or []
        candidate_text = "\n".join(
            f"- axis `{item['axis']}` period **{item['period']}** (power {item['power']})" for item in candidates[:8]
        ) or "- no FFT candidates (search disabled or no periodicity found)"
        grid = report["grid"]
        grid_text = (
            f"- pitch **{grid['pitch'][0]} × {grid['pitch'][1]}**\n"
            f"- phase {grid['phase'][0]} / {grid['phase'][1]}\n"
            f"- confidence {grid['confidence'][0]} / {grid['confidence'][1]}\n"
            f"- locked: **{grid['locked']}** · coarse-to-fine: {grid['coarse_to_fine']}"
        )
        palette = report["palette"]
        palette_text = (
            f"- colors: **{palette['colors']}** · dither: `{palette['dither']}`\n"
            f"- unused entries: {palette['usage'].get('unused', [])}"
        )
        logical = report["sampling"]["logical_size"]
        status = f"Refined `{report['asset']}` → logical **{logical[0]}×{logical[1]}**\n\n" + _warning_lines(report.get("warnings", []))
        return report["output"], candidate_text, grid_text, palette_text, status

    refine_button.click(
        refine_clicked,
        [refine_project, refine_asset_name, dither_mode, fft_search, run_cleanup],
        [refined_preview, fft_candidates, selected_grid, palette_summary, refine_status],
    )

    def cleanup_clicked(pid, asset, orphan, hole):
        if not pid:
            return None, "Select a project first."
        info = static_service.load_project(pid)
        name = str(asset or "scene").strip()
        report = static_service.cleanup_asset(
            info, name, orphan_max_area=int(orphan), fill_max_area=int(hole)
        )
        lines = [
            f"- hardened **{report['alpha']['softened_pixels']}** semi-transparent pixels",
            f"- removed **{report['orphans']['removed_components']}** orphan components "
            f"({report['orphans']['removed_pixels']} px, max area {report['orphan_max_area']})",
            f"- filled **{report['holes']['filled_regions']}** enclosed holes ({report['holes']['filled_pixels']} px)",
        ]
        return str(info.path / "refined" / f"{name}.png"), "\n".join(lines)

    cleanup_button.click(
        cleanup_clicked,
        [cleanup_project, cleanup_asset_name, orphan_max_area, hole_max_area],
        [cleaned_preview, cleanup_output],
    )

    def seam_clicked(pid, asset, repair: bool):
        if not pid:
            return None, "Select a project first."
        info = static_service.load_project(pid)
        report = static_service.check_tileability(info, str(asset or "scene").strip(), repair=repair)
        lines = [
            f"- horizontal ΔE: **{report['horizontal_delta_e']}**",
            f"- vertical ΔE: **{report['vertical_delta_e']}**",
            f"- threshold: {report['threshold']} · ok: **{report['ok']}**",
        ]
        if "repair" in report:
            lines.append(f"- repaired {report['repair']['blended_pixels']} edge pixels → ok: **{report['repair']['after']['ok']}**")
        return report["wrap_preview"], "\n".join(lines)

    seam_button.click(lambda p, a: seam_clicked(p, a, False), [tile_project, tile_asset_name], [wrap_preview, seam_output])
    seam_repair_button.click(lambda p, a: seam_clicked(p, a, True), [tile_project, tile_asset_name], [wrap_preview, seam_output])

    def layers_clicked(pid, asset, cutout: bool):
        if not pid:
            return [], "Select a project first."
        info = static_service.load_project(pid)
        name = str(asset or "scene").strip()
        report = static_service.process_layers(info, name, cutout=cutout)
        if cutout:
            return [report["output"]], (
                f"- cutout kept **{report['kept_pixels']}** px, removed {report['removed_pixels']}\n"
                f"- background colour: {report['background_color']}"
            )
        directory = Path(report["output_dir"])
        files = [str(path) for path in sorted(directory.glob("*.png"))]
        summary = "\n".join(f"- **{layer['name']}**: {layer['pixels']} px" for layer in report["layers"])
        return files, f"{summary}\n\n- recomposes to the input: **{report['round_trips']}**"

    layer_button.click(lambda p, a: layers_clicked(p, a, False), [tile_project, tile_asset_name], [layer_gallery, layer_output])
    cutout_button.click(lambda p, a: layers_clicked(p, a, True), [tile_project, tile_asset_name], [layer_gallery, layer_output])

    def qa_clicked(pid, asset):
        if not pid:
            return "Select a project first."
        info = static_service.load_project(pid)
        report = static_service.static_qa(info, str(asset or "scene").strip())
        head = f"**{'PASS' if report['ok'] else 'FAIL'}** — {report['asset_type']}"
        warnings = "\n".join(
            f"- `{item['severity']}` **{item['code']}** {item['message']}" for item in report["warnings"]
        ) or "- no warnings"
        return f"{head}\n\n{warnings}"

    qa_button.click(qa_clicked, [qa_project, qa_asset_name], qa_output)

    def export_clicked(pid, asset):
        if not pid:
            return "Select a project first."
        info = static_service.load_project(pid)
        path = static_service.export_asset(info, str(asset or "scene").strip())
        return f"Exported (NEAREST, {info.export_size[0]}×{info.export_size[1]}): `{path}`"

    export_button.click(export_clicked, [export_project, export_asset_name], export_output)
    return container
