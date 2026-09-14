"""Canonical Kilo identifiers and read-only legacy compatibility constants."""

from __future__ import annotations

from pathlib import Path

PRODUCT_NAME = "WayriCAD Localizer"
PRODUCT_TITLE = "WayriCAD Localizer"
PROJECT_NAME = "wayricad-localizer"
CLI_NAME = "kilo"

CONTROL_DIRECTORY = ".kilo"
LEGACY_CONTROL_DIRECTORY = ".kicad-blockpack"
CONTROL_DIRECTORIES = (CONTROL_DIRECTORY, LEGACY_CONTROL_DIRECTORY)

STATE_SCHEMA = "kilo/state/v1"
TRANSACTION_SCHEMA = "kilo/transaction/v1"
PACKAGE_SCHEMA = "kilo/package/v1"
VALIDATION_SCHEMA = "kilo/validation/v1"
SCAN_SCHEMA = "kilo/scan/v1"

LEGACY_STATE_SCHEMA = "kicad-blockpack/state/v1"
LEGACY_TRANSACTION_SCHEMA = "kicad-blockpack/transaction/v1"
LEGACY_PACKAGE_SCHEMA = "kicad-blockpack/package/v1"
LEGACY_VALIDATION_SCHEMA = "kicad-blockpack/validation/v1"
LEGACY_SCAN_SCHEMA = "kicad-blockpack/scan/v1"

TRANSACTION_SCHEMAS = frozenset({TRANSACTION_SCHEMA, LEGACY_TRANSACTION_SCHEMA})
PACKAGE_SCHEMAS = frozenset({PACKAGE_SCHEMA, LEGACY_PACKAGE_SCHEMA})

MANIFEST_EMBEDDED_NAME = "kilo-manifest.json"
LEGACY_MANIFEST_EMBEDDED_NAME = "blockpack-manifest.json"
MANIFEST_EMBEDDED_NAMES = (MANIFEST_EMBEDDED_NAME, LEGACY_MANIFEST_EMBEDDED_NAME)


def control_path(project_root: Path) -> Path:
    """Return the canonical control directory used for all new writes."""

    return project_root / CONTROL_DIRECTORY


def existing_control_paths(project_root: Path) -> tuple[Path, ...]:
    """Return existing canonical and legacy control directories, new first."""

    return tuple(
        project_root / name
        for name in CONTROL_DIRECTORIES
        if (project_root / name).is_dir()
    )
