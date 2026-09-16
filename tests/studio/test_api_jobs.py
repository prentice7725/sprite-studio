# SPDX-License-Identifier: Apache-2.0
"""Single-operation Job API: persistence, WebSocket completion, cancel, retry."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from studio.api.main import app
from studio.backend import job_service, run_manager
from studio.backend.run_manager import RUNS_ROOT_ENV
from studio.backend.schemas import StudioRunConfig


client = TestClient(app)


def _seed_run(tmp_path: Path, monkeypatch) -> str:
    root = tmp_path / "runs"
    monkeypatch.setenv(RUNS_ROOT_ENV, str(root))
    run_manager.create_run(
        StudioRunConfig(
            run_id="job_api_test",
            character_id="hero",
            provider="grok",
            base_image=None,
            directions=("side",),
            mirrors={},
            states={"idle": {"frames": 1, "fps": 8, "loop": False, "action": "idle"}},
            preset="sword",
        ),
        root=root,
    )
    return "job_api_test"


def _terminal(ws):
    payload = ws.receive_json()
    while payload["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
        payload = ws.receive_json()
    return payload


def test_single_job_websocket_persists_result(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    monkeypatch.setattr(job_service, "_execute_operation", lambda *_args, **_kwargs: {"marker": "done"})

    started = client.post(f"/api/runs/{run_id}/jobs", json={"operation": "extract", "state": "side_idle"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]

    with client.websocket_connect(f"/api/runs/{run_id}/jobs/{job_id}/events") as ws:
        terminal = _terminal(ws)
    assert terminal["status"] == "succeeded"
    assert terminal["result"] == {"marker": "done"}
    assert client.get(f"/api/runs/{run_id}/jobs/{job_id}").json()["result"] == {"marker": "done"}


def test_single_job_cancel_is_cooperative(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)

    def slow(*_args, **_kwargs):
        time.sleep(0.1)
        return {"marker": "finished-current-call"}

    monkeypatch.setattr(job_service, "_execute_operation", slow)
    started = client.post(f"/api/runs/{run_id}/jobs", json={"operation": "extract", "state": "side_idle"})
    job_id = started.json()["job_id"]
    cancel = client.post(f"/api/runs/{run_id}/jobs/{job_id}/cancel")
    assert cancel.status_code == 200

    with client.websocket_connect(f"/api/runs/{run_id}/jobs/{job_id}/events") as ws:
        terminal = _terminal(ws)
    assert terminal["status"] == "cancelled"


def test_failed_single_job_can_be_retried(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)
    calls = {"count": 0}

    def flaky(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient provider failure")
        return {"marker": "retry-ok"}

    monkeypatch.setattr(job_service, "_execute_operation", flaky)
    first = client.post(f"/api/runs/{run_id}/jobs", json={"operation": "extract", "state": "side_idle"})
    first_id = first.json()["job_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/jobs/{first_id}/events") as ws:
        assert _terminal(ws)["status"] == "failed"

    retried = client.post(f"/api/runs/{run_id}/jobs/{first_id}/retry")
    assert retried.status_code == 202
    second_id = retried.json()["job_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/jobs/{second_id}/events") as ws:
        terminal = _terminal(ws)
    assert terminal["status"] == "succeeded"
    assert terminal["result"] == {"marker": "retry-ok"}
    assert terminal["attempt"] == 2
    assert terminal["parent_job_id"] == first_id
