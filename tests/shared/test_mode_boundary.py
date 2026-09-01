# SPDX-License-Identifier: Apache-2.0
"""Architecture tests for mode boundaries.

Ensures Sprite Mode never reaches Static Mode modules (dither, tileable, seam, layers),
and Static Mode never uses Sprite Mode animation modules (lattice scope, temporal repair, animation qa).
"""

from __future__ import annotations

import ast
from pathlib import Path


def _collect_imports(file_path: Path) -> set[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def test_sprite_mode_does_not_import_static_mode():
    sprite_dir = Path(__file__).resolve().parents[2] / "studio" / "sprite_mode"
    for py_file in sprite_dir.rglob("*.py"):
        imported = _collect_imports(py_file)
        for imp in imported:
            assert "static_mode" not in imp, f"{py_file.name} violates boundary by importing {imp}"
            assert "dither" not in imp, f"{py_file.name} violates boundary by importing {imp}"


def test_static_mode_does_not_import_sprite_mode():
    static_dir = Path(__file__).resolve().parents[2] / "studio" / "static_mode"
    for py_file in static_dir.rglob("*.py"):
        imported = _collect_imports(py_file)
        for imp in imported:
            assert "sprite_mode" not in imp, f"{py_file.name} violates boundary by importing {imp}"
            assert "animation" not in imp, f"{py_file.name} violates boundary by importing {imp}"
