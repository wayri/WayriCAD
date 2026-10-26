"""Bounded IBIS metadata catalog for reviewed KiCad-native IBIS assignments.

This module does not interpret I/V tables or simulate IBIS behaviour.  The
returned names are the file's original names, suitable for KiCad's Sim.Ibis
fields after validation against the same saved file hash.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_ENTRIES = 100_000
_KEYWORD = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$")
_MODEL_TYPE = re.compile(r"^Model_type\s*(?:=\s*)?(\S+)\s*$", re.IGNORECASE)
_CORNERS = ("typ", "min", "max")
_CORNER_FIELDS = ("vcc", "rpin", "lpin", "cpin")
_RESERVED = {"POWER", "GND", "NC"}
_SOURCE_TYPES = {
    "output", "3-state", "open_drain", "open_sink", "open_source",
    "output_ecl", "3-state_ecl", "i/o", "i/o_ecl", "i/o_open_drain",
    "i/o_open_sink", "i/o_open_source",
}
_SINK_TYPES = {
    "input", "input_ecl", "terminator", "i/o", "i/o_ecl",
    "i/o_open_drain", "i/o_open_sink", "i/o_open_source",
}


class IBISError(ValueError):
    """The IBIS metadata or proposed native assignment is unsafe to use."""


def _name(value: str, kind: str, limit: int = 40) -> str:
    if (not value or len(value) > limit or any(ord(c) < 33 or ord(c) > 126
                                            or c in "[]|" for c in value)):
        raise IBISError(f"Invalid {kind} name: {value!r}")
    return value


def _unique(names: set[str], name: str, kind: str) -> None:
    # IBIS readers differ in name case handling.  A case-only collision is
    # ambiguous when transferred to the native simulator, so reject it.
    folded = name.casefold()
    if folded in names:
        raise IBISError(f"Duplicate or case-ambiguous {kind}: {name!r}")
    names.add(folded)


def _roles(model_type: str) -> list[str]:
    value = model_type.casefold()
    return [role for role, types in (("source", _SOURCE_TYPES),
                                     ("sink", _SINK_TYPES)) if value in types]


def load_ibis(path: str | Path) -> dict:
    """Read only component, pin, model and selector metadata from a local .ibs.

    Returns a JSON-serializable catalog with absolute path and SHA-256.  Unknown
    keywords and electrical tables are intentionally skipped.  Unsupported
    model types remain visible with no assignable roles.
    """
    try:
        source = Path(path).expanduser().resolve(strict=True)
        if not source.is_file() or source.suffix.casefold() != ".ibs":
            raise IBISError("Choose an existing .ibs file")
        if source.stat().st_size > MAX_FILE_BYTES:
            raise IBISError(f"IBIS file exceeds {MAX_FILE_BYTES} bytes")
    except OSError as exc:
        raise IBISError(f"Cannot locate IBIS file: {exc}") from exc

    components: dict[str, dict] = {}
    models: dict[str, dict] = {}
    selectors: dict[str, dict] = {}
    component_names: set[str] = set()
    model_names: set[str] = set()
    selector_names: set[str] = set()
    pin_names: dict[str, set[str]] = {}
    selector_models: dict[str, set[str]] = {}
    digest = hashlib.sha256()
    comment = "|"
    section = ""
    component = ""
    model = ""
    selector = ""
    count = 0
    total = 0
    try:
        with source.open("rb") as stream:
            while raw := stream.readline(MAX_LINE_BYTES + 1):
                total += len(raw)
                if total > MAX_FILE_BYTES:
                    raise IBISError("IBIS file changed beyond size limit while reading")
                if len(raw) > MAX_LINE_BYTES:
                    raise IBISError("IBIS line exceeds size limit")
                digest.update(raw)
                if section == "end":
                    continue
                line = raw.decode("latin-1").strip()
                if not line:
                    continue
                # The declaration itself uses the *previous* comment marker.
                match = _KEYWORD.match(line)
                if match and match.group(1).strip().casefold() == "comment char":
                    candidate = match.group(2).strip()
                    if not candidate or candidate[0].isspace() or candidate[0] in "[]":
                        raise IBISError("Invalid [Comment char] declaration")
                    comment = candidate[0]
                    section = ""
                    continue
                line = line.split(comment, 1)[0].strip()
                if not line:
                    continue
                match = _KEYWORD.match(line)
                if match:
                    section = match.group(1).strip().casefold()
                    value = match.group(2).strip()
                    if section == "component":
                        component = _name(value, "component")
                        _unique(component_names, component, "component")
                        components[component] = {"pins": {}}
                        pin_names[component] = set()
                    elif section == "model":
                        model = _name(value, "model")
                        _unique(model_names, model, "model")
                        if model.casefold() in selector_names:
                            raise IBISError(f"Ambiguous IBIS model/selector name: {model!r}")
                        models[model] = {"model_type": "", "roles": []}
                    elif section == "model selector":
                        selector = _name(value, "selector")
                        _unique(selector_names, selector, "selector")
                        if selector.casefold() in model_names:
                            raise IBISError(f"Ambiguous IBIS model/selector name: {selector!r}")
                        selectors[selector] = {"models": []}
                        selector_models[selector] = set()
                    if section == "end":
                        continue
                    continue
                if section == "pin":
                    if not component:
                        raise IBISError("[Pin] occurs before [Component]")
                    fields = line.split()
                    if fields[0].casefold() in {"pin", "pin_name", "signal_name"}:
                        continue
                    if len(fields) < 3:
                        raise IBISError(f"Malformed [Pin] row in {component!r}")
                    pin, signal_name, model_name = fields[:3]
                    pin = _name(pin, "pin", 80)
                    signal_name = _name(signal_name, "signal", 80)
                    model_name = _name(model_name, "pin model")
                    pins = components[component]["pins"]
                    _unique(pin_names[component], pin, "pin")
                    pins[pin] = {"signal_name": signal_name, "model_name": model_name}
                    count += 1
                elif section == "model":
                    match = _MODEL_TYPE.match(line)
                    if match:
                        if models[model]["model_type"]:
                            raise IBISError(f"Duplicate Model_type in {model!r}")
                        model_type = _name(match.group(1), "model type")
                        models[model] = {"model_type": model_type,
                                         "roles": _roles(model_type)}
                elif section == "model selector":
                    fields = line.split()
                    selected = _name(fields[0], "selector model")
                    _unique(selector_models[selector], selected,
                            f"model in selector {selector!r}")
                    selectors[selector]["models"].append(selected)
                    count += 1
                if count > MAX_ENTRIES or len(components) + len(models) + len(selectors) > MAX_ENTRIES:
                    raise IBISError("IBIS catalog exceeds entry limit")
    except OSError as exc:
        raise IBISError(f"Cannot read IBIS file: {exc}") from exc
    if not components or not models:
        raise IBISError("IBIS file has no components or models")
    if any(not item["model_type"] for item in models.values()):
        raise IBISError("IBIS model is missing Model_type")
    if any(not item["models"] for item in selectors.values()):
        raise IBISError("IBIS model selector is empty")
    return {"path": str(source), "sha256": digest.hexdigest(),
            "components": components, "models": models, "selectors": selectors}


def _normalize_corners(corner: str | dict[str, str]) -> dict[str, str]:
    if isinstance(corner, str):
        values = {field: corner for field in _CORNER_FIELDS}
    elif isinstance(corner, dict) and set(corner) == set(_CORNER_FIELDS):
        values = dict(corner)
    else:
        raise IBISError("Corner must be typ|min|max or a vcc/rpin/lpin/cpin mapping")
    if any(value not in _CORNERS for value in values.values()):
        raise IBISError("IBIS corners must be typ, min or max")
    return values


def assignment_from_catalog(catalog: dict, component: str, pin: str,
                            model: str, role: str,
                            corner: str | dict[str, str] = "typ") -> dict:
    """Validate a selection against a previously loaded catalog, without I/O.

    This is suitable for repeated UI selection changes.  Recheck the file hash
    with ``validate_assignment`` or ``load_ibis`` before publishing an export.
    """
    components = catalog["components"]
    if component not in components:
        raise IBISError(f"Unknown IBIS component: {component!r}")
    pins = components[component]["pins"]
    if pin not in pins:
        raise IBISError(f"Pin {pin!r} is not in component {component!r}")
    pin_model = pins[pin]["model_name"]
    if pin_model.upper() in _RESERVED:
        raise IBISError(f"Pin {pin!r} is {pin_model}, not a signal model")
    if pin_model in catalog["selectors"]:
        allowed = catalog["selectors"][pin_model]["models"]
        if model not in allowed:
            raise IBISError(f"Model {model!r} is not in selector {pin_model!r}")
    elif model != pin_model:
        raise IBISError(f"Pin {pin!r} requires model {pin_model!r}")
    if model not in catalog["models"]:
        raise IBISError(f"Selected IBIS model {model!r} is missing")
    if role not in ("source", "sink"):
        raise IBISError("Role must be source or sink")
    info = catalog["models"][model]
    if role not in info["roles"]:
        raise IBISError(f"IBIS {info['model_type']} model {model!r} cannot be {role}")
    return {"path": catalog["path"], "sha256": catalog["sha256"],
            "component": component, "pin": pin, "model": model,
            "model_type": info["model_type"], "role": role,
            "corners": _normalize_corners(corner)}


def validate_assignment(path: str | Path, component: str, pin: str,
                        model: str, role: str, corner: str | dict[str, str] = "typ",
                        expected_sha256: str | None = None) -> dict:
    """Validate one exact pin/model/role against current file bytes.

    Pass the SHA-256 from the reviewed catalog as ``expected_sha256`` to
    reject changed source files before producing KiCad fields.
    """
    catalog = load_ibis(path)
    if expected_sha256 is not None and catalog["sha256"] != expected_sha256:
        raise IBISError("IBIS file changed since catalog review")
    return assignment_from_catalog(catalog, component, pin, model, role, corner)
