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


def test_execute_records_systemexit_as_a_real_failure_not_a_misreported_interrupt(
    tmp_path: Path, monkeypatch
) -> None:
    """§ live incident 2026-09-02: `generate_state`/the grok provider raise
    `SystemExit` on plenty of ordinary, expected failure paths (a bad
    provider output, a missing anchor, a generation timeout) — all
    `BaseException`, not `Exception`. `except Exception` in `_execute` let
    those escape the worker thread uncaught: `finally` still popped the job
    out of `_ACTIVE_THREADS` (it always runs), so the *next* `load_queue()`
    poll saw "status": "running" with no matching live thread and reported
    the generic "Worker thread or host process terminated before batch
    completion" — masking whatever had actually failed. `_execute` must catch
    `SystemExit` too and persist the real error before the thread dies."""
    run_dir = tmp_path / "run"
    (run_dir / "studio").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps({"states": {"idle": {"frames": 4}}}), encoding="utf-8"
    )

    def _boom(*args, **kwargs):
        raise SystemExit("gen: file is not a PNG (magic mismatch) — refusing to claim success")

    monkeypatch.setattr(batch_service.spritegen_bridge, "generate_state", _boom)

    payload = _make_payload("job-systemexit", current_state="idle", current_stage="queued",
                             total_items=1, items=[{"state": "idle", "status": "queued"}])
    with batch_service._ACTIVE_LOCK:
        batch_service._ACTIVE_THREADS["job-systemexit"] = threading.current_thread()

    # Must not raise past _execute — the worker thread contract is that
    # failures are recorded, never left to kill the thread silently.
    batch_service._execute(run_dir, payload, normalize=False, refine=False, repair=False, qa=False)

    result = batch_service.load_queue(run_dir)
    assert result["status"] == "failed"
    assert "SystemExit" in result["error"]
    assert "magic mismatch" in result["error"]
    assert result["failed_state"] == "idle"
    # The thread bookkeeping must still be cleaned up (finally: always runs).
    with batch_service._ACTIVE_LOCK:
        assert "job-systemexit" not in batch_service._ACTIVE_THREADS
