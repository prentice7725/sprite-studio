# SPDX-License-Identifier: Apache-2.0
"""POST /api/uploads — ENDPOINTS.md §Uploads."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile

from studio.api.contracts import UploadResponse
from studio.api.uploads import save_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", response_model=UploadResponse, status_code=201)
def create_upload(file: UploadFile) -> UploadResponse:
    # A plain `def`, like every other route here — FastAPI runs it in a
    # threadpool, so the synchronous file I/O in `save_upload` (matching the
    # rest of this codebase's style) never blocks the event loop.
    upload_id, filename = save_upload(file)
    return UploadResponse(upload_id=upload_id, filename=filename)
