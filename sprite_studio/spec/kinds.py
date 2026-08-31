# SPDX-License-Identifier: Apache-2.0
"""은퇴한 `sprite-gen-*` kind -> 현행 `sprite-studio-*` 이관 게이트.

프로젝트 이름이 `sprite-gen` 에서 `sprite-studio` 로 바뀌면서, 런 디렉터리에
기록된 `kind` 문자열도 함께 옮겨간다. 그런데 kind 는 **이미 디스크에 쓰인 계약**이라
이름만 바꾸면 이관 전 런에서 판독부만 조용히 틀린 답을 본다 — `pixel_perfect`
리네임 때 리롤이 "언페이크가 꺼져 있다" 며 거짓 거부했던 것과 같은 기전이다
(SKILL.md 리네임 게이트).

그래서 계약은 그 때와 같다:

* **읽기는 메모리에서만 정규화한다.** 파일은 건드리지 않는다. 조회가 canonical
  런을 오염시키지 않는다.
* **디스크 이관은 명시 writer 에서만** — `sprite-studio migrate-kinds <run-dir> --apply`.
* **멱등** — 이미 현행 kind 뿐이면 옮길 것이 없다고 답하고 끝난다.
* **은퇴 이름은 조용한 별칭이 아니다.** 읽기는 통과시키되 한 번 안내하고, 계속
  쓰려면 이관하라고 말한다.

`kind` 는 스칼라 한 개라 `pixel_perfect` 때의 "두 키 동시 = hard fail" 은 여기
해당되지 않는다. 이름이 바뀐 사이드카(`.sprite-gen.lock`, `.sprite-gen.progress.json`)로
그 규칙을 옮겨 보려 했으나 **그 자리에는 두 진실이 생기지 않는다**: 둘 다 일시적
파일이고, 이관 뒤 남은 옛 잠금은 무시되는 것이 옳은 동작이다 (hard fail 을 걸면
멀쩡한 런이 열리지 않는다). 그래서 그 게이트는 두지 않는다 — 일어나지 않는
시나리오를 막는 코드는 보호가 아니라 장식이다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


RETIRED_KIND_PREFIX = "sprite-gen-"
CURRENT_KIND_PREFIX = "sprite-studio-"

# 접두사가 겹친다. Studio 계층 kind 는 은퇴 이름에서 `sprite-gen-studio-` 였으므로
# 단순 치환하면 `sprite-studio-studio-run` 이라는 중복 이름이 나온다. **긴 접두사를
# 먼저** 본다 — 순서를 뒤집으면 조용히 중복 이름이 만들어지고, 그 이름으로 쓰인
# 파일은 다시는 정규화되지 않는다.
_KIND_PREFIX_MAP: tuple[tuple[str, str], ...] = (
    ("sprite-gen-studio-", "sprite-studio-"),
    ("sprite-gen-", "sprite-studio-"),
)

# 안내 문구는 은퇴 이름을 **인용**한다. 이 문자열들은 리네임 스윕의 대상이 아니다
# (SKILL.md: "그 안내 문구 자체는 치환 대상에서 제외한다") — 안내가 새 이름만
# 말하면 사용자는 자기 파일에 있는 옛 이름과 연결하지 못한다.
_MIGRATION_HINT = (
    "retired kind prefix {retired!r} found in {where}; "
    "run `sprite-studio migrate-kinds {run_dir} --apply` to move it to {current!r}"
)

_announced: set[str] = set()


def is_retired_kind(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(RETIRED_KIND_PREFIX)


def normalize_kind(value: Any) -> Any:
    """은퇴 kind 를 현행 kind 로. 그 외 값은 그대로 돌려준다."""
    if not is_retired_kind(value):
        return value
    for retired, current in _KIND_PREFIX_MAP:
        if value.startswith(retired):
            return current + value[len(retired):]
    return value


def normalize_document(document: Any) -> Any:
    """문서 전체의 `kind` 를 재귀적으로 정규화한 **새 객체**를 만든다.

    호출부가 넘긴 dict 를 제자리에서 바꾸지 않는다 — 읽기가 호출부의 자료구조를
    조용히 바꾸면 그것도 부작용이다.
    """
    if isinstance(document, dict):
        out: dict[str, Any] = {}
        for key, value in document.items():
            out[key] = normalize_kind(value) if key == "kind" else normalize_document(value)
        return out
    if isinstance(document, list):
        return [normalize_document(item) for item in document]
    return document


def document_has_retired_kind(document: Any) -> bool:
    if isinstance(document, dict):
        if is_retired_kind(document.get("kind")):
            return True
        return any(document_has_retired_kind(value) for value in document.values())
    if isinstance(document, list):
        return any(document_has_retired_kind(item) for item in document)
    return False


def kind_matches(value: Any, expected: str) -> bool:
    """디스크에서 읽은 kind 가 기대하는 현행 kind 와 같은가 — 은퇴 형태도 통과.

    판독부는 이 함수를 쓴다. `value == expected` 로 직접 비교하면 이관 전 런에서
    그 판독부만 거짓으로 거부한다.
    """
    return normalize_kind(value) == normalize_kind(expected)


def announce_once(where: str, run_dir: Any = ".") -> None:
    """런당 한 번만 안내한다 — 파이프라인 한 번에 같은 줄을 수십 번 찍지 않는다."""
    token = f"{run_dir}:{where}"
    if token in _announced:
        return
    _announced.add(token)
    print(
        _MIGRATION_HINT.format(
            retired=RETIRED_KIND_PREFIX, where=where,
            current=CURRENT_KIND_PREFIX, run_dir=run_dir,
        ),
        file=sys.stderr,
    )


def load_normalized(document: Any, *, where: str, run_dir: Any = ".") -> Any:
    """읽기 경로용: 정규화하고, 옮길 것이 있으면 한 번 안내한다. 파일은 안 건드린다."""
    if document_has_retired_kind(document):
        announce_once(where, run_dir)
    return normalize_document(document)


def migrate_document(document: Any) -> tuple[Any, int]:
    """(정규화된 문서, 옮긴 kind 개수)."""
    moved = _count_retired(document)
    return normalize_document(document), moved


def _count_retired(document: Any) -> int:
    if isinstance(document, dict):
        total = 1 if is_retired_kind(document.get("kind")) else 0
        return total + sum(_count_retired(value) for value in document.values())
    if isinstance(document, list):
        return sum(_count_retired(item) for item in document)
    return 0


# --- 은퇴 환경변수 ----------------------------------------------------------
# 이름만 바꾸면 옛 이름을 설정해 둔 셸에서는 그 설정이 **조용히 무시된다** — 사용자는
# 자기가 지정한 런 루트가 아니라 기본값으로 도는 것을 눈치채지 못한다. 조용한 별칭도
# 두지 않는다 (SKILL.md: 은퇴 이름은 새 이름을 안내하며 hard error).
RETIRED_ENV_PREFIX = "SPRITE_GEN_"
CURRENT_ENV_PREFIX = "SPRITE_STUDIO_"

# kind 와 같은 접두사 겹침이 여기에도 있다: Studio 변수는 `SPRITE_GEN_STUDIO_*` 였고
# 현행 이름은 `SPRITE_STUDIO_*` 다. 긴 접두사를 먼저 보지 않으면 안내가
# `SPRITE_STUDIO_STUDIO_RUNS_ROOT` 라는, 존재하지도 않는 이름을 알려준다.
_ENV_PREFIX_MAP: tuple[tuple[str, str], ...] = (
    ("SPRITE_GEN_STUDIO_", "SPRITE_STUDIO_"),
    ("SPRITE_GEN_", "SPRITE_STUDIO_"),
)


def current_env_name(name: str) -> str:
    for retired, current in _ENV_PREFIX_MAP:
        if name.startswith(retired):
            return current + name[len(retired):]
    return name


def assert_no_retired_env(environ: "dict[str, str] | None" = None) -> None:
    """은퇴 이름의 환경변수가 설정돼 있으면 새 이름을 안내하며 죽는다."""
    import os

    source = os.environ if environ is None else environ
    retired = sorted(name for name in source if name.startswith(RETIRED_ENV_PREFIX))
    if not retired:
        return
    moved = ", ".join(f"{name} -> {current_env_name(name)}" for name in retired)
    raise SystemExit(
        "retired environment variable(s) set; this project reads the new names only "
        f"(a silent alias would let your setting be ignored without you noticing): {moved}"
    )
