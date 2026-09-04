# SPDX-License-Identifier: Apache-2.0
"""Sprite Studio API — FastAPI shell for the React migration.

Run with ``python -m studio.api.main`` (dev) or ``uvicorn
studio.api.main:app`` directly. Phase 1: health/providers, run list/get/
status, asset file serving. Phase 2: per-state prompt (get/blocks/override),
generate/normalize/extract/refine, uploads, and run create/delete. Phase 3:
batch start/poll + a WebSocket progress stream. Phases 5-6 add presets,
review/repair, anchor, animation QA, curation launch, sprite export, and
Static Mode adapters. See ENDPOINTS.md for endpoint specifications.
"""

from __future__ import annotations

import argparse
import os
import socket
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from studio.api.routers import assets, batch, generate, health, presets, prompt, review, runs, static_mode, uploads

# Comma-separated dev origins (the Vite dev server) allowed to call this API
# cross-origin. Irrelevant once the built React app is served BY this same
# FastAPI process on one port (the "no CORS needed" end state the migration
# plan describes) — kept configurable rather than hardcoded so a different
# dev port doesn't require an edit here.
_DEV_ORIGINS_ENV = "SPRITE_STUDIO_API_DEV_ORIGINS"
_DEFAULT_DEV_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
_WEB_DIST_ENV = "SPRITE_STUDIO_WEB_DIST"


def _web_dist() -> Path:
    configured = os.environ.get(_WEB_DIST_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "web" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="Sprite Studio API", version="0.1.0")
    origins = os.environ.get(_DEV_ORIGINS_ENV, _DEFAULT_DEV_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(uploads.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(assets.router, prefix="/api")
    app.include_router(prompt.router, prefix="/api")
    app.include_router(generate.router, prefix="/api")
    app.include_router(batch.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(static_mode.router, prefix="/api")
    app.include_router(presets.router, prefix="/api")
    # Production integration: after `cd web && npm run build`, the same API
    # process serves the React bundle. The conditional keeps the API usable
    # from a clean checkout and preserves the Vite two-process dev workflow.
    web_dist = _web_dist()
    if web_dist.is_dir() and (web_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app


app = create_app()


def _pick_free_port(host: str) -> int:
    """Same OS-assigned-port trick `spritegen_bridge.launch_curation` already
    uses for the curation server: bind `:0`, read back what the OS gave us,
    release the socket, hand that integer to the real server. `--port 0`
    means "give me a free one" rather than fighting over a fixed 7860/8765."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("SPRITE_STUDIO_API_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("SPRITE_STUDIO_API_PORT", "0")),
        help="0 (default) asks the OS for a free port and prints which one it picked",
    )
    parser.add_argument("--reload", action="store_true", help="autoreload on source change (dev only)")
    args = parser.parse_args(argv)

    port = args.port or _pick_free_port(args.host)
    print(f"[sprite-studio-api] listening on http://{args.host}:{port} (docs: /docs)")
    uvicorn.run("studio.api.main:app" if args.reload else app, host=args.host, port=port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
