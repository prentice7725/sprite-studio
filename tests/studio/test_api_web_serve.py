# SPDX-License-Identifier: Apache-2.0
"""Production React bundle serving contract."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from studio.api import main


def test_api_serves_built_react_bundle_when_dist_exists(tmp_path: Path, monkeypatch) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Test Sprite Studio</title>", encoding="utf-8")
    monkeypatch.setenv(main._WEB_DIST_ENV, str(dist))

    app = main.create_app()

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "Test Sprite Studio" in response.text
    assert TestClient(app).get("/api/health").status_code == 200
