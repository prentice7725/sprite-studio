# Sprite Studio API — Endpoint Contract

Companion to [`contracts.py`](contracts.py) (the typed request/response models
this table names). This document serves as the single source of truth for FastAPI
routers and the React client.

The "Backend call" column is the `studio/backend/*` function the route calls —
routers stay thin: parse request → call the backend function → shape the response.
**No route calls `sprite_studio/*` directly.**

**Implemented so far** (`studio/api/routers/`): Health, Uploads, Assets, Runs
(list/get/status/create/delete), Presets, Prompt,
Generate/Normalize/Extract/Refine, Batch (start/poll/WebSocket), Review/Repair,
Anchor, Animation QA/Curation/Export, Static Mode, and Quick Generate.
**Not yet implemented**: no planned endpoint groups remain. Review/Repair,
Anchor, Animation QA/Curation/Export, Presets, and Static Mode are registered
service-backed routes.

## Conventions

- Base path: `/api`. All bodies are JSON; no endpoint accepts or returns
  base64 image data.
- **Assets are URLs, not blobs.** Images and files are exposed as
  `GET /api/runs/{run_id}/assets/{path}` (Sprite) or
  `GET /api/static/{project_id}/assets/{path}` (Static) — see §Assets.
- **Uploads.** Client image uploads are staged through `POST /api/uploads` first;
  subsequent routes receive the returned `upload_id`.
- **Errors.** Every 4xx/5xx body is `ErrorResponse` (`{"detail": "..."}`) with
  clean user-facing error text, not a stack trace.
  Normalize's 422 is the one documented exception (structured `detail`, see
  its row below).
- **`SystemExit`.** The engine (`sprite_studio.gen`, `sprite_studio.curate.
  anchor`) raises plain `SystemExit` pervasively as its fail-loud idiom
  (`AnchorUnavailable`, `GenTimeoutError`, `verify_png`, a non-zero provider
  exit, `base_source`). It is a `BaseException`, not an `Exception` —
  FastAPI/Starlette's default handling does not catch it. **Every route that
  calls into `studio/backend/*` must catch `SystemExit` explicitly** and turn
  it into an `HTTPException`, the same lesson `batch_service._execute` had to
  learn the hard way (2026-09-02: `except Exception` there let a `SystemExit`
  kill a batch worker thread silently instead of recording the real error).
  `studio/api/routers/generate.py` is the reference for the pattern.
- **Batch progress** is a WebSocket per job (§Batch); the on-disk
  `batch-queue.json` (`studio.backend.batch_service`) stays the persisted
  SSOT, the socket is just a transport over `load_queue()`.
- **Single-operation jobs** use a separate persisted file per operation under
  `<run>/studio/jobs/<job_id>.json`. The worker calls one existing
  `studio/backend/*` module, while HTTP and WebSocket expose its state and
  URL-shaped result. Cancellation is cooperative: a provider subprocess that
  is already running finishes its current call, then the worker records
  `cancelled` before starting no further stage.

---

## Health

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| GET | `/api/health` | — | `{"status": "ok"}` | — (liveness only) |
| GET | `/api/providers` | — | `list[ProviderStatusModel]` | `spritegen_bridge.provider_status` / `static_service.provider_status` |

## Uploads — `NEW`

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| POST | `/api/uploads` | multipart file | `UploadResponse` | `studio.api.uploads.save_upload` — writes under `.uploads/<upload_id>/<filename>` (gitignored; `SPRITE_STUDIO_UPLOADS_ROOT` overrides), verifies the bytes decode as an image before returning 201, redeemed by `base_image_upload_id` / `upload_id` fields above via `studio.api.uploads.resolve_upload` |

## Assets — `NEW` (transport for every image the UI used to load from a local path)

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| GET | `/api/runs/{run_id}/assets/{path:path}` | — | file stream | resolves under `run_manager.load_run(run_id).path`; **must** reject any resolved path outside the run dir (no `..` escape) |
| GET | `/api/static/{project_id}/assets/{path:path}` | — | file stream | resolves under `static_service.load_project(project_id).path`, same containment rule |

---

## Quick Generate — source-first front door

| Method | Path | Request | Response | Backend owner |
|---|---|---|---|---|
| POST | `/api/quick/sessions` | `QuickSessionCreateRequest` | `QuickSessionResponse` (`201`) | `quick_service.create_session` → upload storage or existing provider service |
| GET | `/api/quick/sessions/{session_id}` | — | `QuickSessionResponse` | persisted Quick session metadata |
| GET | `/api/quick/sessions/{session_id}/assets/{path:path}` | — | file stream | contained Quick source/session asset |
| POST | `/api/quick/sessions/{session_id}/pixelize` | `QuickPixelizeRequest` | `QuickPixelizeResponse` | `preserve` → deterministic Pixelize M1.1; `reference_pixel_master_128` → reference-guided C2 with raw/intermediate/post artifacts |
| PUT | `/api/quick/sessions/{session_id}/source` | `QuickSourceSelectionRequest` | `QuickSessionResponse` | explicit original/pixelized source selection |
| POST | `/api/quick/sessions/{session_id}/make-sprite` | `QuickMakeSpriteRequest` | `QuickMakeSpriteResponse` (`202`) | auto-created Run + persisted `quick_make` Job |

Quick Pixelize defaults to `reference_pixel_master_128` at 128px. `preserve` remains available for the deterministic M1.1 route. C2 accepts only the validator-approved logical post-cleanup master; raw transport and intermediate artifacts remain available for audit. Preserve uses the subject-first `size`, `subject_mode`, and `detail` options.

Quick does not return base64 image data. The session API is a user-facing façade;
Make Sprite automatically builds the internal Run and then delegates the same
Generate/Normalize/Extract/Refine/QA/Compose services used by Advanced Studio.
## Sprite Mode — Project / Runs

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| GET | `/api/presets` | — | `list[str]` | `preset_service.list_presets` |
| GET | `/api/presets/{preset_id}` | — | preset JSON (unmodeled passthrough) | `preset_service.load_preset` |
| POST | `/api/runs` | `CreateRunRequest` | `RunDetail` | `run_manager.create_run` (router builds `StudioRunConfig`; `base_image_upload_id` resolves to the uploaded file path or `None`) |
| GET | `/api/runs` | — | `list[RunSummary]` | `run_manager.list_runs` |
| GET | `/api/runs/{run_id}` | — | `RunDetail` | `run_manager.load_run` |
| DELETE | `/api/runs/{run_id}` | — | 204 | `run_manager.delete_run` |
| GET | `/api/runs/{run_id}/status` | — | `RunStatusResponse` | `run_manager.get_run_status` (the MATRIX tab) |

`CreateRunRequest` has no "Generate New" / "Use Existing Image" flow field —
that distinction (base image required only for "Use Existing Image") is a
client form-level UX rule, not a server
invariant: `StudioRunConfig`/`create_run` already accept `base_image=None`
unconditionally (§ the 2026-09-02 identity_ref/base_source fix made this the
actual production contract, not an edge case). The client enforces the
"Use Existing Image needs a file" rule in its own form validation before it
ever calls `POST /api/uploads`.

## Sprite Mode — Prompt

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| GET | `/api/runs/{run_id}/states/{state}/prompt` | — | `PromptResponse` | `prompt_service.effective_prompt` |
| GET | `/api/runs/{run_id}/states/{state}/prompt/blocks` | — | `PromptBlocksResponse` | `prompt_service.assemble_for_run` |
| PUT | `/api/runs/{run_id}/states/{state}/prompt/override` | `SavePromptOverrideRequest` | `PromptResponse` | `prompt_service.save_override` |
| DELETE | `/api/runs/{run_id}/states/{state}/prompt/override` | — | `PromptResponse` | `prompt_service.reset_override` |

## Sprite Mode — Generate / Normalize / Extract / Refine (single state)

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| POST | `/api/runs/{run_id}/states/{state}/generate` | — | `GenerateResponse` | `spritegen_bridge.generate_state` |
| POST | `/api/runs/{run_id}/states/{state}/normalize` | optional `NormalizeRequest` | `NormalizeResponse` | `spritegen_bridge.normalize_state` (a `NormalizeQualityFailed` maps to 422; AUTO + ROW_FAST failures persist a KEYPOSE_SEQUENTIAL Motion Plan in the error detail) |
| POST | `/api/runs/{run_id}/states/{state}/extract` | — | `ExtractResponse` | `spritegen_bridge.extract_frames` + `qa_service.summary` |
| POST | `/api/runs/{run_id}/states/{state}/refine` | — | `RefineResponse` | `spritegen_bridge.refine_frames` |

## Sprite Mode — Batch

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| POST | `/api/runs/{run_id}/batches` | `BatchStartRequest` | `BatchStartResponse` | `batch_service.start_batch` |
| GET | `/api/runs/{run_id}/batches/current` | — | `BatchStatus` | `batch_service.load_queue` (poll fallback) |
| WS | `/api/runs/{run_id}/batches/{job_id}/events` | — | stream of `BatchStatus` | pushes `batch_service.load_queue` on change (0.5s poll internally, only sends on an actual diff) instead of client-side polling; closes `1000` once a terminal status (`complete`/`failed`/`interrupted`/`corrupt`) is sent, `4404` if the run or its queue file doesn't exist, `4409` if `job_id` is not the run's current batch (a newer one replaced it, or it never matched) |

## Sprite Mode — Single-operation Jobs

The React Workspace submits heavy one-state operations here instead of holding
an HTTP request open until the engine returns. Only one single-operation job is
allowed per run at a time; Batch keeps its existing independent queue and API.

| Method | Path | Request | Response | Backend owner |
|---|---|---|---|---|
| POST | `/api/runs/{run_id}/jobs` | `JobStartRequest` | `JobStartResponse` (`202`) | `job_service.start_job` |
| GET | `/api/runs/{run_id}/jobs` | — | `JobListResponse` | `job_service.list_jobs` |
| GET | `/api/runs/{run_id}/jobs/{job_id}` | — | `JobStatusResponse` | `job_service.load_job` |
| POST | `/api/runs/{run_id}/jobs/{job_id}/cancel` | — | `JobStatusResponse` | cooperative `job_service.cancel_job` |
| POST | `/api/runs/{run_id}/jobs/{job_id}/retry` | — | `JobStartResponse` (`202`) | `job_service.retry_job` (failed/cancelled/interrupted only) |
| WS | `/api/runs/{run_id}/jobs/{job_id}/events` | — | stream of `JobStatusResponse` | pushes persisted job changes; closes `1000` at `succeeded`/`failed`/`cancelled`/`interrupted`, `4404` when the job is absent |

`JobStartRequest.operation` supports `generate`, `normalize`, `extract`,
`refine`, `repair_analyze`, `repair_safe`, `repair_decide`, `repair_undo`,
`repair_adopt`, `repair_unadopt`, `animation_qa`, `export_compose`,
`export_runtime`, `sequential_key_poses`, `sequential_inbetweens`, and
`sequential_promote`. `repair_decide` receives `options.candidate_ids` and
`options.accept`; `normalize` may retain the requested strategy in `options`
for audit/retry.

### Generation strategy / sequential animation

| Method | Path | Request | Response | Backend owner |
|---|---|---|---|---|
| GET | `/api/runs/{run_id}/states/{state}/strategy` | — | `GenerationStrategyResponse` | `strategy_service` |
| PUT | `/api/runs/{run_id}/states/{state}/strategy` | `StrategyUpdateRequest` | `GenerationStrategyResponse` | per-run strategy override + Motion Plan |
| POST | `/api/runs/{run_id}/states/{state}/motion-plan` | optional `StrategyUpdateRequest` | `GenerationStrategyResponse` | `strategy_service` |
| GET | `/api/runs/{run_id}/states/{state}/sequential` | — | `SequentialGenerationResponse` | sequential manifest read |
| POST | `/api/runs/{run_id}/states/{state}/sequential/key-poses` | — | `SequentialGenerationResponse` | provider-backed key-pose generation |
| POST | `/api/runs/{run_id}/states/{state}/sequential/approve` | `KeyPoseApproveRequest` | `SequentialGenerationResponse` | explicit key-pose approval |
| POST | `/api/runs/{run_id}/states/{state}/sequential/inbetweens` | — | `SequentialGenerationResponse` | identity + previous/next accepted key refs |
| POST | `/api/runs/{run_id}/states/{state}/sequential/promote` | — | `SequentialGenerationResponse` | publish approved sequence to canonical `frames/` + `frames-manifest.json` for Refine/QA |

## Sprite Mode — Review / Repair / AI Micro Fix

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| GET | `/api/runs/{run_id}/states/{state}/review` | — | `ReviewDataResponse` | `repair_service.review_data` + `qa_service.summary` + `history_service.summary` |
| POST | `/api/runs/{run_id}/states/{state}/repair/analyze` | — | `ReviewDataResponse` | `repair_service.analyze_state` |
| POST | `/api/runs/{run_id}/states/{state}/repair/safe` | — | `ReviewDataResponse` | `repair_service.analyze_state` + `repair_service.repair_state` |
| POST | `/api/runs/{run_id}/states/{state}/repair/decide` | `RepairDecideRequest` | `ReviewDataResponse` | `repair_service.decide_candidates` |
| POST | `/api/runs/{run_id}/states/{state}/repair/undo` | — | `ReviewDataResponse` | `repair_service.clear_repairs` |
| POST | `/api/runs/{run_id}/states/{state}/repair/adopt` | — | `ReviewDataResponse` | `repair_service.adopt_repaired` |
| POST | `/api/runs/{run_id}/states/{state}/repair/unadopt` | — | `ReviewDataResponse` | `repair_service.unadopt_repaired` |
| POST | `/api/runs/{run_id}/states/{state}/repair/ai-micro-fix/prepare` | `AiMicroFixPrepareRequest` | `AiMicroFixPrepareResponse` | `repair_service.prepare_ai_micro_fix` |
| POST | `/api/runs/{run_id}/states/{state}/repair/ai-micro-fix/apply` | `AiMicroFixApplyRequest` | `AiMicroFixApplyResponse` | `repair_service.apply_ai_micro_fix` |

## Sprite Mode — Anchor

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| GET | `/api/runs/{run_id}/anchors` | — | `AnchorStatusResponse` | `anchor_service.status` + `anchor_service.summary` |
| POST | `/api/runs/{run_id}/anchors/pin` | `AnchorPinRequest` | `AnchorStatusResponse` | `anchor_service.pin` |
| POST | `/api/runs/{run_id}/anchors/clear` | `AnchorClearRequest` | `AnchorStatusResponse` | `anchor_service.clear` |

## Sprite Mode — Animation QA / Curation / Export

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| POST | `/api/runs/{run_id}/states/{state}/animation-qa` | — | `AnimationQaResponse` | `spritegen_bridge.animation_qa` |
| POST | `/api/runs/{run_id}/curation` | — | `CurationLaunchResponse` | `spritegen_bridge.launch_curation` (spawns the existing curation server; the URL is opened in a new tab, not proxied) |
| POST | `/api/runs/{run_id}/export/compose` | — | `ComposeResponse` | `spritegen_bridge.extract_frames` + `export_service.compose` |
| POST | `/api/runs/{run_id}/export/runtime` | — | `RuntimeExportResponse` | `export_service.build_runtime` |

---

## Static Mode — Project

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| GET | `/api/static/presets` | — | `list[str]` | `preset_service.list_static_presets` |
| GET | `/api/static/presets/{preset_id}` | — | preset JSON (unmodeled passthrough) | `preset_service.load_static_preset` |
| POST | `/api/static` | `CreateStaticProjectRequest` | `StaticProjectSummary` | `static_service.create_project` |
| GET | `/api/static` | — | `list[StaticProjectSummary]` | `static_service.list_projects` |
| GET | `/api/static/{project_id}` | — | `StaticProjectSummary` | `static_service.load_project` |
| GET | `/api/static/{project_id}/status` | — | `StaticProjectStatusResponse` | `static_service.project_status` |

## Static Mode — Generate / Import / Refine / Cleanup / Tile / QA / Export

| Method | Path | Request | Response | Backend call |
|---|---|---|---|---|
| GET | `/api/static/{project_id}/prompt` | — | `StaticPromptResponse` | `StaticPromptAssembler().assemble` |
| POST | `/api/static/{project_id}/generate` | `StaticGenerateRequest` | `StaticGenerateResponse` | `static_service.generate_asset` |
| POST | `/api/static/{project_id}/import` | `StaticImportRequest` | `StaticGenerateResponse` | `static_service.import_asset` |
| POST | `/api/static/{project_id}/refine` | `StaticRefineRequest` | `StaticRefineResponse` | `static_service.refine_asset` |
| POST | `/api/static/{project_id}/cleanup` | `StaticCleanupRequest` | `StaticCleanupResponse` | `static_service.cleanup_asset` |
| POST | `/api/static/{project_id}/seam-check` | `StaticSeamRequest` (`repair=false`) | `StaticSeamResponse` | `static_service.check_tileability` |
| POST | `/api/static/{project_id}/seam-repair` | `StaticSeamRequest` (`repair=true`) | `StaticSeamResponse` | `static_service.check_tileability` |
| POST | `/api/static/{project_id}/layers/split` | `StaticLayersRequest` (`cutout=false`) | `StaticLayersResponse` | `static_service.process_layers` |
| POST | `/api/static/{project_id}/layers/cutout` | `StaticLayersRequest` (`cutout=true`) | `StaticLayersResponse` | `static_service.process_layers` |
| POST | `/api/static/{project_id}/qa` | — | `StaticQaResponse` | `static_service.static_qa` |
| POST | `/api/static/{project_id}/export` | — | `StaticExportResponse` | `static_service.export_asset` |

---

## Deliberately out of scope for this pass

- **Repair proposal image identity** (`repair_candidates` choices) stays a
  list of opaque candidate id strings — the client renders them next to the matching `repair_diff`
  asset by index, not by re-deriving meaning from the id.
- **`launch_curation`** keeps spawning the existing standalone curation HTTP
  server on its own port rather than being folded into this API — it is a
  large, already-working SPA (`sprite_studio/serve/curator`) with its own
  request/response contract; re-hosting it is a separate migration, not part
  of the FastAPI shell.
- Static Mode's `import_asset`/`generate_asset` `asset` parameter (which
  logical layer/asset name within a project, e.g. `"scene"`) is passed
  through as a plain `str` here, matching the backend's own contract — no
  enum, since presets do not enumerate a fixed asset-name set.
