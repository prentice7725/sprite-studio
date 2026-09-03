# SPDX-License-Identifier: Apache-2.0
"""Phase 2 FastAPI shell — prompt (get/blocks/override) and generate ->
normalize -> extract -> refine, chained through real HTTP requests against
real backend logic (only the provider call itself is faked — no network,
no grok/codex CLI). ENDPOINTS.md §Prompt, §Generate/Normalize/Extract/Refine.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from studio.api.main import app
from studio.backend import run_manager, spritegen_bridge
from studio.backend.run_manager import RUNS_ROOT_ENV
from studio.backend.schemas import StudioRunConfig

client = TestClient(app)

MAGENTA = (255, 0, 255)


def _base(path: Path) -> None:
    image = Image.new("RGB", (64, 64), (10, 10, 10))
    ImageDraw.Draw(image).rectangle((22, 16, 42, 55), fill=(80, 80, 80))
    image.save(path)


def _clean_strip(frames: int = 4) -> Image.Image:
    """A valid chroma-keyed row a real grok call would (ideally) return —
    same construction as tests/studio/test_normalize_quality_gate.py, reused
    here so normalize/extract/refine run their REAL logic end to end."""
    image = Image.new("RGB", (150 * frames + 45, 180), MAGENTA)
    draw = ImageDraw.Draw(image)
    colors = [(40, 200, 60), (30, 120, 220), (210, 190, 20), (60, 170, 90)]
    for index in range(frames):
        left = 35 + index * 150
        color = colors[index % len(colors)]
        draw.rectangle((left, 28, left + 82, 155), fill=color)
        draw.rectangle((left + 24, 10, left + 58, 45), fill=color)
    return image


def _seed_run(tmp_path: Path, monkeypatch, *, directions=("side",)) -> str:
    runs_root = tmp_path / "runs"
    monkeypatch.setenv(RUNS_ROOT_ENV, str(runs_root))
    base = tmp_path / "base.png"
    _base(base)
    config = StudioRunConfig(
        run_id="api_gen_test",
        character_id="sword",
        provider="grok",
        base_image=base,
        directions=directions,
        mirrors={},
        states={"idle": {"frames": 4, "fps": 4, "loop": True, "action": "idle"}},
        preset="sword",
        # Deterministic chroma so the synthetic strip's magenta background
        # matches what normalize expects, instead of "auto" picking whatever
        # colour the base image happens to avoid.
        background_policy="magenta",
    )
    run_manager.create_run(config, root=runs_root)
    return "api_gen_test"


def _fake_generate_one(provider, prompt, out, *, refs=None, aspect_ratio=None, workdir=None, **kwargs):
    """Stands in for the real grok/codex CLI call: writes a clean synthetic
    strip to the requested `out` path and reports success, so
    `generate_state`'s downstream file/report handling runs unmodified."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    _clean_strip().save(out)
    raw_keep = out.with_suffix(out.suffix + ".raw.png")
    _clean_strip().save(raw_keep)
    from sprite_studio.gen.base import GenResult

    return GenResult(
        provider=provider,
        prompt=prompt or "",
        out=out,
        raw=raw_keep,
        raw_bytes=out.stat().st_size,
        elapsed_seconds=0.01,
        model=None,
        session_id=None,
        refs=[],
        transparent=False,
        chroma=None,
        extra={},
    )


# --- Prompt --------------------------------------------------------------

def test_prompt_get_and_override_round_trip(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    state = "side_idle"

    generated = client.get(f"/api/runs/{run_id}/states/{state}/prompt")
    assert generated.status_code == 200
    body = generated.json()
    assert body["source"] == "generated"
    assert "Exactly 4" in body["prompt"]

    blocks = client.get(f"/api/runs/{run_id}/states/{state}/prompt/blocks")
    assert blocks.status_code == 200
    assert blocks.json()["target_kind"] == "animation_row"
    assert blocks.json()["frame_count"] == 4
    assert "production_contract" not in blocks.json()["blocks"]  # blocks-only preview, not the merged file

    saved = client.put(f"/api/runs/{run_id}/states/{state}/prompt/override", json={"prompt": "custom test prompt"})
    assert saved.status_code == 200
    # save_override persists with a trailing newline (prompt_service.save_override
    # normalizes to `.rstrip() + "\n"`); effective_prompt reads that back verbatim.
    assert saved.json() == {"state": state, "prompt": "custom test prompt\n", "source": "override"}

    reset = client.delete(f"/api/runs/{run_id}/states/{state}/prompt/override")
    assert reset.status_code == 200
    assert reset.json()["source"] == "generated"
    assert reset.json()["prompt"] == body["prompt"]


def test_prompt_unknown_state_is_404(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    response = client.get(f"/api/runs/{run_id}/states/nonexistent/prompt")
    assert response.status_code == 404


def test_prompt_empty_override_is_400(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    response = client.put(f"/api/runs/{run_id}/states/side_idle/prompt/override", json={"prompt": ""})
    assert response.status_code == 422  # Pydantic min_length=1 rejects it before the route runs


# --- Generate -> Normalize -> Extract -> Refine (chained, real logic) ----

def test_generate_normalize_extract_refine_chain(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    state = "side_idle"
    monkeypatch.setattr(spritegen_bridge, "generate_one", _fake_generate_one)

    generated = client.post(f"/api/runs/{run_id}/states/{state}/generate")
    assert generated.status_code == 200
    gbody = generated.json()
    assert gbody["provider"] == "grok"
    assert gbody["raw_bytes"] > 0
    assert gbody["prompt_source"] == "generated"
    # The raw asset must actually be fetchable through the assets router.
    fetched = client.get(gbody["raw_asset"])
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/png"

    normalized = client.post(f"/api/runs/{run_id}/states/{state}/normalize")
    assert normalized.status_code == 200
    nbody = normalized.json()
    assert nbody["result"] == "pass"
    assert nbody["valid_subjects"] == 4
    assert nbody["expected_subjects"] == 4

    extracted = client.post(f"/api/runs/{run_id}/states/{state}/extract")
    assert extracted.status_code == 200
    assert extracted.json()["exit_code"] == 0

    refined = client.post(f"/api/runs/{run_id}/states/{state}/refine")
    assert refined.status_code == 200
    rbody = refined.json()
    assert rbody["refined_preview_asset"] is not None
    preview = client.get(rbody["refined_preview_asset"])
    assert preview.status_code == 200


def test_normalize_quality_failure_is_422_with_report(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    state = "side_idle"

    def _fake_bad_generate(provider, prompt, out, **kwargs):
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        # A blank chroma canvas: no subjects at all, segmentation fails hard.
        Image.new("RGB", (640, 180), MAGENTA).save(out)
        raw_keep = out.with_suffix(out.suffix + ".raw.png")
        Image.new("RGB", (640, 180), MAGENTA).save(raw_keep)
        from sprite_studio.gen.base import GenResult
        return GenResult(provider=provider, prompt=prompt, out=out, raw=raw_keep, raw_bytes=out.stat().st_size,
                          elapsed_seconds=0.01, model=None, session_id=None, refs=[], transparent=False, chroma=None)

    monkeypatch.setattr(spritegen_bridge, "generate_one", _fake_bad_generate)
    assert client.post(f"/api/runs/{run_id}/states/{state}/generate").status_code == 200

    response = client.post(f"/api/runs/{run_id}/states/{state}/normalize")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "report" in detail
    assert detail["report"]["result"] == "fail"


def test_generate_unknown_run_is_404(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(RUNS_ROOT_ENV, str(tmp_path / "runs"))
    response = client.post("/api/runs/does_not_exist/states/side_idle/generate")
    assert response.status_code == 404


def test_refine_before_extract_is_400(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    response = client.post(f"/api/runs/{run_id}/states/side_idle/refine")
    assert response.status_code == 400
