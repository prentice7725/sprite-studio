# SPDX-License-Identifier: Apache-2.0
"""POST /api/uploads storage — ENDPOINTS.md §Uploads.

An HTTP client cannot hand the server a local filesystem path the way an
in-process Gradio `gr.Image(type="filepath")` callback could; it uploads
bytes instead. This module owns where those bytes land and how a later
request (`base_image_upload_id`, `upload_id`, `result_upload_id` in
`studio.api.contracts`) redeems the id it got back for a real path a
`studio/backend/*` function can take.

Storage is content the API layer alone manages — one directory per upload,
named by an opaque id, holding exactly the uploaded file under its original
name (sanitized to a bare filename, no path components). It is deliberately
NOT under a run's own directory: an upload happens before a run/project
exists (that's the whole point of `base_image_upload_id`), so it has nowhere
else to live yet.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

UPLOADS_ROOT_ENV = "SPRITE_STUDIO_UPLOADS_ROOT"
_DEFAULT_UPLOADS_ROOT = ".uploads"


def uploads_root() -> Path:
    return Path(os.environ.get(UPLOADS_ROOT_ENV, _DEFAULT_UPLOADS_ROOT)).expanduser().resolve()


def save_upload(file: UploadFile) -> tuple[str, str]:
    """Persist `file`, return `(upload_id, filename)`.

    Validates the bytes decode as an image immediately (`Image.verify()`) —
    the base-image/import paths this feeds all eventually load it as an
    image too, so failing here is the same fail-fast preference the rest of
    this codebase already has (`verify_png` et al.), not new policy.
    """
    filename = Path(file.filename or "upload").name  # strip any path components a client sent
    if not filename:
        raise HTTPException(status_code=400, detail="upload has no filename")

    upload_id = uuid4().hex[:20]
    directory = uploads_root() / upload_id
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / filename
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    if dest.stat().st_size == 0:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    try:
        with Image.open(dest) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"uploaded file is not a readable image: {exc}") from exc

    return upload_id, filename


def resolve_upload(upload_id: str) -> Path:
    """The saved file path for a previously returned `upload_id`, or a 404
    if it was never uploaded (or was already redeemed and cleaned up —
    Phase 2 keeps uploads around for now; a later phase can add expiry)."""
    directory = uploads_root() / upload_id
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail=f"unknown upload_id: {upload_id!r}")
    files = [p for p in directory.iterdir() if p.is_file()]
    if not files:
        raise HTTPException(status_code=404, detail=f"upload {upload_id!r} has no file")
    return files[0]
