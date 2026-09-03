# SPDX-License-Identifier: Apache-2.0
"""POST .../batches, GET .../batches/current, WS .../batches/{job_id}/events
— ENDPOINTS.md §"Sprite Mode — Batch". The real `batch_service.start_batch`
spawns a genuine background thread; only the provider call (`generate_one`)
is faked, so these tests exercise the real queue-file state machine and the
real WebSocket push loop, not a mock of either.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
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
    image = Image.new("RGB", (150 * frames + 45, 180), MAGENTA)
    draw = ImageDraw.Draw(image)
    colors = [(40, 200, 60), (30, 120, 220), (210, 190, 20), (60, 170, 90)]
    for index in range(frames):
        left = 35 + index * 150
        color = colors[index % len(colors)]
        draw.rectangle((left, 28, left + 82, 155), fill=color)
        draw.rectangle((left + 24, 10, left + 58, 45), fill=color)
    return image


def _seed_run(tmp_path: Path, monkeypatch) -> str:
    runs_root = tmp_path / "runs"
    monkeypatch.setenv(RUNS_ROOT_ENV, str(runs_root))
    base = tmp_path / "base.png"
    _base(base)
    config = StudioRunConfig(
        run_id="api_batch_test",
        character_id="sword",
        provider="grok",
        base_image=base,
        directions=("side",),
        mirrors={},
        states={"idle": {"frames": 4, "fps": 4, "loop": True, "action": "idle"}},
        preset="sword",
        background_policy="magenta",
    )
    run_manager.create_run(config, root=runs_root)
    return "api_batch_test"


def _fake_generate_one(provider, prompt, out, *, refs=None, aspect_ratio=None, workdir=None, delay=0.0, **kwargs):
    if delay:
        time.sleep(delay)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    _clean_strip().save(out)
    raw_keep = out.with_suffix(out.suffix + ".raw.png")
    _clean_strip().save(raw_keep)
    from sprite_studio.gen.base import GenResult

    return GenResult(provider=provider, prompt=prompt or "", out=out, raw=raw_keep, raw_bytes=out.stat().st_size,
                      elapsed_seconds=delay, model=None, session_id=None, refs=[], transparent=False, chroma=None)


def _wait_for_terminal(run_id: str, *, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/batches/current")
        body = response.json()
        if body["status"] in {"complete", "failed", "interrupted", "corrupt"}:
            return body
        time.sleep(0.1)
    raise AssertionError("batch did not reach a terminal status in time")


# --- start / poll ------------------------------------------------------------

def test_start_batch_and_poll_to_completion(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    monkeypatch.setattr(spritegen_bridge, "generate_one", _fake_generate_one)

    started = client.post(
        f"/api/runs/{run_id}/batches",
        json={"states": ["side_idle"], "normalize": True, "refine": False, "repair": False, "qa": False},
    )
    assert started.status_code == 201
    job_id = started.json()["job_id"]
    assert job_id

    final = _wait_for_terminal(run_id)
    assert final["status"] == "complete"
    assert final["job_id"] == job_id
    assert final["completed_items"] == 1
    assert final["items"][0]["state"] == "side_idle"
    assert final["items"][0]["status"] == "complete"
    assert final["items"][0]["normalize"]["result"] == "pass"


def test_batch_current_404_before_any_batch_ran(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    response = client.get(f"/api/runs/{run_id}/batches/current")
    assert response.status_code == 404


def test_start_batch_unknown_state_is_400(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    response = client.post(f"/api/runs/{run_id}/batches", json={"states": ["nonexistent_state"]})
    assert response.status_code == 400


def test_start_batch_conflict_while_running_is_409(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    monkeypatch.setattr(
        spritegen_bridge, "generate_one",
        lambda *a, **k: _fake_generate_one(*a, **k, delay=1.0),
    )

    first = client.post(f"/api/runs/{run_id}/batches", json={"states": ["side_idle"], "normalize": False, "refine": False, "repair": False, "qa": False})
    assert first.status_code == 201

    second = client.post(f"/api/runs/{run_id}/batches", json={"states": ["side_idle"], "normalize": False, "refine": False, "repair": False, "qa": False})
    assert second.status_code == 409

    _wait_for_terminal(run_id)  # drain the background thread before the fixture tears down


def test_start_batch_unknown_run_is_404(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(RUNS_ROOT_ENV, str(tmp_path / "runs"))
    response = client.post("/api/runs/does_not_exist/batches", json={"states": ["side_idle"]})
    assert response.status_code == 404


# --- WebSocket -----------------------------------------------------------

def test_batch_websocket_streams_to_completion(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    monkeypatch.setattr(spritegen_bridge, "generate_one", _fake_generate_one)

    started = client.post(
        f"/api/runs/{run_id}/batches",
        json={"states": ["side_idle"], "normalize": True, "refine": False, "repair": False, "qa": False},
    )
    job_id = started.json()["job_id"]

    statuses: list[str] = []
    with client.websocket_connect(f"/api/runs/{run_id}/batches/{job_id}/events") as ws:
        for _ in range(200):
            message = ws.receive_json()
            statuses.append(message["status"])
            if message["status"] in {"complete", "failed", "interrupted", "corrupt"}:
                break
        else:
            raise AssertionError("websocket never reached a terminal status")

    assert statuses[-1] == "complete"
    assert statuses[0] == "running"


def test_batch_websocket_unknown_run_closes_immediately(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(RUNS_ROOT_ENV, str(tmp_path / "runs"))
    with pytest.raises(Exception):  # noqa: B017 - starlette raises its own WebSocketDisconnect-ish signal on close
        with client.websocket_connect("/api/runs/does_not_exist/batches/nope/events") as ws:
            ws.receive_json()


def test_batch_websocket_stale_job_id_closes(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    monkeypatch.setattr(spritegen_bridge, "generate_one", _fake_generate_one)
    client.post(
        f"/api/runs/{run_id}/batches",
        json={"states": ["side_idle"], "normalize": True, "refine": False, "repair": False, "qa": False},
    )
    _wait_for_terminal(run_id)

    with pytest.raises(Exception):  # noqa: B017
        with client.websocket_connect(f"/api/runs/{run_id}/batches/not-the-real-job-id/events") as ws:
            ws.receive_json()
