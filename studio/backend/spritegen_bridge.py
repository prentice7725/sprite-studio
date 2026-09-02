# SPDX-License-Identifier: Apache-2.0
"""The only boundary between Studio and the existing sprite-studio engine."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sprite_studio.frames import extract
from sprite_studio.gen import generate_image as generate_one
from sprite_studio.gen import normalize_grok_row
from sprite_studio.gen import prepare
from sprite_studio.spec.layout import guide_rel, raw_rel

from .prompt_service import effective_prompt
from .schemas import ProviderStatus
from studio.core.prompt import PromptValidator
from studio.shared.config import load_normalize_quality_settings


class NormalizeQualityFailed(RuntimeError):
    """The normalized row did not clear the Subject Validity / Row-Level
    Acceptance Gate (`SPRITE_STUDIO_GENERATION_NORMALIZE_HARDENING_DIRECTIVE.md`
    §3/§6): promoting it would let a malformed generation reach Extract/Refine/
    Anchor as if it were valid. Carries the parsed report — batch_service and
    the UI surface it instead of a bare exit code (directive §21)."""

    def __init__(self, state: str, report: dict[str, Any]):
        self.state = state
        self.report = report
        cell_reasons = [
            f"cell {subject.get('index')}: {', '.join(subject.get('reasons') or []) or 'invalid'}"
            for subject in (report.get("subjects") or [])
            if not subject.get("valid", True)
        ]
        detail = "; ".join(cell_reasons) if cell_reasons else (report.get("error") or report.get("result") or "fail")
        valid = report.get("valid_subjects")
        expected = report.get("expected_subjects")
        counts = f"{valid}/{expected} valid subjects " if valid is not None and expected is not None else ""
        super().__init__(f"normalize failed for '{state}': {counts}({detail})")


def provider_status() -> list[ProviderStatus]:
    result: list[ProviderStatus] = []
    for name in ("grok", "codex"):
        found = shutil.which(name)
        if not found:
            result.append(ProviderStatus(name, False, f"{name} CLI를 찾을 수 없습니다."))
        else:
            result.append(ProviderStatus(name, True, f"{name} CLI 사용 가능", found))
    return result


def request_for(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))


def prepare_run(**kwargs: Any) -> int:
    return prepare.run(**kwargs)


def generate_state(run_dir: Path, state: str, *, provider: str | None = None) -> dict[str, Any]:
    request = request_for(run_dir)
    provider = provider or json.loads((run_dir / "studio" / "studio.json").read_text(encoding="utf-8"))["config"]["provider"]
    prompt, source = effective_prompt(run_dir, request, state)
    # §4/§13: target kind for validation always comes from the request SSOT
    # (states[state].frames), never from the prompt text itself — an operator
    # override prompt for a 4-frame row is still a row, and must not be held to
    # the single-image "single character only" rule.
    frames = int(request["states"][state]["frames"])
    target_kind = "single" if frames <= 1 else "animation_row"
    prompt_errors = [
        issue.message for issue in PromptValidator().validate(prompt, target_kind=target_kind)
        if issue.severity == "error"
    ]
    if prompt_errors:
        raise ValueError(f"prompt validation failed for {state}: {'; '.join(prompt_errors)}")
    raw = run_dir / raw_rel(request, state)
    refs: list[Path] = []
    if (request.get("directions") or {}).get("set"):
        # Directional identity is owned by the approved anchor. The engine's
        # resolver also enforces the pending/broken distinction and materializes
        # the live curated ref immediately before generation.
        from sprite_studio.curate.anchor import identity_ref, base_source
        try:
            refs.append(identity_ref(run_dir, state, request=request, quiet=True))
        except Exception:
            try:
                refs.append(base_source(run_dir))
            except Exception:
                base = (request.get("character") or {}).get("base_image")
                if base:
                    path = run_dir / base
                    if path.is_file():
                        refs.append(path)
    else:
        base = (request.get("character") or {}).get("base_image")
        if base:
            path = run_dir / base
            if path.is_file():
                refs.append(path)
    # §5: the prompt text tells the model "the attached layout guide shows the
    # N frame boxes..." (sprite_studio.gen.prepare.row_prompt) — that sentence
    # is a lie unless the guide image is actually attached as a provider
    # reference. Order matches the prompt's own "Reference 1 = identity,
    # Reference 2 = layout guide" framing.
    guide_path = run_dir / guide_rel(request, state)
    if guide_path.is_file():
        refs.append(guide_path)
    result = generate_one(
        provider,
        prompt,
        raw,
        refs=refs,
        aspect_ratio="16:9" if provider == "grok" else None,
        workdir=run_dir / "studio" / "work" / state,
    )
    report = result.to_dict() | {"state": state, "prompt_source": source}
    log_path = run_dir / "studio-logs" / f"{state}.generate.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    history_dir = run_dir / "studio" / "history" / state
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ%f")
    (history_dir / f"attempt-{stamp}.json").write_text(
        json.dumps(report | {"timestamp": stamp}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def normalize_state(run_dir: Path, state: str) -> dict[str, Any]:
    """Normalize, then enforce the quality gate before returning.

    This is the only place normalize's report is consumed on the production
    (Studio) path, so it is the only place that needs to know about
    ``NormalizeQualityFailed`` — a FAIL result raises instead of being handed
    back as if it were a usable row, which is what let a malformed generation
    reach Extract/Anchor silently before (directive root cause, §1).
    """
    request = request_for(run_dir)
    spec = request["states"][state]
    cell = request["cell"]
    raw = run_dir / raw_rel(request, state)
    report_path = raw.with_name(raw.stem + ".normalize.report.json")
    quality = load_normalize_quality_settings("sprite")
    try:
        normalize_grok_row.run(
            input=raw,
            out=raw,
            chroma_key=(request.get("chroma_key") or {}).get("hex", "green"),
            count=int(spec["frames"]),
            cell_width=int(cell["width"]),
            cell_height=int(cell["height"]),
            safe_margin_x=int(cell.get("safe_margin_x", cell.get("safe_margin", 24))),
            safe_margin_y=int(cell.get("safe_margin_y", cell.get("safe_margin", 24))),
            report=report_path,
            quality=quality,
        )
    except SystemExit as exc:
        # A hard failure (couldn't segment into `count` spans, empty span, bad
        # params) previously escaped as SystemExit — a BaseException that
        # batch_service's `except Exception` never caught, leaving the batch
        # queue stuck at status "running" until a later poll mislabeled it
        # "interrupted" with a generic message (lost the real cause). Wrap it
        # in the same typed, catchable failure as a soft quality FAIL.
        raise NormalizeQualityFailed(state, {"result": "fail", "error": str(exc)}) from exc
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("result") == "fail":
        raise NormalizeQualityFailed(state, report)
    return report


def extract_frames(run_dir: Path, state: str | None = None, *, normalize: bool = False) -> int:
    return extract.run(run_dir=run_dir, states=state or "all", normalize_grok_row=normalize)


def refine_frames(run_dir: Path, state: str, *, shared_lattice=None):
    from .refine_service import refine_state
    return refine_state(run_dir, state, shared_lattice=shared_lattice)


def refine_states(run_dir: Path, states: list[str]):
    from .refine_service import refine_states as rs
    return rs(run_dir, states)


def analyze_repairs(run_dir: Path, state: str):
    from .repair_service import analyze_state
    return analyze_state(run_dir, state)


def repair_frames(run_dir: Path, state: str, *, candidate_ids: set[str] | None = None):
    from .repair_service import repair_state
    return repair_state(run_dir, state, candidate_ids=candidate_ids)


def animation_qa(run_dir: Path, state: str):
    from .animation_qa import run_animation_qa
    return run_animation_qa(run_dir, state)


def launch_curation(run_dir: Path, *, lang: str = "ko") -> str:
    """Start the existing curation UI without blocking the Studio callback."""
    import socket
    import threading

    from sprite_studio.serve import serve_curation

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    thread = threading.Thread(
        target=serve_curation.run,
        kwargs={"run_dir": run_dir, "port": port, "no_open": False, "lang": lang},
        daemon=True,
        name=f"sprite-studio-curation-{run_dir.name}",
    )
    thread.start()
    return f"http://127.0.0.1:{port}/"
