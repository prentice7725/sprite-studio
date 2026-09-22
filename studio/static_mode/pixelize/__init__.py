# SPDX-License-Identifier: Apache-2.0
"""Illustration-to-pixel-master pipeline."""

from .engine import (
    SUPPORTED_PALETTES,
    SUPPORTED_SIZES,
    DetailMode,
    PixelizeOptions,
    PixelizeResult,
    SubjectBox,
    SubjectMode,
    pixelize_file,
    pixelize_image,
)
from .logical_grid import LogicalGridResult, validate_and_unzoom
from .d1_d2 import D1Result, D2Result, SemanticPseOptions, d1_semantic_pse_file, d2_semantic_pse_file
from .d1_d2_auto import AutoD1Result, AutoD2Result, d1_semantic_auto_file, d2_semantic_auto_file
from .auto_resolution import AutoResolutionResult, project_auto_resolution
from .identity_manifest import FeatureRegion, IdentityFeature, IdentityFeatureManifest
from .information_loss_gate import InformationLossResult, SemanticPreservationResult, evaluate_information_loss, evaluate_semantic_preservation
from .resolution import AUTO_LOGICAL_HEIGHTS, LOGICAL_HEIGHTS
from .structure_extractor import LogicalMasterValidation, StructureExtractionResult, StructureExtractorOptions, extract_structure, validate_logical_master

__all__ = [
    "SUPPORTED_PALETTES",
    "SUPPORTED_SIZES",
    "DetailMode",
    "PixelizeOptions",
    "PixelizeResult",
    "SubjectBox",
    "SubjectMode",
    "pixelize_file",
    "pixelize_image",
    "LogicalGridResult",
    "validate_and_unzoom",
    "D1Result",
    "D2Result",
    "SemanticPseOptions",
    "d1_semantic_pse_file",
    "d2_semantic_pse_file",
    "AutoD1Result",
    "AutoD2Result",
    "d1_semantic_auto_file",
    "d2_semantic_auto_file",
    "AutoResolutionResult",
    "project_auto_resolution",
    "FeatureRegion",
    "IdentityFeature",
    "IdentityFeatureManifest",
    "InformationLossResult",
    "SemanticPreservationResult",
    "evaluate_information_loss",
    "evaluate_semantic_preservation",
    "AUTO_LOGICAL_HEIGHTS",
    "LOGICAL_HEIGHTS",
    "LogicalMasterValidation",
    "StructureExtractionResult",
    "StructureExtractorOptions",
    "extract_structure",
    "validate_logical_master",
]
