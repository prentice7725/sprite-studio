# SPDX-License-Identifier: Apache-2.0
"""Sprite Gen Studio Gradio entrypoint.

Run with ``python -m studio.app``. The UI owns interaction; the backend owns
run state and delegates image work to the existing sprite-studio modules.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .backend import anchor_service, batch_service, history_service, qa_service, repair_service, run_manager, spritegen_bridge
from .backend.prompt_service import assemble_for_run, effective_prompt, reset_override, save_override
from .backend.preset_service import list_presets, load_preset, preset_states
from .backend.schemas import StudioRunConfig
from .shared.modes import MODES, SPRITE, STATIC
from .ui.static_mode_ui import build_static_tabs


def _gradio():
    try:
        import gradio as gr
    except ImportError as exc:
        raise SystemExit("Sprite Gen Studio requires Gradio. Install with: pip install -e '.[studio]'") from exc
    return gr


def _load_i18n(locale: str = "ko") -> dict[str, str]:
    path = Path(__file__).parent / "data" / "i18n" / f"{locale}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _provider_markdown() -> str:
    rows = []
    for status in spritegen_bridge.provider_status():
        icon = "●" if status.available else "○"
        rows.append(f"{icon} **{status.name}** — {status.message}")
    return "\n\n".join(rows)


def _state_names(preset: dict[str, Any], directions: list[str], selected: list[str]) -> list[str]:
    entries = preset_states(preset, selected)
    return [f"{direction}_{pose}" for direction in directions for pose in entries]


def _run_state(run_id: str | None) -> tuple[Path, dict[str, Any]]:
    if not run_id:
        raise ValueError("먼저 Project 탭에서 Run을 생성하거나 선택하세요.")
    info = run_manager.load_run(run_id)
    request = spritegen_bridge.request_for(info.path)
    return info.path, request


def _selected_state(direction: str, pose: str) -> str:
    if not direction or not pose:
        raise ValueError("방향과 상태를 선택하세요.")
    return f"{direction}_{pose}"


def _raw_paths(run_dir: Path, request: dict[str, Any], state: str) -> tuple[str | None, str | None]:
    from sprite_studio.spec.layout import raw_rel

    raw = run_dir / raw_rel(request, state)
    raw_original = Path(str(raw) + ".raw.png")
    return (str(raw_original) if raw_original.is_file() else None, str(raw) if raw.is_file() else None)


def _refine_details(report: dict[str, Any], t: dict[str, str]) -> str:
    """Render the Sprite Refine panel described by spec section 12.2."""
    if report.get("kind") != "asset-studio-sprite-refine":
        return "_legacy refine engine (v1): no lattice report_"
    lattice = report["lattice"]
    shared = report["shared"]
    thin = report["thin_feature"]
    clamped = report.get("phase_clamped_frames") or []
    lines = [
        f"**{t.get('refine.lattice', 'Shared Lattice')}** — pitch `{lattice['pitch'][0]} x {lattice['pitch'][1]}` "
        f"(scope `{lattice['scope']}`, locked **{lattice['locked']}**)",
        f"**{t.get('refine.confidence', 'Cell-size Confidence')}** — {lattice['confidence'][0]} / {lattice['confidence'][1]}",
        f"**{t.get('refine.phase', 'Phase Adjustment')}** — offsets "
        + ", ".join(f"`{item['offset'][0]:+.2f}`" for item in report["phases"])
        + (f" · held at bound: frames {clamped}" if clamped else " · none clamped"),
        f"**{t.get('refine.thin_feature', 'Thin-feature Protection')}** — "
        f"{'on' if thin['enabled'] else 'off'}, rescued cells {thin['rescued_cells']}",
        f"**{t.get('refine.palette', 'Palette Summary')}** — {shared['palette_colors']} colors, "
        f"logical `{shared['logical_size'][0]}x{shared['logical_size'][1]}`, scale x{shared['scale']}",
    ]
    for warning in report.get("warnings", []):
        lines.append(f"- WARNING `{warning['code']}` {warning['message']}")
    return "\n\n".join(lines)


def build_app(*, locale: str = "ko"):
    gr = _gradio()
    t = _load_i18n(locale)
    presets = list_presets()
    default_preset = load_preset("sword" if "sword" in presets else presets[0])
    default_dirs = list(default_preset["directions"])
    default_states = list(default_preset["states"])

    with gr.Blocks(title=t["app.title"]) as app:
        current_run = gr.State(None)
        current_state = gr.State(None)

        with gr.Row():
            gr.Markdown(f"# {t['app.title']}")
            provider_badge = gr.Markdown(_provider_markdown())

        # Spec section 12.1: one Studio, two production modes chosen up front. The
        # selector is not cosmetic - it decides which surface exists at all, so an
        # option that belongs to the other mode is never reachable (section 12.4).
        with gr.Row():
            mode_selector = gr.Radio(
                [(MODES[SPRITE].title, SPRITE), (MODES[STATIC].title, STATIC)],
                value=SPRITE,
                label=t.get("mode.select", "Mode"),
            )
            mode_purpose = gr.Markdown(f"_{MODES[SPRITE].purpose}_")

        with gr.Column(visible=True) as sprite_container:
            with gr.Tabs():
                with gr.Tab(t["tab.project"]):
                    with gr.Row():
                        with gr.Column():
                            preset = gr.Dropdown(presets, value=default_preset["id"], label="Preset")
                            run_id = gr.Textbox(label="Run ID", value="sword_a01")
                            character_id = gr.Textbox(label="Character ID", value="sword")
                            description = gr.Textbox(label="Description", value=default_preset.get("character_description", ""))
                            base_image = gr.Image(type="filepath", label="Base Image")
                            provider = gr.Radio(["grok", "codex"], value="grok", label="Provider")
                            generation_profile = gr.Radio(
                                ["direct_pixel", "refine_first"],
                                value=default_preset.get("default_generation_profile", "refine_first"),
                                label="Prompt Profile",
                            )
                            background_policy = gr.Dropdown(
                                ["auto", "green", "magenta", "red", "blue", "transparent"],
                                value=default_preset.get("background_policy", "auto"),
                                label="Background Policy",
                            )
                            directions = gr.CheckboxGroup(default_dirs, value=default_dirs, label="Directions")
                            states = gr.CheckboxGroup(default_states, value=default_states, label="States")
                            create_button = gr.Button(t["run.create"], variant="primary")
                        with gr.Column():
                            project_status = gr.Markdown("Run을 생성하면 상태가 표시됩니다.")
                            run_picker = gr.Dropdown(
                                choices=[info.run_id for info in run_manager.list_runs()],
                                label="Existing Runs",
                                allow_custom_value=False,
                            )
                            refresh_runs = gr.Button("Refresh Runs")

                with gr.Tab(t["tab.generate"]):
                    with gr.Row():
                        with gr.Column():
                            generate_run = gr.Dropdown(label="Run")
                            generate_direction = gr.Dropdown(default_dirs, value="side", label="Direction")
                            generate_pose = gr.Dropdown(default_states, value="attack", label="State")
                            prompt = gr.Textbox(label="Prompt", lines=12)
                            prompt_blocks = gr.Markdown(label="Prompt Assembly Preview")
                            with gr.Row():
                                reset_prompt = gr.Button("RESET PROMPT")
                                save_prompt = gr.Button("SAVE OVERRIDE")
                                generate_button = gr.Button(t["generation.generate"], variant="primary")
                        with gr.Column():
                            raw_preview = gr.Image(label="RAW")
                            normalized_preview = gr.Image(label="NORMALIZED")
                            refined_preview = gr.Image(label="REFINED")
                            # Spec section 12.2 "Sprite Refine display items": the operator
                            # has to see which grid was locked and whether any frame was held
                            # at the phase bound, or a soft result looks like a clean one.
                            refine_details = gr.Markdown(label="Sprite Refine")
                            generate_status = gr.Markdown()
                            with gr.Row():
                                normalize_button = gr.Button(t["normalize.run"])
                                extract_button = gr.Button(t["extract.run"])
                                refine_button = gr.Button("FRAME REFINE")
                            batch_states = gr.CheckboxGroup(
                                choices=_state_names(default_preset, default_dirs, default_states),
                                value=_state_names(default_preset, default_dirs, default_states),
                                label="Batch States",
                            )
                            with gr.Row():
                                batch_normalize = gr.Checkbox(value=True, label="Normalize")
                                batch_refine = gr.Checkbox(value=True, label="Refine")
                                batch_repair = gr.Checkbox(value=True, label=t["repair.batch"])
                                batch_qa = gr.Checkbox(value=True, label="Animation QA")
                                batch_button = gr.Button("RUN BATCH", variant="primary")
                                batch_refresh = gr.Button("REFRESH BATCH")
                            batch_output = gr.Markdown()

                with gr.Tab(t["tab.review"]):
                    review_run = gr.Dropdown(label="Run")
                    review_state = gr.Dropdown(label="State")
                    review_frames = gr.Gallery(label="EXTRACTED FRAMES", columns=4, height="auto")
                    review_refined_frames = gr.Gallery(label="REFINED FRAMES", columns=4, height="auto")
                    review_repair_proposals = gr.Gallery(label=t["repair.proposals"], columns=4, height="auto")
                    review_repaired_frames = gr.Gallery(label=t["repair.frames"], columns=4, height="auto")
                    review_repair_diff = gr.Gallery(label=t["repair.diff"], columns=4, height="auto")
                    repair_candidates = gr.Dropdown(label=t["repair.candidates"], choices=[], multiselect=True)
                    with gr.Row():
                        repair_analyze_button = gr.Button(t["repair.analyze"])
                        repair_safe_button = gr.Button(t["repair.apply_safe"], variant="primary")
                        repair_accept_button = gr.Button(t["repair.accept"])
                        repair_reject_button = gr.Button(t["repair.reject"])
                        repair_undo_button = gr.Button(t["repair.undo"])
                    with gr.Row():
                        repair_adopt_button = gr.Button(t["repair.adopt"], variant="primary")
                        repair_unadopt_button = gr.Button(t["repair.unadopt"])
                    ai_micro_job = gr.Textbox(label=t["repair.ai_job"], interactive=False)
                    ai_micro_inputs = gr.Gallery(label=t["repair.ai_inputs"], columns=2, height="auto")
                    ai_micro_result = gr.Image(type="filepath", label=t["repair.ai_result"])
                    with gr.Row():
                        ai_micro_prepare_button = gr.Button(t["repair.ai_prepare"])
                        ai_micro_apply_button = gr.Button(t["repair.ai_apply"], variant="primary")
                    ai_micro_status = gr.Markdown()
                    repair_output = gr.Markdown()
                    review_qa = gr.Markdown()
                    review_history = gr.Markdown()
                    anchor_direction = gr.Dropdown(choices=default_dirs, value=default_dirs[0] if default_dirs else None, label="Anchor Direction")
                    anchor_index = gr.Number(value=0, precision=0, label="Approved Frame Index")
                    with gr.Row():
                        pin_anchor_button = gr.Button("PIN REVIEW FRAME AS ANCHOR")
                        clear_anchor_button = gr.Button("CLEAR ANCHOR PIN")
                    anchor_output = gr.Markdown()
                    with gr.Row():
                        animation_qa_button = gr.Button("ANIMATION QA", variant="primary")
                        open_curation_button = gr.Button("OPEN CURATION")
                    animation_qa_output = gr.Markdown()
                    curation_output = gr.Markdown()

                with gr.Tab(t["tab.matrix"]):
                    matrix_run = gr.Dropdown(label="Run")
                    matrix_output = gr.Markdown()
                    matrix_refresh = gr.Button("Refresh Matrix")

                with gr.Tab(t["tab.export"]):
                    export_run = gr.Dropdown(label="Run")
                    compose_button = gr.Button("COMPOSE", variant="primary")
                    runtime_button = gr.Button("EXPORT RUNTIME 48×48")
                    export_output = gr.Markdown()

        static_container = build_static_tabs(gr, t)

        def mode_changed(mode_value: str):
            sprite_active = mode_value == SPRITE
            purpose = MODES[mode_value].purpose
            return (
                gr.Column(visible=sprite_active),
                gr.Column(visible=not sprite_active),
                f"_{purpose}_",
            )

        mode_selector.change(mode_changed, mode_selector, [sprite_container, static_container, mode_purpose])

        def preset_changed(preset_id: str):
            data = load_preset(preset_id)
            dirs = list(data["directions"])
            poses = list(data["states"])
            return (
                gr.CheckboxGroup(choices=dirs, value=dirs),
                gr.CheckboxGroup(choices=poses, value=poses),
                data.get("character_description", ""),
                gr.Radio(["direct_pixel", "refine_first"], value=data.get("default_generation_profile", "refine_first")),
                gr.Dropdown(["auto", "green", "magenta", "red", "blue", "transparent"], value=data.get("background_policy", "auto")),
            )

        preset.change(preset_changed, preset, [directions, states, description, generation_profile, background_policy])

        def create_clicked(preset_id, rid, cid, desc, image, selected_provider, selected_profile, selected_background, selected_dirs, selected_states):
            data = load_preset(preset_id)
            image_path = Path(image) if image else None
            config = StudioRunConfig(
                run_id=rid.strip(),
                character_id=cid.strip(),
                provider=selected_provider,
                base_image=image_path,
                directions=tuple(selected_dirs),
                mirrors=dict(data.get("mirror") or {}),
                states=preset_states(data, list(selected_states)),
                cell_size=int(data.get("working_cell", 256)),
                runtime_size=int(data.get("runtime_cell", 48)),
                preset=preset_id,
                description=desc.strip(),
                generation_profile=selected_profile,
                background_policy=selected_background,
                locks=dict(data.get("locks") or {}),
            )
            info = run_manager.create_run(config)
            choices = [item.run_id for item in run_manager.list_runs()]
            states_for_run = list(info.states)
            return (
                info.run_id,
                f"### Created\n`{info.path}`\n\n{len(info.states)} state rows ready.",
                gr.Dropdown(choices=choices, value=info.run_id),
                gr.Dropdown(choices=choices, value=info.run_id),
                gr.Dropdown(choices=choices, value=info.run_id),
                gr.Dropdown(choices=choices, value=info.run_id),
                gr.Dropdown(choices=choices, value=info.run_id),
                gr.Dropdown(choices=states_for_run, value=states_for_run[0]),
                gr.CheckboxGroup(choices=states_for_run, value=states_for_run),
                gr.Dropdown(choices=list(info.directions), value=info.directions[0] if info.directions else None),
            )

        create_button.click(
            create_clicked,
            [preset, run_id, character_id, description, base_image, provider, generation_profile, background_policy, directions, states],
            [current_run, project_status, run_picker, generate_run, review_run, matrix_run, export_run, current_state, batch_states, anchor_direction],
        )

        def refresh_clicked():
            choices = [item.run_id for item in run_manager.list_runs()]
            return tuple(gr.Dropdown(choices=choices) for _ in range(5))

        refresh_runs.click(refresh_clicked, outputs=[run_picker, generate_run, review_run, matrix_run, export_run])

        def run_selected(run_id_value):
            if not run_id_value:
                return None, gr.Dropdown(choices=[]), gr.Dropdown(choices=[]), "", gr.Dropdown(choices=[])
            info = run_manager.load_run(run_id_value)
            poses = sorted({state.split("_", 1)[1] for state in info.states if "_" in state})
            return info.run_id, gr.Dropdown(choices=list(info.states), value=info.states[0]), gr.Dropdown(choices=poses, value=poses[0] if poses else None), "", gr.Dropdown(choices=list(info.directions), value=info.directions[0] if info.directions else None)

        run_picker.change(run_selected, run_picker, [current_run, review_state, generate_pose, project_status, anchor_direction])
        generate_run.change(lambda value: value, generate_run, current_run)

        def load_prompt_clicked(run_value, direction, pose):
            path, request = _run_state(run_value)
            state = _selected_state(direction, pose)
            text, source = effective_prompt(path, request, state)
            if source == "override":
                preview = "### Override\n\n사용자 override prompt가 provider에 전달됩니다."
            else:
                result = assemble_for_run(path, request, state)
                preview = "\n\n".join(f"### {name}\n{value}" for name, value in result.blocks.items())
            return text, preview, f"Prompt source: `{source}`"

        for trigger in (generate_direction.change, generate_pose.change):
            trigger(load_prompt_clicked, [generate_run, generate_direction, generate_pose], [prompt, prompt_blocks, generate_status])

        def save_prompt_clicked(run_value, direction, pose, text):
            path, _ = _run_state(run_value)
            state = _selected_state(direction, pose)
            saved = save_override(path, state, text)
            return f"Prompt override saved: `{saved}`"

        save_prompt.click(save_prompt_clicked, [generate_run, generate_direction, generate_pose, prompt], generate_status)

        def reset_prompt_clicked(run_value, direction, pose):
            path, request = _run_state(run_value)
            state = _selected_state(direction, pose)
            reset_override(path, state)
            text, source = effective_prompt(path, request, state)
            result = assemble_for_run(path, request, state)
            preview = "\n\n".join(f"### {name}\n{value}" for name, value in result.blocks.items())
            return text, preview, f"Prompt source: `{source}`"

        reset_prompt.click(reset_prompt_clicked, [generate_run, generate_direction, generate_pose], [prompt, prompt_blocks, generate_status])

        def generate_clicked(run_value, direction, pose):
            path, request = _run_state(run_value)
            state = _selected_state(direction, pose)
            report = spritegen_bridge.generate_state(path, state)
            raw_original, raw = _raw_paths(path, request, state)
            return raw_original, raw, f"Generated `{state}` via `{report['provider']}`."

        generate_button.click(generate_clicked, [generate_run, generate_direction, generate_pose], [raw_preview, normalized_preview, generate_status])

        def normalize_clicked(run_value, direction, pose):
            path, request = _run_state(run_value)
            state = _selected_state(direction, pose)
            report = spritegen_bridge.normalize_state(path, state)
            _, normalized = _raw_paths(path, request, state)
            return normalized, f"Normalized `{state}`: {report['output_size'][0]}×{report['output_size'][1]}"

        normalize_button.click(normalize_clicked, [generate_run, generate_direction, generate_pose], [normalized_preview, generate_status])

        def extract_clicked(run_value, direction, pose):
            path, _ = _run_state(run_value)
            state = _selected_state(direction, pose)
            code = spritegen_bridge.extract_frames(path, state)
            return f"Extract finished for `{state}` (exit {code}).\n\n{qa_service.summary(path, state)}"

        extract_button.click(extract_clicked, [generate_run, generate_direction, generate_pose], generate_status)

        def refine_clicked(run_value, direction, pose):
            path, request = _run_state(run_value)
            state = _selected_state(direction, pose)
            result = spritegen_bridge.refine_frames(path, state)
            from sprite_studio.spec.layout import frames_dir_rel
            refined = str(path / frames_dir_rel(request, state) / "refined" / "frame-0.png")
            return refined, _refine_details(result.report, t), f"Refined `{state}` with shared grid/palette/baseline/scale locks."

        refine_button.click(
            refine_clicked,
            [generate_run, generate_direction, generate_pose],
            [refined_preview, refine_details, generate_status],
        )

        def review_clicked(run_value, state):
            path, request = _run_state(run_value)
            manifest_path = path / "frames" / "frames-manifest.json"
            if not manifest_path.is_file():
                return [], [], [], [], [], gr.Dropdown(choices=[], value=[]), "아직 repair 결과가 없습니다.", "아직 extract 결과가 없습니다.", history_service.summary(path, state)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            row = next((item for item in manifest.get("rows", []) if item.get("state") == state), None)
            if not row:
                return [], [], [], [], [], gr.Dropdown(choices=[], value=[]), "선택한 state의 프레임이 없습니다.", "선택한 state의 프레임이 없습니다.", history_service.summary(path, state)
            files = [str(path / rel) for rel in row.get("files", [])]
            from sprite_studio.spec.layout import frames_dir_rel
            refined_dir = path / frames_dir_rel(request, state) / "refined"
            refined_files = [str(item) for item in sorted(refined_dir.glob("frame-*.png"))] if refined_dir.is_dir() else []
            repair = repair_service.review_data(path, state)
            return (
                files, refined_files, repair["proposal_files"], repair["repaired_files"], repair["diff_files"],
                gr.Dropdown(choices=repair["candidate_choices"], value=[]), repair_service.summary(path, state),
                qa_service.summary(path, state), history_service.summary(path, state),
            )

        review_state.change(
            review_clicked, [review_run, review_state],
            [review_frames, review_refined_frames, review_repair_proposals, review_repaired_frames,
             review_repair_diff, repair_candidates, repair_output, review_qa, review_history],
        )

        def _repair_updates(path: Path, state: str):
            data = repair_service.review_data(path, state)
            return (
                data["proposal_files"], data["repaired_files"], data["diff_files"],
                gr.Dropdown(choices=data["candidate_choices"], value=[]), repair_service.summary(path, state),
                qa_service.summary(path, state),
            )

        def repair_analyze_clicked(run_value, state):
            path, _ = _run_state(run_value)
            repair_service.analyze_state(path, state)
            return _repair_updates(path, state)

        def repair_safe_clicked(run_value, state):
            path, _ = _run_state(run_value)
            repair_service.analyze_state(path, state)
            repair_service.repair_state(path, state)
            return _repair_updates(path, state)

        def repair_decide_clicked(run_value, state, selected, accept):
            path, _ = _run_state(run_value)
            ids = set(selected or [])
            if not ids:
                raise ValueError("repair candidate를 하나 이상 선택하세요.")
            repair_service.decide_candidates(path, state, ids, accept=accept)
            return _repair_updates(path, state)

        def repair_undo_clicked(run_value, state):
            path, _ = _run_state(run_value)
            repair_service.clear_repairs(path, state)
            return _repair_updates(path, state)

        def repair_adopt_clicked(run_value, state):
            path, _ = _run_state(run_value)
            repair_service.adopt_repaired(path, state)
            return _repair_updates(path, state)

        def repair_unadopt_clicked(run_value, state):
            path, _ = _run_state(run_value)
            repair_service.unadopt_repaired(path, state)
            return _repair_updates(path, state)

        def ai_micro_prepare_clicked(run_value, state, selected):
            path, _ = _run_state(run_value)
            job = repair_service.prepare_ai_micro_fix(path, state, set(selected or []))
            return job["job_id"], [job["before_path"], job["mask_path"]], f"Prepared `{job['job_dir']}`"

        def ai_micro_apply_clicked(run_value, state, job_id, result_path):
            path, _ = _run_state(run_value)
            if not result_path:
                raise ValueError("AI Micro Fix 결과 PNG를 선택하세요.")
            result = repair_service.apply_ai_micro_fix(path, state, job_id, Path(result_path))
            return (*_repair_updates(path, state),
                    f"Applied AI Micro Fix `{job_id}` — {result['ai_micro_fix']['pixels_changed']} logical pixel(s).")

        repair_outputs = [review_repair_proposals, review_repaired_frames, review_repair_diff,
                          repair_candidates, repair_output, review_qa]
        repair_analyze_button.click(repair_analyze_clicked, [review_run, review_state], repair_outputs)
        repair_safe_button.click(repair_safe_clicked, [review_run, review_state], repair_outputs)
        repair_accept_button.click(lambda run_value, state, selected: repair_decide_clicked(run_value, state, selected, True),
                                   [review_run, review_state, repair_candidates], repair_outputs)
        repair_reject_button.click(lambda run_value, state, selected: repair_decide_clicked(run_value, state, selected, False),
                                   [review_run, review_state, repair_candidates], repair_outputs)
        repair_undo_button.click(repair_undo_clicked, [review_run, review_state], repair_outputs)
        repair_adopt_button.click(repair_adopt_clicked, [review_run, review_state], repair_outputs)
        repair_unadopt_button.click(repair_unadopt_clicked, [review_run, review_state], repair_outputs)
        ai_micro_prepare_button.click(
            ai_micro_prepare_clicked, [review_run, review_state, repair_candidates],
            [ai_micro_job, ai_micro_inputs, ai_micro_status],
        )
        ai_micro_apply_button.click(
            ai_micro_apply_clicked, [review_run, review_state, ai_micro_job, ai_micro_result],
            repair_outputs + [ai_micro_status],
        )

        def pin_anchor_clicked(run_value, state, index):
            path, _ = _run_state(run_value)
            try:
                anchor_service.pin(path, state, int(index))
                return anchor_service.summary(path)
            except (SystemExit, ValueError) as exc:
                return f"⚠ Anchor pin failed: {exc}"

        pin_anchor_button.click(pin_anchor_clicked, [review_run, review_state, anchor_index], anchor_output)

        def clear_anchor_clicked(run_value, direction):
            path, _ = _run_state(run_value)
            try:
                anchor_service.clear(path, direction)
                return anchor_service.summary(path)
            except (SystemExit, ValueError) as exc:
                return f"⚠ Anchor clear failed: {exc}"

        clear_anchor_button.click(clear_anchor_clicked, [review_run, anchor_direction], anchor_output)

        def batch_clicked(run_value, selected_states, normalize, refine, repair, qa):
            path, _ = _run_state(run_value)
            job_id = batch_service.start_batch(path, list(selected_states or []), normalize=normalize, refine=refine, repair=repair, qa=qa)
            return f"Batch `{job_id}` started.\n\n{batch_service.status_text(path)}"

        batch_button.click(batch_clicked, [generate_run, batch_states, batch_normalize, batch_refine, batch_repair, batch_qa], batch_output)

        def batch_refresh_clicked(run_value):
            path, _ = _run_state(run_value)
            return batch_service.status_text(path)

        batch_refresh.click(batch_refresh_clicked, generate_run, batch_output)

        def animation_qa_clicked(run_value, state):
            path, _ = _run_state(run_value)
            result = spritegen_bridge.animation_qa(path, state)
            status = "PASS" if result.ok and not result.warnings else "WARN"
            return f"### Animation QA: {status}\n\n`{state}` — {len(result.warnings)} warning(s)\n\n{qa_service.summary(path, state)}"

        animation_qa_button.click(animation_qa_clicked, [review_run, review_state], animation_qa_output)

        def curation_clicked(run_value):
            path, _ = _run_state(run_value)
            url = spritegen_bridge.launch_curation(path, lang=locale)
            return f"Curation server started: [{url}]({url})"

        open_curation_button.click(curation_clicked, review_run, curation_output)

        def matrix_clicked(run_value):
            if not run_value:
                return "런을 선택하세요."
            info = run_manager.load_run(run_value)
            statuses = run_manager.get_run_status(run_value)
            lines = ["| State | Status |", "|---|---|"]
            icons = {"not-generated": "⬜", "raw": "🟡", "normalized": "🟠", "extracted": "🔵", "refined": "🟣", "repaired": "🟢", "warning": "⚠️", "failed": "❌", "accepted": "✅"}
            for state in info.states:
                lines.append(f"| `{state}` | {icons.get(statuses[state], '⬜')} {statuses[state]} |")
            return "\n".join(lines)

        matrix_refresh.click(matrix_clicked, matrix_run, matrix_output)
        matrix_run.change(matrix_clicked, matrix_run, matrix_output)

        def compose_clicked(run_value):
            path, _ = _run_state(run_value)
            code = spritegen_bridge.extract_frames(path)
            if code != 0:
                return "Extract가 실패해서 Compose를 중단했습니다.\n\n" + qa_service.summary(path)
            from .backend.export_service import compose

            compose(path)
            return f"Compose 완료: `{path / 'sprite-sheet-alpha.png'}`\n`{path / 'manifest.json'}`"

        compose_button.click(compose_clicked, export_run, export_output)

        def runtime_clicked(run_value):
            path, _ = _run_state(run_value)
            from .backend.export_service import build_runtime
            result = build_runtime(path)
            width, height = result["size"]
            return f"Runtime export 완료 ({width}×{height}, NEAREST): `{result['atlas']}`\n`{result['manifest']}`"

        runtime_button.click(runtime_clicked, export_run, export_output)

        app.load(lambda: _provider_markdown(), outputs=provider_badge)
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("SPRITE_STUDIO_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SPRITE_STUDIO_PORT", "7860")))
    parser.add_argument("--share", action="store_true")
    parser.add_argument("--locale", choices=("ko", "en"), default="ko")
    args = parser.parse_args(argv)
    build_app(locale=args.locale).launch(server_name=args.host, server_port=args.port, share=args.share)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
