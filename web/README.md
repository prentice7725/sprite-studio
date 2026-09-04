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

This front end implements Project, Static Mode, Generate, Refine, Repair,
Animation QA, Curation launch, Sprite Export, and Batch workflows against
FastAPI service-backed routes.

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
