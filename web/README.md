# Sprite Studio Web

Phase 6 React/Vite front end for the existing Sprite Studio FastAPI surface.

## Development

Run the API on the port used by the Vite proxy:

```powershell
python -m studio.api.main --port 8765
```

In another terminal:

```powershell
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

To point the browser directly at another API origin, set `VITE_API_BASE_URL`, for
example `http://127.0.0.1:8765/api`. The default is `/api`, which uses the Vite
development proxy and also keeps asset URLs same-origin in the browser.

This front end implements an asset-centric Project/Static/Workspace layout.
Generate, Refine, Repair, Animation QA, and Export are tools inside the active
Workspace; Batch is available from the global Jobs drawer. Sprite preset details
are loaded from FastAPI rather than duplicated in React.

The Workspace also provides a persistent canvas viewer, keyboard-friendly frame
timeline, read-only generation variant history, and a locale toggle. Static
projects use `/api/static/presets`; tileable outputs show a 3×3 wrap preview
after seam check/repair.

When the FastAPI server is running, `npm run api:types` fetches its OpenAPI
document and writes the generated contract types to `src/api.generated.ts`.
The hand-written `src/api.ts` client keeps the user-facing helpers and uses the
same response envelopes.

P2 generation planning is available under
`/api/runs/{run_id}/states/{state}`. The sequential path persists a Motion Plan,
generates key poses, requires explicit approval, and then generates
bidirectional inbetweens in a separate manifest.

## Single-port preview

Build the bundle first, then run FastAPI. When `web/dist/index.html` exists,
FastAPI serves the React bundle and API from one origin:

```powershell
npm run build
cd ..
python -m studio.api.main --port 8765
```

Open `http://127.0.0.1:8765`. Tauri packaging is intentionally not part of
this phase.
