# SPDX-License-Identifier: Apache-2.0
"""Data contracts for non-destructive sprite repair."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RepairAction = Literal["add", "remove"]
RepairEngine = Literal["deterministic", "temporal", "ai_micro_fix", "manual"]


@dataclass(frozen=True)
class RepairCandidate:
    frame: int
    type: str
    action: RepairAction
    pixels: tuple[tuple[int, int], ...]
    confidence: float
    color: tuple[int, int, int, int] | None = None
    engine: RepairEngine = "deterministic"
    protected: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        coords = ";".join(f"{x},{y}" for x, y in self.pixels)
        return f"f{self.frame}:{self.engine}:{self.type}:{self.action}:{coords}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "frame": self.frame,
            "type": self.type,
            "action": self.action,
            "x": self.pixels[0][0] if self.pixels else None,
            "y": self.pixels[0][1] if self.pixels else None,
            "pixels": [list(pixel) for pixel in self.pixels],
            "confidence": round(self.confidence, 6),
            "color": list(self.color) if self.color is not None else None,
            "engine": self.engine,
            "protected": self.protected,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RepairCandidate":
        color = value.get("color")
        return cls(
            frame=int(value["frame"]),
            type=str(value["type"]),
            action=value["action"],
            pixels=tuple((int(x), int(y)) for x, y in value.get("pixels") or []),
            confidence=float(value["confidence"]),
            color=tuple(int(channel) for channel in color) if color is not None else None,
            engine=value.get("engine", "deterministic"),
            protected=bool(value.get("protected", False)),
            details=dict(value.get("details") or {}),
        )


@dataclass(frozen=True)
class RepairChange:
    candidate_id: str
    frame: int
    engine: RepairEngine
    rule: str
    action: RepairAction
    pixels: tuple[tuple[int, int], ...]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "frame": self.frame,
            "engine": self.engine,
            "rule": self.rule,
            "action": self.action,
            "pixels": [list(pixel) for pixel in self.pixels],
            "pixels_added": len(self.pixels) if self.action == "add" else 0,
            "pixels_removed": len(self.pixels) if self.action == "remove" else 0,
            "confidence": round(self.confidence, 6),
        }


@dataclass(frozen=True)
class RepairResult:
    frames: tuple[Any, ...]
    candidates: tuple[RepairCandidate, ...]
    changes: tuple[RepairChange, ...]
    skipped: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": len(self.candidates),
            "change_count": len(self.changes),
            "changes": [change.to_dict() for change in self.changes],
            "skipped": list(self.skipped),
        }
