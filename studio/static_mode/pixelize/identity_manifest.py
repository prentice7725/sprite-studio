# SPDX-License-Identifier: Apache-2.0
"""Identity Feature Manifest (IFM) schema for information-preserving exports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


IdentityFeatureImportance = Literal["CRITICAL", "IMPORTANT", "OPTIONAL"]
IdentityFeatureKind = Literal[
    "SILHOUETTE", "FACE", "HAIR", "HEADGEAR", "BODY_PART", "GARMENT", "ACCESSORY",
    "WEAPON", "EMBLEM", "MARKING", "COLOR_BLOCK", "ASYMMETRY", "SPECIES_TRAIT", "OTHER",
]
Side = Literal["LEFT", "RIGHT", "CENTER"]
_IMPORTANCE_VALUES = {"CRITICAL", "IMPORTANT", "OPTIONAL"}
_KIND_VALUES = {
    "SILHOUETTE", "FACE", "HAIR", "HEADGEAR", "BODY_PART", "GARMENT", "ACCESSORY",
    "WEAPON", "EMBLEM", "MARKING", "COLOR_BLOCK", "ASYMMETRY", "SPECIES_TRAIT", "OTHER",
}
_SIDE_VALUES = {"LEFT", "RIGHT", "CENTER"}


def _normalize_side(value: Any) -> Side | None:
    if value is None:
        return None
    normalized = str(value).strip().upper().replace("_", "-")
    normalized = {
        "IMAGE-LEFT": "LEFT",
        "IMAGE-RIGHT": "RIGHT",
        "MIDDLE": "CENTER",
    }.get(normalized, normalized)
    if normalized not in _SIDE_VALUES:
        raise ValueError(f"unsupported feature side: {value}")
    return normalized  # type: ignore[return-value]


@dataclass(frozen=True)
class FeatureRegion:
    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.w, self.h)
        if any(value < 0.0 or value > 1.0 for value in values):
            raise ValueError("feature region values must be normalized to 0..1")
        if self.w <= 0.0 or self.h <= 0.0 or self.x + self.w > 1.0 or self.y + self.h > 1.0:
            raise ValueError("feature region must be a non-empty box inside 0..1")


@dataclass(frozen=True)
class IdentityFeature:
    id: str
    label: str
    importance: IdentityFeatureImportance
    kind: IdentityFeatureKind
    region: FeatureRegion | None = None
    must_remain_recognizable: bool = True
    must_remain_separated_from: tuple[str, ...] = ()
    must_remain_on_side: Side | None = None
    required_color_relation: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("identity feature id must not be empty")
        if not self.label.strip():
            raise ValueError("identity feature label must not be empty")
        if self.importance not in _IMPORTANCE_VALUES:
            raise ValueError(f"unsupported feature importance: {self.importance}")
        if self.kind not in _KIND_VALUES:
            raise ValueError(f"unsupported feature kind: {self.kind}")
        if self.must_remain_on_side is not None and self.must_remain_on_side not in _SIDE_VALUES:
            raise ValueError(f"unsupported feature side: {self.must_remain_on_side}")
        if not isinstance(self.must_remain_recognizable, bool):
            raise ValueError("must_remain_recognizable must be a boolean")


@dataclass(frozen=True)
class IdentityFeatureManifest:
    source_id: str
    features: tuple[IdentityFeature, ...]
    version: str = "ifm-v0.1"

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("Identity Feature Manifest source_id must not be empty")
        ids = [feature.id for feature in self.features]
        if len(ids) != len(set(ids)):
            raise ValueError("Identity Feature Manifest feature ids must be unique")
        known = set(ids)
        for feature in self.features:
            missing = set(feature.must_remain_separated_from) - known
            if missing:
                raise ValueError(f"feature {feature.id!r} references unknown features: {sorted(missing)}")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "IdentityFeatureManifest":
        def parse_feature(item: dict[str, Any]) -> IdentityFeature:
            region = item.get("region")
            return IdentityFeature(
                id=str(item["id"]),
                label=str(item["label"]),
                importance=str(item["importance"]),
                kind=str(item["kind"]),
                region=FeatureRegion(**region) if region else None,
                must_remain_recognizable=bool(item.get("mustRemainRecognizable", item.get("must_remain_recognizable", True))),
                must_remain_separated_from=tuple(item.get("mustRemainSeparatedFrom", item.get("must_remain_separated_from", ()))),
                must_remain_on_side=_normalize_side(item.get("mustRemainOnSide", item.get("must_remain_on_side"))),
                required_color_relation=item.get("requiredColorRelation", item.get("required_color_relation")),
                notes=item.get("notes"),
            )

        return cls(
            source_id=str(payload["source_id"]),
            version=str(payload.get("version", "ifm-v0.1")),
            features=tuple(parse_feature(item) for item in payload.get("features", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        def feature_dict(feature: IdentityFeature) -> dict[str, Any]:
            payload = asdict(feature)
            payload["mustRemainRecognizable"] = payload.pop("must_remain_recognizable")
            payload["mustRemainSeparatedFrom"] = payload.pop("must_remain_separated_from")
            payload["mustRemainOnSide"] = payload.pop("must_remain_on_side")
            payload["requiredColorRelation"] = payload.pop("required_color_relation")
            return payload

        return {"version": self.version, "source_id": self.source_id, "features": [feature_dict(feature) for feature in self.features]}


def manifest_from_json(path: str | Any) -> IdentityFeatureManifest:
    import json
    from pathlib import Path

    return IdentityFeatureManifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


__all__ = [
    "FeatureRegion",
    "IdentityFeature",
    "IdentityFeatureImportance",
    "IdentityFeatureKind",
    "IdentityFeatureManifest",
    "manifest_from_json",
]
