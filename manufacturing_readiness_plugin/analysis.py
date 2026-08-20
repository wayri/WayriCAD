"""Fabricator-profile audits and deterministic release manifests."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class FabricatorProfile:
    name: str = "Demo standard capability"
    minimum_track_mm: float = 0.15
    minimum_clearance_mm: float = 0.15
    minimum_drill_mm: float = 0.20
    minimum_annular_ring_mm: float = 0.10
    maximum_via_aspect_ratio: float = 10.0
    maximum_layers: int = 12


@dataclass
class BoardMetrics:
    minimum_track_mm: float
    minimum_clearance_mm: float
    minimum_drill_mm: float
    minimum_annular_ring_mm: float
    maximum_via_aspect_ratio: float
    copper_layers: int


@dataclass(frozen=True)
class ReadinessCheck:
    status: str
    item: str
    actual: str
    requirement: str


def audit_metrics(metrics: BoardMetrics, profile: FabricatorProfile) -> list[ReadinessCheck]:
    checks = []
    def minimum(item: str, actual: float, required: float, unit: str = "mm") -> None:
        checks.append(ReadinessCheck("PASS" if actual >= required else "FAIL", item,
                                     f"{actual:g} {unit}", f">= {required:g} {unit}"))
    minimum("Minimum routed track", metrics.minimum_track_mm, profile.minimum_track_mm)
    minimum("Minimum copper clearance", metrics.minimum_clearance_mm, profile.minimum_clearance_mm)
    minimum("Minimum finished drill", metrics.minimum_drill_mm, profile.minimum_drill_mm)
    minimum("Minimum annular ring", metrics.minimum_annular_ring_mm, profile.minimum_annular_ring_mm)
    checks.append(ReadinessCheck("PASS" if metrics.maximum_via_aspect_ratio <= profile.maximum_via_aspect_ratio else "FAIL",
                                 "Maximum via aspect ratio", f"{metrics.maximum_via_aspect_ratio:g}:1",
                                 f"<= {profile.maximum_via_aspect_ratio:g}:1"))
    checks.append(ReadinessCheck("PASS" if metrics.copper_layers <= profile.maximum_layers else "FAIL",
                                 "Copper layers", str(metrics.copper_layers), f"<= {profile.maximum_layers}"))
    return checks


def save_profile(path: str | Path, profile: FabricatorProfile) -> None:
    Path(path).write_text(json.dumps(asdict(profile), indent=2) + "\n", encoding="utf-8")


def load_profile(path: str | Path) -> FabricatorProfile:
    return FabricatorProfile(**json.loads(Path(path).read_text(encoding="utf-8")))


def build_release(output_zip: str | Path, files: list[str | Path], checks: list[ReadinessCheck],
                  tool_version: str) -> dict:
    failed = [check.item for check in checks if check.status == "FAIL"]
    if failed: raise ValueError("Release blocked by failed checks: " + ", ".join(failed))
    source_files = [Path(path) for path in files if Path(path).is_file()]
    manifest = {"tool": "KiWay Manufacturing Readiness Manager", "version": tool_version,
                "files": [], "checks": [asdict(check) for check in checks]}
    for source in sorted(source_files, key=lambda item: item.name.casefold()):
        manifest["files"].append({"name": source.name, "size": source.stat().st_size,
                                  "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    destination = Path(output_zip); destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in source_files: archive.write(source, source.name)
        archive.writestr("kiway-release-manifest.json", json.dumps(manifest, indent=2) + "\n")
    return manifest
