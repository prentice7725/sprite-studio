# SPDX-License-Identifier: Apache-2.0
"""Pydantic request/response contract for the Sprite Studio API.

Source of truth for what `studio/api/*` routers accept and return (SPRITE_STUDIO_REACT_MIGRATION
directive). See ``ENDPOINTS.md`` next to this file for the full route -> model -> backend-function map.

Two shapes recur on purpose:

- Deeply-nested engine reports (`sprite_studio.gen.normalize_grok_row`'s
  segmentation/subjects payload, the refine lattice report, repair analysis)
  stay `dict[str, Any]` here rather than being re-modeled field by field. They
  are already self-describing JSON contracts owned by the engine layer
  (``*.report.json`` on disk); duplicating their shape here would just be a
  second place for them to drift out of sync. Only the OUTER envelope
  (status, timing, file paths) is typed.
- File references are represented as `str` **asset URLs** (``/api/runs/{run_id}/assets/...``),
  per the "no base64 blobs" rule — see ``ENDPOINTS.md`` §Assets. Uploads are handled
  by staging files through ``POST /api/uploads`` to acquire an ``upload_id``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

GenerationProfile = Literal["direct_pixel", "refine_first"]
Provider = Literal["grok", "codex"]
GenerationStrategy = Literal["AUTO", "ROW_FAST", "KEYPOSE_SEQUENTIAL"]
StaticAssetType = Literal["PIXEL_SCENE", "TILE_SET", "PROP_OBJECT", "FLAT_SCENE"]
BatchStatusKind = Literal["running", "complete", "failed", "interrupted", "corrupt"]
StageKind = Literal[
    "queued", "generating", "normalizing", "extracting", "refining", "repairing", "qa", "complete",
]
JobOperation = Literal[
    "generate", "normalize", "extract", "refine",
    "repair_analyze", "repair_safe", "repair_decide", "repair_undo",
    "repair_adopt", "repair_unadopt", "animation_qa",
    "export_compose", "export_runtime",
    "sequential_key_poses", "sequential_inbetweens", "sequential_promote",
    "quick_make",
]
JobStatusKind = Literal[
    "running", "succeeded", "failed", "cancel_requested", "cancelled", "interrupted",
]


# --------------------------------------------------------------------------
# Common
# --------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    detail: str


class ProviderStatusModel(BaseModel):
    name: str
    available: bool
    message: str
    detail: str | None = None


class UploadResponse(BaseModel):
    """POST /api/uploads — stages an uploaded file.
    `upload_id` is redeemed by a create/import/apply request below."""
    upload_id: str
    filename: str


# --------------------------------------------------------------------------
# Quick Generate — source-first front door
# --------------------------------------------------------------------------

QuickSourceKind = Literal["upload", "prompt"]
QuickSourceSelection = Literal["original", "pixelized"]
QuickMotion = Literal["idle", "walk", "run", "jump", "attack", "hurt", "custom"]
QuickStyle = Literal["pixel-art", "cel-shaded", "hand-painted", "3d-render"]
QuickBackground = Literal["transparent", "chroma"]
QuickDirectionCount = Literal[1, 4, 8]
QuickFrameCount = Literal[4, 6, 8]
QuickPixelSize = Literal[64, 96, 128, 192]
QuickPalette = Literal["auto", 16, 24, 32, 48]
QuickDither = Literal["none", "ordered-low", "ordered"]
QuickOutline = Literal["preserve", "auto"]
QuickSubjectMode = Literal["auto", "manual"]
QuickDetail = Literal["clean", "balanced", "detailed"]
QuickPixelMasterStrategy = Literal["preserve", "reference_pixel_master_128"]
QuickAcceptedArtifact = Literal["post"]


class QuickSessionCreateRequest(BaseModel):
    source_kind: QuickSourceKind
    upload_id: str | None = None
    reference_upload_id: str | None = None
    prompt: str = ""
    motion: QuickMotion = "idle"
    custom_motion: str = ""
    style: QuickStyle = "pixel-art"
    background: QuickBackground = "transparent"
    notes: str = ""
    provider: Provider = "grok"


class QuickSessionResponse(BaseModel):
    session_id: str
    run_id: str | None = None
    job_id: str | None = None
    source_kind: QuickSourceKind
    source_status: Literal["ready", "failed"]
    source_selection: QuickSourceSelection
    original_source: str
    pixelized_source: str | None = None
    pixelized_preview: str | None = None
    subject_source: str | None = None
    prompt: str
    motion: str
    style: QuickStyle
    background: QuickBackground
    notes: str
    provider: Provider


class QuickPixelizeRequest(BaseModel):
    strategy: QuickPixelMasterStrategy = "reference_pixel_master_128"
    accepted: QuickAcceptedArtifact = "post"
    size: QuickPixelSize = 128
    palette: QuickPalette = "auto"
    dither: QuickDither = "none"
    background: Literal["keep", "cleanup"] = "keep"
    outline: QuickOutline = "preserve"
    subject_mode: QuickSubjectMode = "auto"
    subject_bbox: tuple[int, int, int, int] | None = None
    detail: QuickDetail = "balanced"
    alpha_threshold: int = Field(default=128, ge=1, le=254)


class QuickPixelizeResponse(BaseModel):
    session_id: str
    strategy: QuickPixelMasterStrategy = "preserve"
    accepted: QuickAcceptedArtifact = "post"
    output_source: str
    preview_source: str
    subject_source: str
    subject_bbox: tuple[int, int, int, int]
    subject_candidates: list[dict[str, Any]]
    logical_size: tuple[int, int]
    palette_size: int
    palette: list[list[int]]
    warnings: list[dict[str, Any]]
    report: dict[str, Any]
    raw_source: str | None = None
    intermediate_source: str | None = None
    post_source: str | None = None

class QuickSourceSelectionRequest(BaseModel):
    source: QuickSourceSelection


class QuickMakeSpriteRequest(BaseModel):
    strategy: QuickPixelMasterStrategy = "reference_pixel_master_128"
    accepted: QuickAcceptedArtifact = "post"
    motion: QuickMotion = "idle"
    custom_motion: str = ""
    directions: QuickDirectionCount = 1
    frames: QuickFrameCount = 6
    pixelize: bool = False
    pixel_size: QuickPixelSize = 128
    palette: QuickPalette = "auto"
    dither: QuickDither = "none"
    background_cleanup: bool = False
    outline: QuickOutline = "preserve"
    subject_mode: QuickSubjectMode = "auto"
    subject_bbox: tuple[int, int, int, int] | None = None
    detail: QuickDetail = "balanced"
    alpha_threshold: int = Field(default=128, ge=1, le=254)
    sprite_source: QuickSourceSelection | None = None
    generation_strategy: GenerationStrategy = "AUTO"


class QuickMakeSpriteResponse(BaseModel):
    session: QuickSessionResponse
    run_id: str
    target_state: str
    job_id: str

# --------------------------------------------------------------------------
# Sprite Mode — Project / Runs (run_manager)
# --------------------------------------------------------------------------

class StateSpec(BaseModel):
    frames: int = Field(gt=0)
    fps: int = 8
    loop: bool = False
    action: str = ""


class CreateRunRequest(BaseModel):
    run_id: str
    character_id: str
    provider: Provider
    preset: str = "sword"
    description: str = ""
    directions: list[str]
    mirrors: dict[str, str] = Field(default_factory=dict)
    states: dict[str, StateSpec]
    cell_size: int = 256
    runtime_size: int = 48
    generation_profile: GenerationProfile = "refine_first"
    background_policy: str = "auto"
    # None = "Generate New" with no reference (§ base image is optional there;
    # only "Use Existing Image" requires one — enforced by the router, not
    # this model, since it is a cross-field UI-flow rule, not a shape rule).
    base_image_upload_id: str | None = None
    locks: dict[str, str] | None = None


class RunSummary(BaseModel):
    run_id: str
    character_id: str
    provider: str
    preset: str
    mode: str
    directions: list[str]
    states: list[str]


class RunDetail(RunSummary):
    cell_size: int
    runtime_size: int
    generation_profile: str
    background_policy: str
    refine: dict[str, Any]
    locks: dict[str, str]


class RunStatusResponse(BaseModel):
    """The PROJECT/MATRIX tab's per-state status column."""

    states: dict[str, str]


# --------------------------------------------------------------------------
# Sprite Mode — Prompt
# --------------------------------------------------------------------------

class PromptResponse(BaseModel):
    state: str
    prompt: str
    source: Literal["generated", "override"]


class PromptBlocksResponse(BaseModel):
    """GENERATE tab's "Prompt Assembly Preview" — the Studio extension blocks
    only (identity/style/negative), not the full merged prompt; see
    `studio.backend.prompt_service.assemble_for_run`."""

    state: str
    target_kind: Literal["single", "animation_row"]
    frame_count: int
    blocks: dict[str, str]


class SavePromptOverrideRequest(BaseModel):
    prompt: str = Field(min_length=1)


# --------------------------------------------------------------------------
# Sprite Mode — Generate / Normalize / Extract / Refine (per state)
# --------------------------------------------------------------------------

class GenerateResponse(BaseModel):
    provider: str
    prompt: str
    raw_asset: str  # asset URL, not the raw provider report's local out/raw paths
    raw_bytes: int
    elapsed_seconds: float
    model: str | None
    refs: list[str]  # asset URLs of the reference images actually attached
    transparent: bool
    prompt_source: Literal["generated", "override"]


class GenerateRequest(BaseModel):
    strategy: GenerationStrategy | None = None


class StrategyUpdateRequest(BaseModel):
    strategy: GenerationStrategy


class GenerationStrategyResponse(BaseModel):
    state: str
    requested: GenerationStrategy
    resolved: Literal["ROW_FAST", "KEYPOSE_SEQUENTIAL"]
    reason: str
    policy: dict[str, Any]
    motion_plan: dict[str, Any]
    motion_plan_asset: str | None = None


class KeyPoseApproveRequest(BaseModel):
    indices: list[int] = Field(min_length=1)


class NormalizeRequest(BaseModel):
    strategy: GenerationStrategy | None = None


class SequentialAssetResponse(BaseModel):
    index: int
    phase: str
    role: Literal["key", "between"]
    asset: str | None = None
    status: Literal["generated", "pending", "missing"]


class SequentialGenerationResponse(BaseModel):
    state: str
    status: str
    motion_plan: dict[str, Any]
    key_poses: list[SequentialAssetResponse] = Field(default_factory=list)
    inbetweens: list[SequentialAssetResponse] = Field(default_factory=list)
    promoted: bool = False
    promoted_assets: list[str] = Field(default_factory=list)


class NormalizeResponse(BaseModel):
    result: Literal["pass", "fail"]
    output_asset: str
    output_size: tuple[int, int]
    expected_subjects: int
    valid_subjects: int
    report: dict[str, Any]  # full sprite-studio-grok-row-normalization payload


class ExtractResponse(BaseModel):
    exit_code: int
    summary: str  # markdown, from qa_service.summary


class RefineResponse(BaseModel):
    refined_preview_asset: str | None
    report: dict[str, Any]  # asset-studio-sprite-refine payload (lattice/phase/palette)
    summary: str


# --------------------------------------------------------------------------
# Sprite Mode — Batch
# --------------------------------------------------------------------------

class BatchStartRequest(BaseModel):
    states: list[str] = Field(min_length=1)
    normalize: bool = True
    refine: bool = True
    repair: bool = False
    qa: bool = True


class BatchStartResponse(BaseModel):
    job_id: str


class BatchItemStatus(BaseModel):
    state: str
    status: str
    generate: dict[str, Any] | None = None
    normalize: dict[str, Any] | None = None
    normalize_error: str | None = None
    normalize_fallback: dict[str, Any] | None = None
    refine: dict[str, Any] | None = None
    repair_analysis: dict[str, Any] | None = None
    repair: dict[str, Any] | None = None
    qa: dict[str, Any] | None = None


class BatchStatus(BaseModel):
    """Mirrors `batch-queue.json` (batch_service._save's on-disk SSOT) field
    for field — the WebSocket event and the GET poll fallback both send this
    same shape (ENDPOINTS.md §Batch)."""

    job_id: str | None
    status: BatchStatusKind
    current_state: str | None
    current_stage: StageKind | None
    completed_items: int
    total_items: int
    progress_percent: float
    items: list[BatchItemStatus]
    error: str | None
    failed_state: str | None = None
    failed_stage: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: int | None = None


# --------------------------------------------------------------------------
# Sprite Mode — Single background jobs
# --------------------------------------------------------------------------

class JobStartRequest(BaseModel):
    operation: JobOperation
    state: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class JobStartResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    """Persisted single-operation job state and its JSON result envelope."""

    job_id: str
    operation: JobOperation
    state: str | None
    status: JobStatusKind
    current_stage: str
    progress_percent: float
    cancel_requested: bool = False
    attempt: int = 1
    parent_job_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    updated_at: str
    finished_at: str | None = None
    elapsed_seconds: int | None = None


class JobListResponse(BaseModel):
    jobs: list[JobStatusResponse]


# --------------------------------------------------------------------------
# Sprite Mode — Review / Repair / AI Micro Fix
# --------------------------------------------------------------------------

class GenerationVariantResponse(BaseModel):
    id: str
    timestamp: str | None = None
    provider: str
    model: str | None = None
    raw_asset: str | None = None


class RevisionVariantResponse(BaseModel):
    id: str
    label: str
    frames: int | None = None
    raw_asset: str | None = None
    exists: bool = False


class ReviewDataResponse(BaseModel):
    frames: list[str]
    refined_frames: list[str]
    repair_proposals: list[str]
    repaired_frames: list[str]
    repair_diff: list[str]
    repair_candidates: list[str]
    repair_summary: str
    qa_summary: str
    history_summary: str
    generation_variants: list[GenerationVariantResponse] = Field(default_factory=list)
    revision_variants: list[RevisionVariantResponse] = Field(default_factory=list)


class RepairDecideRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)
    accept: bool


class AiMicroFixPrepareRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)


class AiMicroFixPrepareResponse(BaseModel):
    job_id: str
    before_asset: str
    mask_asset: str
    job_dir: str


class AiMicroFixApplyRequest(BaseModel):
    job_id: str
    # The operator ran the prepared job through an external AI tool and is
    # handing back the result PNG — an upload, same as a base image.
    result_upload_id: str


class AiMicroFixApplyResponse(BaseModel):
    review: ReviewDataResponse
    pixels_changed: int


# --------------------------------------------------------------------------
# Sprite Mode — Anchor
# --------------------------------------------------------------------------

class AnchorPinRequest(BaseModel):
    state: str
    index: int = Field(ge=0)


class AnchorClearRequest(BaseModel):
    direction: str


class AnchorStatusResponse(BaseModel):
    summary: str
    directions: list[dict[str, Any]]


# --------------------------------------------------------------------------
# Sprite Mode — Animation QA / Curation
# --------------------------------------------------------------------------

class AnimationQaResponse(BaseModel):
    ok: bool
    warnings: list[str]
    summary: str


class CurationLaunchResponse(BaseModel):
    url: str


# --------------------------------------------------------------------------
# Sprite Mode — Export
# --------------------------------------------------------------------------

class ComposeResponse(BaseModel):
    sprite_sheet_asset: str
    manifest_asset: str


class RuntimeExportResponse(BaseModel):
    atlas_asset: str
    manifest_asset: str
    size: tuple[int, int]


# --------------------------------------------------------------------------
# Static Mode — Project (static_service)
# --------------------------------------------------------------------------

class CreateStaticProjectRequest(BaseModel):
    project_id: str
    provider: Provider
    asset_type: StaticAssetType = "PIXEL_SCENE"
    style_profile: str = "pixel_scene"
    description: str = ""
    base_image_upload_id: str | None = None
    tileable: bool = False
    export_size: tuple[int, int] = (1024, 1024)
    layer_intent: str = "none"
    background_policy: str = "auto"


class StaticProjectSummary(BaseModel):
    project_id: str
    provider: str
    asset_type: str
    style_profile: str
    tileable: bool
    export_size: tuple[int, int]
    layer_intent: str
    background_policy: str


class StaticProjectStatusResponse(BaseModel):
    assets: dict[str, str]


# --------------------------------------------------------------------------
# Static Mode — Generate / Import / Refine / Cleanup / Tile / QA / Export
# --------------------------------------------------------------------------

class StaticPromptResponse(BaseModel):
    prompt: str
    issues: list[str]


class StaticGenerateRequest(BaseModel):
    asset: str = "scene"
    prompt_override: str | None = None
    provider: Provider | None = None


class StaticGenerateResponse(BaseModel):
    asset: str
    provider: str
    elapsed_seconds: float
    out_asset: str


class StaticImportRequest(BaseModel):
    asset: str = "scene"
    upload_id: str


class StaticRefineRequest(BaseModel):
    asset: str = "scene"
    dither_mode: str = "off"
    fft_candidate_search: bool = True
    cleanup: bool = True


class StaticRefineResponse(BaseModel):
    output_asset: str
    report: dict[str, Any]  # grid/palette/sampling/warnings, unmodeled (see module docstring)


class StaticCleanupRequest(BaseModel):
    asset: str = "scene"
    orphan_max_area: int = 2
    hole_max_area: int = 4


class StaticCleanupResponse(BaseModel):
    output_asset: str
    report: dict[str, Any]


class StaticSeamRequest(BaseModel):
    asset: str = "scene"
    repair: bool = False


class StaticSeamResponse(BaseModel):
    wrap_preview_asset: str
    report: dict[str, Any]


class StaticLayersRequest(BaseModel):
    asset: str = "scene"
    cutout: bool = False


class StaticLayersResponse(BaseModel):
    layer_assets: list[str]
    report: dict[str, Any]


class StaticQaResponse(BaseModel):
    ok: bool
    asset_type: str
    warnings: list[dict[str, Any]]


class StaticExportResponse(BaseModel):
    export_asset: str
