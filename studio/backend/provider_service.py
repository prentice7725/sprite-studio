# SPDX-License-Identifier: Apache-2.0
"""Shared provider transport and generation adapter for Asset Studio."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sprite_studio.gen import GenResult, generate_image as _generate_image
from .schemas import ProviderStatus


def provider_status() -> list[ProviderStatus]:
    """Report CLI and availability status for supported generation backends."""
    result: list[ProviderStatus] = []
    for name in ("grok", "codex"):
        found = shutil.which(name)
        if not found:
            result.append(ProviderStatus(name, False, f"{name} CLI를 찾을 수 없습니다."))
        else:
            result.append(ProviderStatus(name, True, f"{name} CLI 사용 가능", found))
    return result


def generate_image(
    provider: str,
    prompt: str,
    out: Path,
    *,
    refs: list[Path] | None = None,
    model: str | None = None,
    aspect_ratio: str | None = None,
    transparent: bool = False,
    chroma_key: str = "magenta",
    white_check: Path | None = None,
    keep_session: bool = False,
    workdir: Path | None = None,
) -> GenResult:
    """Execute provider generation through the unified engine generator."""
    return _generate_image(
        provider=provider,
        prompt=prompt,
        out=out,
        refs=refs,
        model=model,
        aspect_ratio=aspect_ratio,
        transparent=transparent,
        chroma_key=chroma_key,
        white_check=white_check,
        keep_session=keep_session,
        workdir=workdir,
    )
