"""Dependency and installation health checks for the complete KiWay suite."""

from __future__ import annotations

import importlib.util
import json
import re
import site
import subprocess
import sys
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class DependencySpec:
    key: str
    distribution: str
    module: str
    minimum: str
    level: str
    features: str

    @property
    def requirement(self) -> str:
        return f"{self.distribution}>={self.minimum}"


DEPENDENCIES: tuple[DependencySpec, ...] = (
    DependencySpec("networkx", "networkx", "networkx", "2.8", "required", "Connectivity graphs, tracing, and cross-project analysis"),
    DependencySpec("markdown", "Markdown", "markdown", "3.4", "recommended", "Full Markdown table and HTML report rendering"),
    DependencySpec("matplotlib", "matplotlib", "matplotlib", "3.5", "optional", "Native chart previews where the KiCad runtime supports them"),
    DependencySpec("pillow", "Pillow", "PIL", "9.0", "optional", "Annotated help-image generation and asset validation"),
)

SUITE_PACKAGES: tuple[tuple[str, str], ...] = (
    ("bulk_label_editor_plugin", "Bulk Label Editor"),
    ("connector_icd_plugin", "Connector ICD Builder"),
    ("extract_pins_plugin", "Extract Pins and Build ICD"),
    ("fanout_generator_plugin", "Fanout Generator"),
    ("net_hygiene_plugin", "Net Hygiene"),
    ("test_coverage_plugin", "Test Coverage Planner"),
    ("test_point_descriptor_plugin", "Test Point Descriptor"),
    ("trace_impedance_plugin", "Trace RLC / Impedance"),
    ("via_stitching_plugin", "Via Stitching"),
)


def _version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return ""


def _version_tuple(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", value)
    return tuple(int(number) for number in numbers[:4])


def inspect_dependencies() -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for spec in DEPENDENCIES:
        installed = importlib.util.find_spec(spec.module) is not None
        version = _version(spec.distribution) if installed else ""
        satisfied = installed and _version_tuple(version) >= _version_tuple(spec.minimum)
        result.append(
            {
                **asdict(spec),
                "requirement": spec.requirement,
                "installed": installed,
                "satisfied": satisfied,
                "status": "available" if satisfied else ("outdated" if installed else "missing"),
                "version": version,
            }
        )
    return result


def inspect_suite(plugin_root: Optional[str] = None) -> List[Dict[str, Any]]:
    root = Path(plugin_root).resolve() if plugin_root else Path(__file__).resolve().parents[1]
    rows: List[Dict[str, Any]] = []
    for folder, name in SUITE_PACKAGES:
        package = root / folder
        metadata_path = package / "metadata.json"
        version = ""
        identifier = ""
        if metadata_path.exists():
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                versions = data.get("versions") or []
                version = str(versions[0].get("version", "")) if versions else ""
                identifier = str(data.get("identifier", ""))
            except (OSError, ValueError, TypeError):
                pass
        rows.append(
            {
                "folder": folder,
                "name": name,
                "identifier": identifier,
                "installed": package.is_dir(),
                "status": "installed" if package.is_dir() else "missing",
                "version": version,
            }
        )
    return rows


def runtime_info(python_executable: Optional[str] = None) -> Dict[str, Any]:
    executable = str(Path(python_executable or sys.executable).resolve())
    return {
        "executable": executable,
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "user_site_enabled": bool(site.ENABLE_USER_SITE),
        "user_site": site.getusersitepackages(),
        "pip_available": importlib.util.find_spec("pip") is not None,
    }


def install_command(
    keys: Sequence[str],
    python_executable: Optional[str] = None,
    use_user_site: bool = True,
) -> List[str]:
    requested = set(keys)
    unknown = sorted(requested - {spec.key for spec in DEPENDENCIES})
    if unknown:
        raise ValueError(f"Unknown dependencies: {', '.join(unknown)}")
    requirements = [spec.requirement for spec in DEPENDENCIES if spec.key in requested]
    if not requirements:
        raise ValueError("No dependencies selected.")
    command = [python_executable or sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    if use_user_site:
        command.append("--user")
    return command + requirements


def install_dependencies(
    keys: Sequence[str],
    python_executable: Optional[str] = None,
    use_user_site: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    command = install_command(keys, python_executable, use_user_site)
    if dry_run:
        return {"command": command, "returncode": 0, "stdout": "", "stderr": "", "dry_run": True}
    if use_user_site and not site.ENABLE_USER_SITE:
        return {
            "command": command,
            "returncode": 1,
            "stdout": "",
            "stderr": "Python user-site packages are disabled for this interpreter.",
            "dry_run": False,
        }
    bootstrap_output = ""
    if importlib.util.find_spec("pip") is None:
        bootstrap = subprocess.run(
            [python_executable or sys.executable, "-m", "ensurepip", "--user"],
            capture_output=True,
            text=True,
            check=False,
        )
        bootstrap_output = "\n".join(part for part in (bootstrap.stdout.strip(), bootstrap.stderr.strip()) if part)
        if bootstrap.returncode:
            return {
                "command": command,
                "returncode": int(bootstrap.returncode),
                "stdout": bootstrap.stdout.strip(),
                "stderr": bootstrap.stderr.strip() or "Could not bootstrap pip with ensurepip.",
                "dry_run": False,
            }
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return {
        "command": command,
        "returncode": int(completed.returncode),
        "stdout": "\n".join(part for part in (bootstrap_output, completed.stdout.strip()) if part),
        "stderr": completed.stderr.strip(),
        "dry_run": False,
    }


def recommended_missing(include_optional: bool = False) -> List[str]:
    levels = {"required", "recommended"}
    if include_optional:
        levels.add("optional")
    return [
        row["key"]
        for row in inspect_dependencies()
        if not row["satisfied"] and row["level"] in levels
    ]


def health_report(plugin_root: Optional[str] = None) -> Dict[str, Any]:
    dependencies = inspect_dependencies()
    suite = inspect_suite(plugin_root)
    return {
        "runtime": runtime_info(),
        "dependencies": dependencies,
        "suite": suite,
        "healthy": all(row["satisfied"] for row in dependencies if row["level"] == "required")
        and all(row["installed"] for row in suite),
    }
