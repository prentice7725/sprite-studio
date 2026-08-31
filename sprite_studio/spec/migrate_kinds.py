# SPDX-License-Identifier: Apache-2.0
"""`sprite-studio migrate-kinds` — 은퇴 kind 를 디스크에서 옮긴다.

읽기 경로는 은퇴 kind 를 메모리에서만 정규화하고 파일은 건드리지 않는다
(`sprite_studio.spec.kinds`). 디스크를 바꾸는 곳은 여기 하나뿐이다 — 조회가
canonical 런을 오염시키지 않게 하려면 쓰기가 사용자가 부른 명령 안에서만
일어나야 한다 (`migrate-request` / `migrate-breathe` 와 같은 모양).

`--apply` 없이는 아무것도 쓰지 않고 무엇이 바뀔지만 말한다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sprite_studio.spec.kinds import document_has_retired_kind, migrate_document
from sprite_studio.spec.runio import atomic_write_text


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run_dir", type=Path, help="run directory to scan for retired kind strings")
    parser.add_argument(
        "--apply", action="store_true",
        help="rewrite the files (without this flag the command is a dry run)",
    )


def _json_files(run_dir: Path) -> list[Path]:
    return sorted(path for path in run_dir.rglob("*.json") if path.is_file())


def migrate_run(run_dir: Path, *, apply: bool = False) -> tuple[int, int]:
    """(옮길/옮긴 파일 수, kind 개수). 멱등 — 옮길 것이 없으면 (0, 0)."""
    files = 0
    kinds = 0
    for path in _json_files(run_dir):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 읽을 수 없는 파일은 조용히 건너뛰지 않고 남긴다 — 다만 이관 대상도 아니다.
            continue
        if not document_has_retired_kind(document):
            continue
        migrated, moved = migrate_document(document)
        files += 1
        kinds += moved
        if apply:
            atomic_write_text(path, json.dumps(migrated, ensure_ascii=False, indent=2) + "\n")
    return files, kinds


def run(**kwargs: object) -> int:
    # CLI 는 Namespace 가 아니라 키워드로 디스패치한다 (`migrate_request.run` 과 같은 규약).
    run_dir = Path(str(kwargs["run_dir"]))
    apply_changes = bool(kwargs.get("apply"))
    if not run_dir.is_dir():
        print(f"migrate-kinds: {run_dir} 가 없다")
        return 1
    files, kinds = migrate_run(run_dir, apply=apply_changes)
    if not files:
        print(f"{run_dir}: 옮길 것이 없다 (이미 현행 kind 뿐)")
        return 0
    if apply_changes:
        print(f"{run_dir}: {files}개 파일의 kind {kinds}개를 옮겼다")
    else:
        print(f"{run_dir}: dry-run — {files}개 파일의 kind {kinds}개가 바뀐다 (--apply 로 적용)")
    return 0
