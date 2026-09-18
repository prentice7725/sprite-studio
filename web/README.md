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
The default entry point is **Quick Generate**. It supports Upload → Make Sprite,
Upload → Pixelize → Make Sprite, Prompt → Generate Source → Make Sprite, and the
corresponding Pixelize-first path. Quick sessions expose only source, motion,
style, background, Pixelize, Make Sprite, progress, and result concepts; the
existing Project/Workspace/Static/Jobs screens remain available under **Studio**.
The Quick API persists source files under its session root, serves them as URLs,
and delegates Pixelize M1 and the full Generate → Normalize → Extract → Refine →
QA → Compose pipeline to the existing backend services.
Generate, Refine, Repair, Animation QA, and Export are tools inside the active
Workspace; Batch is available from the global Jobs drawer. Sprite preset details
are loaded from FastAPI rather than duplicated in React.

The application shell owns selection, API orchestration, and job state while
Workspace presentation lives in `src/features/workspace/WorkspacePanels.tsx`.
This keeps the persistent canvas/timeline and inspector-like pipeline tools
together without growing `App.tsx` into another monolithic UI component.

The Workspace also provides a persistent canvas viewer, keyboard-friendly frame
timeline, read-only generation variant history, and a locale toggle. Heavy
single-operation actions start through the Jobs drawer and stream their
persisted status over WebSocket; cancellation is cooperative while a provider
call is already running, and failed jobs can be retried. Static projects use
`/api/static/presets`; tileable outputs show a 3×3 wrap preview
after seam check/repair.

The shell keeps a single `activeJob` state for foreground operations. On reload
or asset navigation it asks `listJobs()` for running/cancel-requested work and
reconnects to the persisted job stream. Sprite preview state is cached under
`{run_id}:{state}` and static preview state under `{project_id}:{asset}` to
prevent stale output from crossing selections. The Jobs drawer exposes a modal
dialog keyboard flow (Escape, focus trap, focus restore), ARIA progress bars,
and live status updates.

The Workspace also places a single **NEXT ACTION** card beside the persistent
canvas. It derives the next step from the server-owned state status and handles
the `KEYPOSE_SEQUENTIAL` fallback sequence (key poses, approval, inbetweens,
and promotion) through the same Job actions. The top-bar **Display** menu
persists 100/125/150% UI scale and high-contrast mode locally.

Review mode uses the persistent center workspace for A/B comparison instead of
stacking every asset in a vertical grid. View A and View B can independently
select Extracted, Refined, Proposal, Repaired, or Diff, while one timeline keeps
the selected frame position synchronized across both canvases.

Frontend state regressions are covered by Vitest + Testing Library. Run
`npm run test` for the one-shot suite or `npm run test:watch` during UI work;
`npm run build` remains the production type/build check.

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

Open `http://127.0.0.1:8765`. The desktop wrapper is Electron-based; see
`../desktop/electron/README.md` for dynamic-port development and packaging.
