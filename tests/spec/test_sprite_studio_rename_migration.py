# SPDX-License-Identifier: MIT
"""은퇴한 `sprite-gen-*` kind -> 현행 `sprite-studio-*` 이관 (프로젝트 리네임).

`sprite-gen` 이 `sprite-studio` 로 이름이 바뀌면서 런 디렉터리에 기록된 `kind`
문자열도 옮겨간다. 이관 계약은 `pixel_perfect` -> `pixel_unfake` 때와 같다
(`tests/curate/test_pixel_unfake_migration.py`): 읽기는 메모리에서만 정규화하고
파일은 건드리지 않는다 · 디스크 이관은 명시 writer 에서만 · 멱등.

이 파일의 마지막 두 케이스가 **구조 단정**이다. 키 이름만 바꾸고 판독부를 게이트
뒤로 옮기지 않으면 이관 전 런에서 그 판독부만 조용히 틀린 답을 본다 — SKILL.md 의
리네임 게이트가 스윕보다 먼저 쓰라고 요구하는 단정이 이것이다.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from sprite_studio.spec.kinds import (
    CURRENT_KIND_PREFIX,
    RETIRED_KIND_PREFIX,
    document_has_retired_kind,
    kind_matches,
    load_normalized,
    migrate_document,
    normalize_document,
    normalize_kind,
)


ROOT = Path(__file__).resolve().parents[2]


def test_retired_kind_normalizes_to_the_current_prefix() -> None:
    assert normalize_kind("sprite-gen-request") == "sprite-studio-request"
    # 접두사 겹침: Studio kind 는 `sprite-gen-studio-` 였으므로 중복 이름이 되면 안 된다
    assert normalize_kind("sprite-gen-studio-run") == "sprite-studio-run"
    assert normalize_kind("sprite-gen-studio-frame-refine") == "sprite-studio-frame-refine"
    # 관계없는 값은 그대로 — 접두사 치환이 다른 어휘를 삼키면 안 된다
    assert normalize_kind("asset-studio-sprite-refine") == "asset-studio-sprite-refine"
    assert normalize_kind("geometry") == "geometry"
    assert normalize_kind(None) is None


def test_kind_matches_accepts_both_forms_so_a_legacy_run_is_not_falsely_rejected() -> None:
    """판독부가 쓰는 함수. 이관 전 런이 거짓 거부되면 안 된다."""
    assert kind_matches("sprite-gen-curation", "sprite-studio-curation")
    assert kind_matches("sprite-studio-curation", "sprite-studio-curation")
    assert not kind_matches("sprite-studio-recolor", "sprite-studio-curation")
    assert not kind_matches(None, "sprite-studio-curation")


def test_normalization_is_memory_only_and_does_not_mutate_the_caller(tmp_path) -> None:
    original = {"kind": "sprite-gen-request", "states": {"walk": {"kind": "sprite-gen-gif"}}}
    snapshot = json.dumps(original, sort_keys=True)
    normalized = normalize_document(original)

    assert normalized["kind"] == "sprite-studio-request"
    assert normalized["states"]["walk"]["kind"] == "sprite-studio-gif"
    # 호출부 dict 는 그대로다
    assert json.dumps(original, sort_keys=True) == snapshot


def test_reading_announces_once_per_run_and_leaves_the_file_alone(tmp_path, capsys) -> None:
    document = {"kind": "sprite-gen-request"}
    load_normalized(document, where="sprite-request.json", run_dir=tmp_path / "a")
    first = capsys.readouterr().err
    assert "migrate-kinds" in first and RETIRED_KIND_PREFIX in first

    load_normalized(document, where="sprite-request.json", run_dir=tmp_path / "a")
    assert capsys.readouterr().err == ""          # 같은 런은 다시 말하지 않는다

    load_normalized(document, where="sprite-request.json", run_dir=tmp_path / "b")
    assert "migrate-kinds" in capsys.readouterr().err   # 다른 런은 다시 말한다


def test_current_kinds_announce_nothing(capsys) -> None:
    load_normalized({"kind": "sprite-studio-request"}, where="x", run_dir="fresh")
    assert capsys.readouterr().err == ""


def test_migrate_document_is_idempotent() -> None:
    document = {"kind": "sprite-gen-request", "rows": [{"kind": "sprite-gen-gif"}]}
    migrated, moved = migrate_document(document)
    assert moved == 2
    assert not document_has_retired_kind(migrated)

    again, moved_again = migrate_document(migrated)
    assert moved_again == 0
    assert again == migrated



# --- 구조 단정 -------------------------------------------------------------
# 아래 두 케이스는 스윕보다 먼저 쓰였고, mutant 로 검증됐다
# (`test_the_structural_assertion_catches_a_reverted_reader` 가 그 mutant 를
# 이 파일 안에서 재현한다 — 단정이 통과만 하는 장식이 아님을 증명한다).

_GATE_MODULE = "kinds.py"
_KIND_COMPARISON_OPS = (ast.Eq, ast.NotEq)


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for package in ("sprite_studio", "studio"):
        files += sorted((ROOT / package).rglob("*.py"))
    files += sorted((ROOT / "scripts").glob("*.py"))
    return [path for path in files if "__pycache__" not in path.parts and path.name != _GATE_MODULE]


def _retired_kind_comparisons(tree: ast.AST) -> list[int]:
    """`<something> == "sprite-gen-..."` 형태의 직접 비교를 찾는다.

    **판정 단위를 비교 연산으로 잡는다.** 정규식으로 리터럴만 찾으면 상수에 담아
    다음 줄에서 비교하는 형태(`KIND = "sprite-gen-x"` … `!= KIND`)를 놓친다.
    그래서 상수 대입도 함께 본다.
    """
    offenders: list[int] = []
    literals: set[str] = set()
    for node in ast.walk(tree):
        # 모듈 상수에 은퇴 kind 를 담는 것도 판독부의 일부다
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                    if isinstance(node.value.value, str) and node.value.value.startswith(RETIRED_KIND_PREFIX):
                        literals.add(target.id)
                        offenders.append(node.lineno)
        if isinstance(node, ast.Compare) and any(isinstance(op, _KIND_COMPARISON_OPS) for op in node.ops):
            for side in [node.left, *node.comparators]:
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    if side.value.startswith(RETIRED_KIND_PREFIX):
                        offenders.append(node.lineno)
                if isinstance(side, ast.Name) and side.id in literals:
                    offenders.append(node.lineno)
    return sorted(set(offenders))


def test_no_production_path_compares_a_retired_kind_outside_the_gate() -> None:
    """프로덕션 코드가 은퇴 kind 를 직접 비교하지 않는다 (구조 단정).

    이게 이 리네임의 핵심 계약이다. 판독부를 게이트(`kind_matches`) 뒤로 옮기지
    않고 문자열만 바꾸면, 아직 이관되지 않은 런에서 그 판독부만 조용히 틀린 답을
    본다. 게이트 모듈 자신(`kinds.py`)은 은퇴 이름을 알아야 하므로 제외한다.
    """
    offenders: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno in _retired_kind_comparisons(tree):
            offenders.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not offenders, (
        "은퇴 kind 를 게이트 밖에서 직접 다룬다 — sprite_studio.spec.kinds.kind_matches 뒤로 옮겨라:\n"
        + "\n".join(offenders)
    )


def test_the_structural_assertion_catches_a_reverted_reader() -> None:
    """단정을 mutant 로 검증한다.

    통과만 하는 단정은 장식이고, 그걸 근거로 "구조로 닫았다" 고 말하면 거짓 보고가
    된다 (SKILL.md 리네임 게이트). 여기서는 실제 회귀 형태 두 가지를 일부러
    되돌려 단정이 정말 잡는지 본다: (1) 리터럴 직접 비교, (2) 상수에 담고 다음
    줄에서 비교 — 한 줄 정규식이 놓쳤던 그 형태.
    """
    literal_form = ast.parse(
        'def read(doc):\n'
        '    if doc.get("kind") != "sprite-gen-curation":\n'
        '        raise SystemExit("bad")\n'
    )
    assert _retired_kind_comparisons(literal_form), "리터럴 직접 비교를 놓쳤다"

    indirect_form = ast.parse(
        'REPORT_KIND = "sprite-gen-recolor-report"\n'
        'def read(doc):\n'
        '    if doc.get("kind") != REPORT_KIND:\n'
        '        raise SystemExit("bad")\n'
    )
    assert _retired_kind_comparisons(indirect_form), "상수 경유 비교를 놓쳤다 (정규식이 놓쳤던 형태)"

    # 게이트를 통과하는 형태는 잡지 않는다 (거짓 양성이면 단정이 못 쓰게 된다)
    gated_form = ast.parse(
        'from sprite_studio.spec.kinds import kind_matches\n'
        'def read(doc):\n'
        '    if not kind_matches(doc.get("kind"), "sprite-studio-curation"):\n'
        '        raise SystemExit("bad")\n'
    )
    assert not _retired_kind_comparisons(gated_form), "게이트를 쓴 코드를 거짓 양성으로 잡는다"


# --- 은퇴 환경변수 / 마이그레이션 명령 ---------------------------------------

def test_retired_env_var_is_not_a_silent_alias() -> None:
    """옛 이름을 설정해 둔 셸에서 그 설정이 조용히 무시되면 안 된다."""
    from sprite_studio.spec.kinds import assert_no_retired_env

    assert_no_retired_env({"SPRITE_STUDIO_ROOT": "/x", "PATH": "/bin"})   # 현행 이름은 통과
    with pytest.raises(SystemExit) as excinfo:
        assert_no_retired_env({"SPRITE_GEN_ROOT": "/x"})
    assert "SPRITE_STUDIO_ROOT" in str(excinfo.value)


def test_retired_env_guidance_names_the_variable_the_code_actually_reads() -> None:
    """안내가 존재하지 않는 이름을 알려주면 안내가 아니라 오도다.

    접두사가 겹쳐서(`SPRITE_GEN_STUDIO_*` vs `SPRITE_STUDIO_*`) 단순 치환은
    `SPRITE_STUDIO_STUDIO_RUNS_ROOT` 라는 없는 이름을 만들어냈다.
    """
    from studio.backend import run_manager, static_service
    from sprite_studio.spec.kinds import current_env_name

    assert current_env_name("SPRITE_GEN_STUDIO_RUNS_ROOT") == run_manager.RUNS_ROOT_ENV
    assert current_env_name("SPRITE_GEN_STUDIO_STATIC_ROOT") == static_service.PROJECTS_ROOT_ENV
    assert "STUDIO_STUDIO" not in current_env_name("SPRITE_GEN_STUDIO_RUNS_ROOT")


def test_migrate_kinds_is_dry_run_by_default_and_idempotent(tmp_path, capsys) -> None:
    """디스크를 바꾸는 곳은 이 명령 하나뿐이다 (`migrate-request` 와 같은 모양)."""
    from sprite_studio.cli import main

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "sprite-request.json").write_text(
        json.dumps({"kind": "sprite-gen-request"}), encoding="utf-8")
    (run_dir / "curation.json").write_text(
        json.dumps({"kind": "sprite-gen-curation", "rows": [{"kind": "sprite-gen-studio-run"}]}),
        encoding="utf-8")

    assert main(["migrate-kinds", str(run_dir)]) == 0
    assert "dry-run" in capsys.readouterr().out
    assert json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))["kind"] == "sprite-gen-request"

    assert main(["migrate-kinds", str(run_dir), "--apply"]) == 0
    capsys.readouterr()
    assert json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))["kind"] == "sprite-studio-request"
    # 접두사 겹침이 중복 이름을 만들지 않는다
    curation = json.loads((run_dir / "curation.json").read_text(encoding="utf-8"))
    assert curation["rows"][0]["kind"] == "sprite-studio-run"

    assert main(["migrate-kinds", str(run_dir), "--apply"]) == 0
    assert "옮길 것이 없다" in capsys.readouterr().out


def test_a_legacy_curation_file_is_not_falsely_rejected(tmp_path) -> None:
    """판독부가 게이트 뒤에 있는지 실제 파일로 확인한다 (거짓 거부 회귀 고정)."""
    from sprite_studio.curate.curation import CURATION_KIND
    from sprite_studio.spec.kinds import kind_matches

    assert kind_matches("sprite-gen-curation", CURATION_KIND)
    assert CURATION_KIND == "sprite-studio-curation"
