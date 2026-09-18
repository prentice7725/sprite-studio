# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path

import pytest

from tools.tier_b_fixture_guard import (
    TierBFixtureError,
    ai_reference_plan,
    sha256_file,
    verify_tier_b_fixtures,
)


def _write_manifest(path: Path, filename: str, digest: str) -> Path:
    manifest = path / "fixtures.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "pixel-master-tier-b-fixtures",
                "source_root": "benchmark_v2/sources/tier_b",
                "policy": "immutable-existing-files-only",
                "required_sources": [{"id": "R01", "file": filename, "sha256": digest}],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_verification_returns_existing_fixture_without_writing(tmp_path: Path):
    source_root = tmp_path / "tier_b"
    source_root.mkdir()
    source = source_root / "R01.png"
    source.write_bytes(b"frozen fixture bytes")
    manifest = _write_manifest(tmp_path, source.name, sha256_file(source))

    verified = verify_tier_b_fixtures(source_root=source_root, manifest_path=manifest)

    assert verified.path_for("R01") == source.resolve()
    assert source.read_bytes() == b"frozen fixture bytes"


def test_missing_fixture_is_a_hard_failure(tmp_path: Path):
    source_root = tmp_path / "tier_b"
    source_root.mkdir()
    manifest = _write_manifest(tmp_path, "R01.png", "0" * 64)

    with pytest.raises(TierBFixtureError, match="Missing required fixtures"):
        verify_tier_b_fixtures(source_root=source_root, manifest_path=manifest)


def test_changed_fixture_is_a_hard_sha256_failure(tmp_path: Path):
    source_root = tmp_path / "tier_b"
    source_root.mkdir()
    source = source_root / "R01.png"
    source.write_bytes(b"original")
    manifest = _write_manifest(tmp_path, source.name, sha256_file(source))
    source.write_bytes(b"changed")

    with pytest.raises(TierBFixtureError, match="SHA-256 mismatches"):
        verify_tier_b_fixtures(source_root=source_root, manifest_path=manifest)


def test_c1_and_c2_share_the_same_frozen_reference_path(tmp_path: Path):
    source_root = tmp_path / "tier_b"
    source_root.mkdir()
    source = source_root / "R01.png"
    source.write_bytes(b"frozen fixture bytes")
    manifest = _write_manifest(tmp_path, source.name, sha256_file(source))
    fixtures = verify_tier_b_fixtures(source_root=source_root, manifest_path=manifest)

    references = ai_reference_plan(fixtures, ["R01"])

    assert references["R01"]["C1"] is references["R01"]["C2"]
    assert references["R01"]["C1"] == source.resolve()
