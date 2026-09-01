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
from sprite_studio.spec.layout import raw_rel

from .prompt_service import effective_prompt
from .schemas import ProviderStatus
from studio.core.prompt import PromptValidator


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
    prompt_errors = [issue.message for issue in PromptValidator().validate(prompt) if issue.severity == "error"]
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
    request = request_for(run_dir)
    spec = request["states"][state]
    cell = request["cell"]
    raw = run_dir / raw_rel(request, state)
    report = raw.with_name(raw.stem + ".normalize.report.json")
    normalize_grok_row.run(
        input=raw,
        out=raw,
        chroma_key=(request.get("chroma_key") or {}).get("hex", "green"),
        count=int(spec["frames"]),
        cell_width=int(cell["width"]),
        cell_height=int(cell["height"]),
        safe_margin_x=int(cell.get("safe_margin_x", cell.get("safe_margin", 24))),
        safe_margin_y=int(cell.get("safe_margin_y", cell.get("safe_margin", 24))),
        report=report,
    )
    return json.loads(report.read_text(encoding="utf-8"))


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
