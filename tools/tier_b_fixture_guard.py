#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify the immutable Tier B benchmark source set.

This module deliberately has no source-generation or source-repair path. A
benchmark caller must invoke :func:`verify_tier_b_fixtures` before doing any
work that could create benchmark artifacts. The returned paths point directly
at the frozen files under ``benchmark_v2/sources/tier_b``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = ROOT / "benchmark_v2" / "sources" / "tier_b"
DEFAULT_MANIFEST = ROOT / "benchmark_v2" / "configs" / "tier_b_fixtures.json"
AI_METHODS = ("C1", "C2")


class TierBFixtureError(RuntimeError):
    """Raised when the frozen Tier B fixture set cannot be verified."""


@dataclass(frozen=True)
class TierBFixture:
    source_id: str
    path: Path
    expected_sha256: str
    actual_sha256: str


@dataclass(frozen=True)
class TierBFixtureSet:
    source_root: Path
    fixtures: tuple[TierBFixture, ...]

    def by_id(self) -> dict[str, TierBFixture]:
        return {fixture.source_id: fixture for fixture in self.fixtures}

    def path_for(self, source_id: str) -> Path:
        try:
            return self.by_id()[source_id].path
        except KeyError as exc:
            available = ", ".join(fixture.source_id for fixture in self.fixtures)
            raise TierBFixtureError(
                f"Tier B source {source_id!r} was not verified; available verified sources: {available}"
            ) from exc


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of *path* without changing it."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.is_file():
        raise TierBFixtureError(
            f"Tier B fixture manifest is missing: {path}. "
            "Do not generate or synthesize replacement fixtures."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TierBFixtureError(f"cannot read Tier B fixture manifest: {path}: {exc}") from exc
    if payload.get("version") != 1 or payload.get("policy") != "immutable-existing-files-only":
        raise TierBFixtureError(f"unsupported Tier B fixture manifest policy: {path}")

    entries = payload.get("required_sources")
    if not isinstance(entries, list) or not entries:
        raise TierBFixtureError(f"Tier B fixture manifest has no required_sources: {path}")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise TierBFixtureError(f"invalid Tier B fixture entry in {path}: {entry!r}")
        source_id = entry.get("id")
        filename = entry.get("file")
        expected = entry.get("sha256")
        if not isinstance(source_id, str) or not source_id.startswith("R"):
            raise TierBFixtureError(f"invalid Tier B source id in {path}: {source_id!r}")
        if source_id in seen_ids:
            raise TierBFixtureError(f"duplicate Tier B source id in {path}: {source_id}")
        if not isinstance(filename, str) or Path(filename).name != filename or Path(filename).suffix.lower() != ".png":
            raise TierBFixtureError(f"Tier B fixture must be a plain PNG filename: {filename!r}")
        if not isinstance(expected, str) or len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise TierBFixtureError(f"invalid SHA-256 for {source_id} in {path}: {expected!r}")
        seen_ids.add(source_id)
        normalized.append({"id": source_id, "file": filename, "sha256": expected})
    return tuple(normalized)


def verify_tier_b_fixtures(
    *,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
    required_ids: Iterable[str] | None = None,
) -> TierBFixtureSet:
    """Verify required Tier B files and return their frozen paths.

    Verification happens before callers receive any usable source path. Missing
    files, changed bytes, unsafe paths, or malformed manifest entries are hard
    failures. No missing-file bootstrap or image synthesis is intentionally
    provided.
    """

    source_root = source_root.resolve()
    entries = _load_manifest(manifest_path.resolve())
    requested = tuple(required_ids) if required_ids is not None else tuple(entry["id"] for entry in entries)
    requested_set = set(requested)
    by_id = {entry["id"]: entry for entry in entries}
    missing_manifest_ids = [source_id for source_id in requested if source_id not in by_id]
    if missing_manifest_ids:
        raise TierBFixtureError(
            "required Tier B sources are absent from the fixture manifest: "
            + ", ".join(missing_manifest_ids)
        )

    missing: list[str] = []
    mismatched: list[str] = []
    invalid_paths: list[str] = []
    verified: list[TierBFixture] = []
    for source_id in requested:
        entry = by_id[source_id]
        candidate = (source_root / entry["file"]).resolve()
        try:
            candidate.relative_to(source_root)
        except ValueError:
            invalid_paths.append(f"{source_id}={entry['file']}")
            continue
        if not candidate.is_file():
            missing.append(f"{source_id} ({candidate})")
            continue
        actual = sha256_file(candidate)
        if actual != entry["sha256"]:
            mismatched.append(f"{source_id} ({candidate} expected {entry['sha256']}, got {actual})")
            continue
        verified.append(TierBFixture(source_id, candidate, entry["sha256"], actual))

    if missing or mismatched or invalid_paths:
        details = [
            "Tier B benchmark fixtures failed immutable verification.",
            "No benchmark outputs were started and no replacement source may be created.",
        ]
        if missing:
            details.append("Missing required fixtures: " + "; ".join(missing))
        if mismatched:
            details.append("SHA-256 mismatches: " + "; ".join(mismatched))
        if invalid_paths:
            details.append("Unsafe fixture paths: " + "; ".join(invalid_paths))
        raise TierBFixtureError("\n".join(details))

    # Keep the requested order stable and reject duplicate requests explicitly.
    if len(requested_set) != len(requested):
        raise TierBFixtureError("required Tier B source ids contain duplicates")
    return TierBFixtureSet(source_root, tuple(verified))


def ai_reference_plan(fixtures: TierBFixtureSet, source_ids: Iterable[str] | None = None) -> dict[str, dict[str, Path]]:
    """Return C1/C2 references, sharing one exact frozen path per source.

    The same ``Path`` object is intentionally assigned to both methods. This
    prevents a C1/C2 caller from silently introducing separate redraws or
    alternate source copies for the same Rxx case.
    """

    ids = tuple(source_ids) if source_ids is not None else tuple(f.source_id for f in fixtures.fixtures)
    plan: dict[str, dict[str, Path]] = {}
    for source_id in ids:
        source_path = fixtures.path_for(source_id)
        plan[source_id] = {method: source_path for method in AI_METHODS}
        if plan[source_id]["C1"] is not plan[source_id]["C2"]:
            raise TierBFixtureError(f"C1/C2 reference identity diverged for {source_id}")
    return plan


__all__ = [
    "AI_METHODS",
    "DEFAULT_MANIFEST",
    "DEFAULT_SOURCE_ROOT",
    "TierBFixture",
    "TierBFixtureError",
    "TierBFixtureSet",
    "ai_reference_plan",
    "sha256_file",
    "verify_tier_b_fixtures",
]
