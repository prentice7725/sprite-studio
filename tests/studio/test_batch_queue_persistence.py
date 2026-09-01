# SPDX-License-Identifier: Apache-2.0
"""Batch queue atomic persistence — directive §1 / §11.

Covers the P0 fix: ``batch-queue.json`` must never be visible to a concurrent
reader (UI polling) as a torn/partial write, and a genuinely corrupt file must
come back as an explicit, invariant-preserving "corrupt" status rather than a
partial dict that crashes callers indexing ``job_id`` / ``items`` /
``total_items``.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from studio.backend import batch_service

_REQUIRED_KEYS = {"job_id", "items", "total_items"}


def _make_payload(job_id: str, **extra) -> dict:
    payload = {
        "kind": "sprite-studio-batch",
        "job_id": job_id,
        "status": "running",
        "current_state": "side_idle",
        "current_stage": "refining",
        "completed_items": 0,
        "total_items": 1,
        "progress_percent": 0.0,
        "started_at": "2026-09-02T00:00:00+00:00",
        "updated_at": "2026-09-02T00:00:00+00:00",
        "elapsed_seconds": 0,
        "items": [{"state": "side_idle", "status": "queued"}],
        "error": None,
    }
    payload.update(extra)
    return payload


def test_atomic_write_stress_never_yields_partial_json(tmp_path: Path) -> None:
    """100-500 rapid _update()/load_queue() cycles: every read is whole JSON."""
    run_dir = tmp_path / "run"
    (run_dir / "studio").mkdir(parents=True)
    payload = _make_payload("job-stress")
    batch_service._save(run_dir, payload)

    errors: list[BaseException] = []
    stop = threading.Event()

    def writer() -> None:
        for i in range(300):
            if stop.is_set():
                return
            try:
                batch_service._update(run_dir, payload, completed_items=i % 5, progress_percent=float(i % 100))
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)
                stop.set()
                return

    def reader() -> None:
        for _ in range(300):
            if stop.is_set():
                return
            try:
                result = batch_service.load_queue(run_dir)
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)
                stop.set()
                return
            if result is not None:
                missing = _REQUIRED_KEYS - set(result)
                if missing:
                    errors.append(AssertionError(f"read missing keys: {missing}"))
                    stop.set()
                    return

    threads = [threading.Thread(target=writer), threading.Thread(target=reader), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors


def test_load_queue_malformed_json_returns_explicit_corrupt_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "studio").mkdir(parents=True)
    (run_dir / "studio" / "batch-queue.json").write_text("{not valid json", encoding="utf-8")

    payload = batch_service.load_queue(run_dir)

    assert payload is not None
    assert payload["status"] == "corrupt"
    assert payload["job_id"] is None
    assert payload["items"] == []
    assert payload["total_items"] == 0
    assert payload["error"]
    # Every downstream consumer indexes these unconditionally — must never KeyError.
    assert _REQUIRED_KEYS <= set(payload)


def test_load_queue_missing_invariant_keys_returns_corrupt(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "studio").mkdir(parents=True)
    # Valid JSON, but missing the invariant keys (e.g. truncated write that
    # still happens to parse, or a hand-edited file).
    (run_dir / "studio" / "batch-queue.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")

    payload = batch_service.load_queue(run_dir)

    assert payload["status"] == "corrupt"
    assert payload["job_id"] is None
    assert _REQUIRED_KEYS <= set(payload)


def test_load_queue_non_object_json_returns_corrupt(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "studio").mkdir(parents=True)
    (run_dir / "studio" / "batch-queue.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    payload = batch_service.load_queue(run_dir)

    assert payload["status"] == "corrupt"
    assert _REQUIRED_KEYS <= set(payload)


def test_status_text_reports_corrupt_queue_explicitly(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "studio").mkdir(parents=True)
    (run_dir / "studio" / "batch-queue.json").write_text("{broken", encoding="utf-8")

    text = batch_service.status_text(run_dir)

    assert "CORRUPT" in text
    assert "batch-queue.json is invalid" in text


def test_save_replaces_file_atomically_no_truncated_intermediate(tmp_path: Path) -> None:
    """A crash/kill mid-write must never leave a truncated file behind: the
    writer stages to a temp file and os.replace()s it in, so the target path
    itself is either the old complete payload or the new one."""
    run_dir = tmp_path / "run"
    (run_dir / "studio").mkdir(parents=True)
    path = run_dir / "studio" / "batch-queue.json"

    small = _make_payload("job-a")
    batch_service._save(run_dir, small)
    before = path.read_text(encoding="utf-8")
    assert json.loads(before)["job_id"] == "job-a"

    big = _make_payload("job-b", items=[{"state": f"s{i}", "status": "queued"} for i in range(200)])
    batch_service._save(run_dir, big)
    after = path.read_text(encoding="utf-8")
    parsed = json.loads(after)
    assert parsed["job_id"] == "job-b"
    assert len(parsed["items"]) == 200

    # No leftover temp files from the atomic-replace staging.
    leftovers = [p for p in path.parent.iterdir() if p.name != path.name]
    assert leftovers == []


def test_finished_failed_interrupted_states_keep_required_keys(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "studio").mkdir(parents=True)
    for status in ("complete", "failed", "interrupted"):
        payload = _make_payload(f"job-{status}", status=status)
        batch_service._save(run_dir, payload)
        result = batch_service.load_queue(run_dir)
        assert _REQUIRED_KEYS <= set(result)
        assert result["status"] == status
