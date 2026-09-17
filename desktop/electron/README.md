# Sprite Studio Electron shell

This is the desktop wrapper for the existing React/Vite + FastAPI application.
The renderer still talks to FastAPI through HTTP/WebSocket only; the Electron
main process is responsible for starting and stopping the backend.

## Development

Install the desktop dependencies, then run:

```powershell
npm install
npm run dev
```

`dev` builds `web/dist`, starts `python -u -m studio.api.main --host
127.0.0.1 --port 0`, waits for `/api/health`, and opens the Electron window.
It prefers `.venv` at the repository root. Set `SPRITE_STUDIO_PYTHON` to a
different Python executable when needed.

## Packaging

Packaging is Windows-first for now and requires a native FastAPI executable.
Build the backend artifact, then run:

```powershell
$env:SPRITE_STUDIO_BACKEND_BIN = 'C:\path\to\sprite-studio-api.exe'
npm run make
```

The staging script copies `web/dist` and the backend artifact into the bundle.
The packaged app stores runs, static projects, and uploads under Electron's
user-data directory instead of the installation directory.
