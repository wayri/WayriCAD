"""Local intent matching and revision-bound orchestration of WayriCAD tools.

The fuzzy matcher selects typed actions; it does not generate executable code,
shell commands, engineering results or hidden simulation inputs. Workers compile
the same allowlisted actions again before executing an existing tool CLI.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import unicodedata
import uuid

from .assistant_actions import ACTIONS, compile_action, _validate
from .jobs import load_json, terminate
from .tool_cli import command

SCHEMA = "wayricad.assistant-plan/v1"
ENGINE = "Local token/character fuzzy intent matcher 0.1"
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_LOG_BYTES = 8 * 1024 * 1024
_CATALOGUE = "assistant.catalogue"
_SPECS = dict(
    ACTIONS,
    **{
        _CATALOGUE: dict(
            tool="assistant",
            title="List available tools",
            phrases=["list available tools", "what can you do", "show tools", "help"],
            required=[],
            fields={},
            effect="inspect",
            summary="List supported local actions and inputs.",
        )
    },
)
_ALIASES = {
    "quick-pi": ["quick pi", "power integrity", "voltage drop", "ir drop", "dc rail"],
    "quick-therm": ["quick therm", "quicktherm", "thermal", "temperature"],
    "signal-integrity": ["quick si", "signal integrity", "crosstalk", "route delay"],
    "trace-impedance": ["rlc", "impedance", "microstrip", "stripline", "coplanar"],
    "fanout-generator": ["fanout", "fan out", "escape routing"],
    "silkscreen-label-placer": ["silkscreen", "reference labels", "place references"],
    "trace-refiner": ["trace refiner", "trace fixer", "refine traces", "routing kinks"],
    "component-arranger": ["arrange components", "component placement"],
    "mechanical-check": ["mechanical", "mechanics", "collisions"],
    "via-stitching": ["stitching", "stitch vias"],
    "bom-studio": ["analytics", "bom", "bill of materials"],
    "project-fusion": ["fusion", "import project"],
    "variant-manager": ["variants", "variant manager"],
    "extract-pins": ["extract pins", "pin inventory"],
    "embed-3d": ["3d models", "model links"],
    "copper-balancer": ["copper balance", "balance copper"],
    "layer-counter": ["layer counter", "layer numbering"],
    "protocol-constraints": ["constraints", "protocols"],
    "bulk-label-editor": ["rename labels", "bulk labels"],
    "harness-workbench": ["harness", "cable"],
    "heater-designer": ["heater"],
    "planar-magnetics": ["magnetics", "coil"],
    "manufacturing-readiness": ["manufacturing", "fabrication"],
}
_STOP = set(
    "a an the please can could would you me my this that on of for with to and run generate make get do i want using".split()
)


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _seal(plan):
    unsigned = {key: value for key, value in plan.items() if key != "plan_hash"}
    plan["plan_hash"] = hashlib.sha256(_canonical(unsigned).encode()).hexdigest()
    return plan


def _words(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"\b(?:analyse|analyze|analysing|analyzing)\b", "analysis", value)
    value = re.sub(r"\b(?:simulate|simulation|simulating)\b", "analysis", value)
    return [word for word in re.findall(r"[a-z0-9]+", value) if word not in _STOP]


def _grams(value):
    text = " ".join(_words(value))
    return {text[i : i + 3] for i in range(max(0, len(text) - 2))}


def _similarity(query, phrase):
    q, p = set(_words(query)), set(_words(phrase))
    if not q or not p:
        return 0.0
    coverage = len(q & p) / len(p)
    precision = len(q & p) / len(q)
    a, b = _grams(query), _grams(phrase)
    fuzzy = 2 * len(a & b) / max(1, len(a) + len(b))
    return 0.65 * coverage + 0.15 * precision + 0.2 * fuzzy


def _rank(query):
    normalized = " ".join(_words(query))
    help_requested = bool(
        re.search(r"\b(help|usage|commands|instructions)\b", query, re.I)
    )
    explicit = {
        tool
        for tool, aliases in _ALIASES.items()
        if any(
            re.search(r"\b" + re.escape(alias) + r"\b", normalized) for alias in aliases
        )
    }
    rows = []
    for identifier, spec in _SPECS.items():
        if spec["effect"] == "help" and not help_requested:
            continue
        score = max(
            (_similarity(query, phrase) for phrase in spec["phrases"]), default=0
        )
        if spec["tool"] in explicit:
            score += 0.22
        elif explicit and identifier != _CATALOGUE:
            score -= 0.18
        if help_requested:
            score += 0.35 if spec["effect"] == "help" else -0.15
        if identifier == _CATALOGUE and len(_words(query)) > 5:
            score -= 0.2
        if identifier.endswith(".inspect") and re.search(
            r"\b(list|inspect|show)\b", query, re.I
        ):
            score += 0.1
        if identifier == "trace-impedance.inspect" and re.search(
            r"\b(?:list|show)\s+(?:the\s+)?(?:nets|pads|layers)\b", query, re.I
        ):
            score = max(score, 0.95)
        if identifier == "trace-impedance.cross-section" and re.search(
            r"\b(microstrip|stripline|coplanar|cpw)\b", query, re.I
        ):
            score += 0.25
        if identifier == "trace-impedance.path" and re.search(
            r"\b(microstrip|stripline|coplanar|cpw)\b", query, re.I
        ):
            score -= 0.3
        if score > 0:
            rows.append(
                dict(
                    action=identifier,
                    title=spec["title"],
                    score=round(min(1.0, score), 4),
                )
            )
    return sorted(rows, key=lambda row: (-row["score"], row["action"]))


def _numeric(query, pattern, scale=1.0):
    match = re.search(pattern, query, re.I)
    return float(match.group(1)) * scale if match else None


def _slots(query):
    values = {}
    # Exact names are kept verbatim, including hierarchical net separators.
    match = re.search(r'\bnet\s+(?:["\']([^"\']+)["\']|([^\s,;]+))', query, re.I)
    if match:
        values["net"] = (match.group(1) or match.group(2)).rstrip(".")
    pair = re.search(r"\bfrom\s+([\w-]+\.[\w-]+)\s+to\s+([\w-]+\.[\w-]+)", query, re.I)
    if pair:
        values.update(
            source=pair.group(1),
            start=pair.group(1),
            sink=pair.group(2),
            end=pair.group(2),
        )
    for key in ("source", "sink", "start", "end", "anchor"):
        match = re.search(r"\b" + key + r"\s+([A-Za-z][\w.-]*)", query, re.I)
        if match:
            values[key] = match.group(1)
    refs = re.findall(r"\b[A-Z]{1,4}\d+\b", query)
    if refs:
        values["refs"] = list(dict.fromkeys(refs))
    numeric = {
        "voltage": (r"\b(?:voltage|at)\s*(\d+(?:\.\d+)?)\s*(?:v\b|volts?\b)", 1),
        "current": (r"(\d+(?:\.\d+)?)\s*mA\b", 0.001),
        "frequency_mhz": (r"(\d+(?:\.\d+)?)\s*MHz\b", 1),
        "rise_ns": (r"(?:rise(?:\s*time)?\s*=?\s*)(\d+(?:\.\d+)?)\s*ns\b", 1),
        "width_mm": (r"\bwidth\s*=?\s*(\d+(?:\.\d+)?)\s*mm\b", 1),
        "height_mm": (r"\b(?:height|separation)\s*=?\s*(\d+(?:\.\d+)?)\s*mm\b", 1),
        "copper_mm": (r"\bcopper\s*=?\s*(\d+(?:\.\d+)?)\s*(?:um|microns?)\b", 0.001),
        "gap_mm": (r"\bgap\s*=?\s*(\d+(?:\.\d+)?)\s*mm\b", 1),
        "er": (r"\b(?:er|permittivity)\s*=?\s*(\d+(?:\.\d+)?)", 1),
        "source_ohm": (
            r"\b(?:driver|source)\s*(?:resistance)?\s*(\d+(?:\.\d+)?)\s*(?:ohms?|\u03a9)",
            1,
        ),
        "ambient": (r"\b(?:ambient|at)\s*(-?\d+(?:\.\d+)?)\s*(?:C\b|celsius\b)", 1),
    }
    for key, (pattern, scale) in numeric.items():
        value = _numeric(query, pattern, scale)
        if value is not None:
            values[key] = value
    if "current" not in values:
        value = _numeric(query, r"(\d+(?:\.\d+)?)\s*(?:A\b|amps?\b)")
        if value is not None:
            values["current"] = value
    if "frequency_mhz" not in values:
        value = _numeric(query, r"(\d+(?:\.\d+)?)\s*GHz\b", 1000.0)
        if value is not None:
            values["frequency_mhz"] = value
    for topology in (
        "edge-coupled-stripline",
        "symmetric-stripline",
        "grounded-cpw",
        "microstrip",
        "cpw",
    ):
        if re.search(r"\b" + topology + r"\b", query, re.I):
            values["topology"] = topology
            break
    for key in ("power_field", "theta_ja_field"):
        match = re.search(
            r"\b" + key.replace("_", r"[_\s]") + r"\s*[=:]?\s*([\w.-]+)", query, re.I
        )
        if match:
            values[key] = match.group(1)
    return values


def _safe_context(context):
    if not isinstance(context, dict):
        raise ValueError("Context must be an object.")
    result = {}
    for key in ("board", "project", "schematic"):
        value = context.get(key)
        if value:
            if not isinstance(value, str) or len(value) > 4096 or "\x00" in value:
                raise ValueError("Invalid saved-file context.")
            result[key] = str(Path(value).expanduser().resolve())
    for key in ("selected_nets", "selected_refs", "nets"):
        value = context.get(key, [])
        if (
            not isinstance(value, list)
            or len(value) > 100000
            or any(not isinstance(x, str) or len(x) > 4096 for x in value)
        ):
            raise ValueError("Invalid selection context.")
        result[key] = value
    return result


def _input_hashes(paths):
    result = {}
    if len(set(paths)) > 300:
        raise ValueError("Too many input files.")
    for raw in sorted(set(paths)):
        path = Path(raw).resolve()
        if not path.is_file():
            raise ValueError("Saved input does not exist: " + str(path))
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("Input exceeds the 512 MiB source limit.")
        result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if len(result) > 300:
        raise ValueError("Too many input files.")
    return result


def _sheet_path(raw, directory, project_root, variables):
    """Resolve a declared sheet path without tolerating unknown variables."""
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or len(raw) > 4096
        or any(ord(c) < 32 for c in raw)
    ):
        raise ValueError("Invalid hierarchical schematic filename.")
    if raw.startswith("kicad-embed:"):
        raise ValueError("Extract embedded schematic sheets before analysis.")
    environment = dict(os.environ, **variables)
    environment["KIPRJMOD"] = str(project_root)
    value = raw
    seen = set()
    pattern = r"\$\{([^{}]+)\}|\$\(([^()]+)\)|\$([A-Za-z_]\w*)|%([^%]+)%"
    for _ in range(16):
        if value in seen:
            raise ValueError("Cyclic schematic filename variable.")
        seen.add(value)

        def expand(match):
            key = next(part for part in match.groups() if part is not None)
            if key not in environment:
                raise ValueError("Unresolved schematic filename variable: " + key)
            return environment[key]

        expanded = re.sub(pattern, expand, value)
        if expanded == value:
            if re.search(pattern, value) or "${" in value or "$(" in value:
                raise ValueError("Unresolved schematic filename variable.")
            break
        value = expanded
    else:
        raise ValueError("Schematic filename expansion exceeded its limit.")
    if len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid expanded schematic filename.")
    path = Path(value.replace("\\", "/")).expanduser()
    path = (path if path.is_absolute() else directory / path).resolve()
    if path.suffix.lower() != ".kicad_sch":
        raise ValueError("Hierarchical inputs must be modern .kicad_sch files.")
    return path


def _source_paths(context, compiled):
    """Bind saved inputs and complete schematic hierarchies within a shared budget.

    Repeated/cyclic sheet references are visited once per project. Missing sheets,
    malformed hierarchies and unresolved paths fail closed before workers launch.
    """
    from .schematic_sexpr import parse, properties

    paths = {}
    total = 0
    projects = {}
    pending = []
    visited = set()

    def add(raw):
        nonlocal total
        path = Path(raw).resolve()
        if path in paths:
            return path
        if not path.is_file():
            raise ValueError("Saved input does not exist: " + str(path))
        size = path.stat().st_size
        if len(paths) >= 300:
            raise ValueError("Too many input files; maximum is 300.")
        if size > MAX_SOURCE_BYTES or total + size > MAX_SOURCE_BYTES:
            raise ValueError("Saved inputs exceed the combined 512 MiB source limit.")
        paths[path] = size
        total += size
        return path

    initial = [
        value
        for key, value in context.items()
        if key in ("board", "project", "schematic")
    ]
    for step in compiled:
        initial.extend(step["input_files"])
    seeds = [add(raw) for raw in initial]
    for path in list(seeds):
        if path.suffix.lower() in (".kicad_pcb", ".kicad_pro", ".kicad_sch"):
            for suffix in (".kicad_pro", ".kicad_dru"):
                companion = path.with_suffix(suffix)
                if companion.is_file():
                    add(companion)
    for path in tuple(paths):
        if path.suffix.lower() != ".kicad_pro":
            continue
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("Project settings must be an object.")
        variables = document.get("text_variables", {})
        if not isinstance(variables, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in variables.items()
        ):
            raise ValueError("Project text variables must be text.")
        schematic = document.get("schematic", {})
        if not isinstance(schematic, dict):
            raise ValueError("Project schematic settings must be an object.")
        top = schematic.get("top_level_sheets", [])
        if not isinstance(top, list):
            raise ValueError("Project top-level sheets must be an array.")
        projects[path] = (path.parent, variables)
        root = path.with_suffix(".kicad_sch")
        if root.is_file():
            pending.append((add(root), path.parent, variables))
        for entry in top:
            if not isinstance(entry, dict):
                raise ValueError("Invalid project top-level sheet.")
            sheet = _sheet_path(
                entry.get("filename"), path.parent, path.parent, variables
            )
            pending.append((add(sheet), path.parent, variables))
    for path in seeds:
        if path.suffix.lower() == ".kicad_sch":
            project = path.with_suffix(".kicad_pro")
            project_root, variables = projects.get(project, (path.parent, {}))
            pending.append((path, project_root, variables))
    while pending:
        path, project_root, variables = pending.pop()
        key = (path, project_root, tuple(sorted(variables.items())))
        if key in visited:
            continue
        visited.add(key)
        tree = parse(path.read_text(encoding="utf-8-sig"))
        if tree.tag != "kicad_sch":
            raise ValueError("Expected a modern KiCad schematic: " + str(path))
        for sheet in tree.nodes("sheet"):
            fields = properties(sheet)
            raw = fields.get("Sheetfile", fields.get("Sheet file", ("",)))[0]
            child = _sheet_path(raw, path.parent, project_root, variables)
            pending.append((add(child), project_root, variables))
    return [str(path) for path in sorted(paths)]


def _compile(step, context, output_dir):
    if step["action"] == _CATALOGUE:
        if step["params"]:
            raise ValueError("Catalogue action takes no parameters.")
        return dict(
            tool="assistant",
            arguments=["capabilities", "--output", str(output_dir / "report.json")],
            outputs=["report.json"],
            documents={},
            input_files=[],
            assumptions=[],
        )
    return compile_action(step["action"], step["params"], context, output_dir)


def propose(query, context=None, answers=None):
    """Convert bounded English requests to a sealed, typed plan or questions.

    Answers use question keys such as ``0.net``; a single-step plan also accepts
    plain field names. ``action`` explicitly selects a clarification alternative.
    No process or model service is started by this function.
    """
    if (
        not isinstance(query, str)
        or not 1 <= len(query.strip()) <= 8192
        or "\x00" in query
    ):
        raise ValueError("Enter 1–8192 characters of task text.")
    context = _safe_context(context or {})
    answers = answers or {}
    if not isinstance(answers, dict) or len(answers) > 256:
        raise ValueError("Answers must be a bounded object.")
    plan = dict(
        schema=SCHEMA,
        query=query,
        engine=ENGINE,
        status="ready",
        context=context,
        steps=[],
        questions=[],
        alternatives=[],
        assumptions=[],
        sources={},
    )
    clauses = [
        part.strip(" ,.")
        for part in re.split(r"\b(?:and then|then|also)\b|[;\n]", query, flags=re.I)
        if part.strip(" ,. ")
    ]
    if not 1 <= len(clauses) <= 8:
        raise ValueError("Choose 1–8 tasks per request.")
    all_slots = _slots(query)
    for index, clause in enumerate(clauses):
        ranked = _rank(clause)
        choice = answers.get(
            f"{index}.action", answers.get("action") if len(clauses) == 1 else None
        )
        if choice is not None:
            if choice not in _SPECS:
                raise ValueError("Choose a listed Assistant action.")
            identifier = choice
        elif not ranked or ranked[0]["score"] < 0.47:
            plan["status"] = "unsupported"
            plan["alternatives"] = ranked[:4]
            continue
        elif len(ranked) > 1 and ranked[0]["score"] - ranked[1]["score"] < 0.055:
            plan["status"] = "ambiguous"
            plan["alternatives"] = ranked[:4]
            continue
        else:
            identifier = ranked[0]["action"]
        spec = _SPECS[identifier]
        slots = dict(all_slots, **_slots(clause))
        params = {}
        if (
            context.get("selected_nets")
            and "net" not in slots
            and len(context["selected_nets"]) == 1
        ):
            slots["net"] = context["selected_nets"][0]
        if context.get("selected_refs") and "refs" not in slots:
            slots["refs"] = context["selected_refs"]
        if "pattern" in spec["fields"] and spec["fields"]["pattern"].get("choices"):
            matches = [
                value
                for value in spec["fields"]["pattern"]["choices"]
                if value.casefold() in clause.casefold()
            ]
            if matches:
                slots["pattern"] = max(matches, key=len)
        for key, field in spec["fields"].items():
            value = answers.get(
                f"{index}.{key}", answers.get(key) if len(clauses) == 1 else None
            )
            if value is None:
                value = slots.get(
                    key, context.get(key) if key in ("board", "project") else None
                )
            if value is None:
                continue
            if key == "refs" and field["kind"] == "text" and isinstance(value, list):
                value = ",".join(value)
            if field["kind"] in ("list", "paths") and isinstance(value, str):
                value = [x.strip() for x in value.split(",") if x.strip()]
            if field["kind"] in ("number", "integer") and isinstance(value, str):
                try:
                    value = int(value) if field["kind"] == "integer" else float(value)
                except ValueError:
                    pass  # Validator produces the field-specific error.
            if field["kind"] == "boolean" and isinstance(value, str):
                value = {"true": True, "false": False, "yes": True, "no": False}.get(
                    value.casefold(), value
                )
            try:
                params[key] = _validate(value, field)
            except ValueError as exc:
                plan["questions"].append(
                    dict(field, key=f"{index}.{key}", error=str(exc))
                )
        missing = [key for key in spec["required"] if key not in params]
        if (
            identifier == "trace-impedance.cross-section"
            and params.get("topology")
            in ("cpw", "grounded-cpw", "edge-coupled-stripline")
            and "gap_mm" not in params
        ):
            missing.append("gap_mm")
        if (
            "net" in params
            and context.get("nets")
            and params["net"] not in context["nets"]
        ):
            exact = [
                n
                for n in context["nets"]
                if n.casefold() == str(params["net"]).casefold()
            ]
            if len(exact) == 1:
                params["net"] = exact[0]
            else:
                missing.append("net")
                params.pop("net")
        for key in dict.fromkeys(missing):
            question = dict(spec["fields"][key], key=f"{index}.{key}")
            if key == "net" and context.get("nets"):
                question["choices"] = context["nets"]
            plan["questions"].append(question)
        plan["steps"].append(
            dict(
                action=identifier,
                title=spec["title"],
                params=params,
                effect=spec["effect"],
            )
        )
    if plan["questions"] and plan["status"] == "ready":
        plan["status"] = "needs_input"
    plan["questions"] = list({item["key"]: item for item in plan["questions"]}.values())
    if not plan["steps"] and plan["status"] == "ready":
        plan["status"] = "unsupported"
    if plan["status"] == "ready":
        try:
            compiled = [
                _compile(step, context, Path.cwd() / ".assistant-preview" / f"step-{i}")
                for i, step in enumerate(plan["steps"])
            ]
            plan["sources"] = _input_hashes(_source_paths(context, compiled))
            plan["assumptions"] = list(
                dict.fromkeys(a for step in compiled for a in step["assumptions"])
            )
        except (ValueError, OSError) as exc:
            plan["status"] = "needs_input"
            plan["error"] = str(exc)
    return _seal(plan)


def validate_plan(plan):
    allowed = {
        "schema",
        "query",
        "engine",
        "status",
        "context",
        "steps",
        "questions",
        "alternatives",
        "assumptions",
        "sources",
        "plan_hash",
        "error",
    }
    if (
        not isinstance(plan, dict)
        or set(plan) - allowed
        or plan.get("schema") != SCHEMA
    ):
        raise ValueError("Invalid Assistant plan schema.")
    if len(_canonical(plan)) > 2 * 1024 * 1024:
        raise ValueError("Plan exceeds 2 MiB.")
    unsigned = {key: value for key, value in plan.items() if key != "plan_hash"}
    if (
        plan.get("plan_hash")
        != hashlib.sha256(_canonical(unsigned).encode()).hexdigest()
    ):
        raise ValueError("Plan changed after interpretation. Interpret again.")
    if plan.get("status") != "ready" or plan.get("questions"):
        raise ValueError("Resolve the plan questions before running.")
    if not isinstance(plan.get("steps"), list) or not 1 <= len(plan["steps"]) <= 8:
        raise ValueError("Invalid step count.")
    context = _safe_context(plan.get("context", {}))
    compiled = []
    for i, step in enumerate(plan["steps"]):
        if (
            not isinstance(step, dict)
            or set(step) != {"action", "title", "params", "effect"}
            or step["action"] not in _SPECS
        ):
            raise ValueError("Invalid typed step.")
        if step["effect"] != _SPECS[step["action"]]["effect"]:
            raise ValueError("Action effect changed.")
        compiled.append(
            _compile(step, context, Path.cwd() / ".assistant-preview" / f"step-{i}")
        )
    actual = _input_hashes(_source_paths(context, compiled))
    if actual != plan.get("sources"):
        raise ValueError("Saved inputs changed. Interpret the request again.")
    return plan


def capabilities():
    return dict(
        schema="wayricad.assistant-capabilities/v1",
        engine=ENGINE,
        local=True,
        model_download_required=False,
        shell_execution=False,
        board_mutation=False,
        actions=[dict(id=key, **value) for key, value in _SPECS.items()],
        limits=[
            "Bounded local intent/slot matching; not a general-purpose language model.",
            "Missing physics inputs and ambiguous actions require clarification.",
            "Design changes are previews; Apply remains in the originating tool.",
            "Only saved files are analyzed; save editor changes before running.",
        ],
    )


def _relative(root, value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(
            "Artifact paths must be relative to their private step directory."
        )
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Artifact escaped the run directory.")
    return target


def _write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        )


def _collect(directory):
    artifacts = []
    total = 0
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError(
                "A tool created a linked artifact; result is not accepted."
            )
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Artifact escaped its run directory.")
        if not path.is_file():
            continue
        total += path.stat().st_size
        if len(artifacts) >= 256 or total > 512 * 1024 * 1024:
            raise ValueError("Run artifacts exceeded the result budget.")
        if path.name in (
            "request.json",
            "worker.json",
            "settings.json",
            "stdout.log",
            "stderr.log",
        ):
            continue
        suffix = path.suffix.lower()
        kind = (
            "report"
            if suffix == ".html"
            else "image"
            if suffix in (".svg", ".png")
            else "data"
        )
        artifacts.append(
            dict(
                path=str(path.resolve()),
                label=path.name,
                kind=kind,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return artifacts


def _worker_path():
    return Path(__file__).with_name("assistant_worker.py")


def _read_log(path, limit):
    """Read only the displayed portion, even if a worker exits with a huge log."""
    with path.open("rb") as stream:
        return stream.read(limit).decode("utf-8", errors="replace")


def run_plan(
    plan, output_root, python=None, cancel=None, progress=None, timeout_seconds=600
):
    """Run a sealed read-only plan in owned, cancellable subprocesses.

    Each run owns a fresh result directory. Source hashes are checked before
    and after every step. Existing native tool validation is retained, and a
    nonzero process status is recorded rather than explained away as success.
    """
    validate_plan(plan)
    if (
        not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 3600
    ):
        raise ValueError("Choose a timeout of 1–3600 seconds.")
    cancel = cancel or threading.Event()
    progress = progress or (lambda message: None)
    parent = Path(output_root).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / (
        "run-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        + "-"
        + uuid.uuid4().hex[:10]
    )
    root.mkdir(exist_ok=False)
    _write_new(root / "plan.json", plan)
    result = dict(
        schema="wayricad.assistant-run/v1",
        status="completed",
        output_dir=str(root),
        query=plan["query"],
        engine=ENGINE,
        plan_hash=plan["plan_hash"],
        steps=[],
        artifacts=[],
    )
    try:
        for i, step in enumerate(plan["steps"]):
            if cancel.is_set():
                result["status"] = "cancelled"
                break
            validate_plan(plan)
            directory = root / f"step-{i + 1:02d}"
            directory.mkdir()
            compiled = _compile(step, plan["context"], directory)
            for name, document in compiled["documents"].items():
                _write_new(_relative(directory, name), document)
            request = dict(plan=plan, index=i, output_dir=str(directory))
            _write_new(directory / "worker.json", request)
            argv = [
                str(python or sys.executable),
                "-I",
                "-X",
                "utf8",
                str(_worker_path()),
                str(directory / "worker.json"),
            ]
            progress("Running " + step["title"])
            record = dict(
                action=step["action"],
                tool=compiled["tool"],
                title=step["title"],
                command=command(compiled["tool"], compiled["arguments"], python),
                status="running",
            )
            started = time.monotonic()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
            with (
                (directory / "stdout.log").open("wb") as out,
                (directory / "stderr.log").open("wb") as err,
            ):
                process = subprocess.Popen(
                    argv,
                    cwd=directory,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    creationflags=flags,
                    start_new_session=os.name != "nt",
                )
                try:
                    reason = None
                    while process.poll() is None:
                        if cancel.is_set():
                            reason = "cancelled"
                        elif time.monotonic() - started > timeout_seconds:
                            reason = "timed_out"
                        elif (
                            sum(
                                (directory / name).stat().st_size
                                for name in ("stdout.log", "stderr.log")
                            )
                            > MAX_LOG_BYTES
                        ):
                            reason = "log_limit"
                        if reason:
                            terminate(process)
                            break
                        cancel.wait(0.05)
                    record["exit_code"] = process.wait()
                    if (
                        sum(
                            (directory / name).stat().st_size
                            for name in ("stdout.log", "stderr.log")
                        )
                        > MAX_LOG_BYTES
                    ):
                        reason = "log_limit"
                finally:
                    # Reap even if monitoring, log I/O or cancellation raises.
                    terminate(process)
            record.update(
                seconds=time.monotonic() - started,
                stdout=_read_log(directory / "stdout.log", 262144),
                stderr=_read_log(directory / "stderr.log", 65536),
            )
            record["status"] = reason or (
                "completed" if record["exit_code"] == 0 else "failed"
            )
            validate_plan(plan)
            # A fixed tool may produce its report on stdout instead of a file.
            if record["stdout"].strip() and not (directory / "report.json").exists():
                try:
                    document = json.loads(record["stdout"])
                except ValueError:
                    document = {"text": record["stdout"]}
                _write_new(directory / "console-result.json", document)
            artifacts = _collect(directory)
            record["artifacts"] = artifacts
            result["artifacts"].extend(artifacts)
            result["steps"].append(record)
            if record["status"] != "completed":
                result["status"] = (
                    "cancelled" if reason == "cancelled" else "completed_with_errors"
                )
            if reason:
                break
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
    result["summary"] = (
        f"{sum(s['status'] == 'completed' for s in result['steps'])}/{len(plan['steps'])} tasks completed. "
        + (result.get("error") or result["status"].replace("_", " "))
    )
    index = root / "index.html"
    parts = [
        '<!doctype html><meta charset="utf-8"><title>WayriCAD Assistant results</title>',
        "<style>body{font:16px/1.5 system-ui;max-width:1000px;margin:2em auto;padding:0 1em}pre{white-space:pre-wrap}td,th{padding:.6em;border-bottom:1px solid #ccd}</style>",
        "<h1>WayriCAD Assistant</h1><p>"
        + escape(result["summary"])
        + "</p><p>"
        + escape(plan["query"])
        + "</p>",
        "<p>" + escape(ENGINE) + ". Numerical results come from the tools below.</p>",
    ]
    if plan["assumptions"]:
        parts.append(
            "<h2>Declared assumptions</h2><ul>"
            + "".join("<li>" + escape(item) + "</li>" for item in plan["assumptions"])
            + "</ul>"
        )
    parts.append(
        '<p><a href="plan.json">Inputs, source hashes and interpreted plan</a> · <a href="result.json">Complete run record</a></p>'
    )
    for step in result["steps"]:
        parts.append(
            "<h2>"
            + escape(step["title"])
            + "</h2><p>"
            + escape(step["status"])
            + "</p><ul>"
        )
        for artifact in step.get("artifacts", []):
            relative = Path(artifact["path"]).relative_to(root).as_posix()
            from urllib.parse import quote

            parts.append(
                '<li><a href="'
                + quote(relative)
                + '">'
                + escape(artifact["label"])
                + "</a></li>"
            )
        parts.append(
            "</ul><details><summary>Command and log</summary><pre>"
            + escape(subprocess.list2cmdline(step["command"]))
            + "\n"
            + escape(step["stdout"])
            + "\n"
            + escape(step["stderr"])
            + "</pre></details>"
        )
    with index.open("x", encoding="utf-8") as stream:
        stream.write("".join(parts))
    result["artifacts"].insert(
        0,
        dict(
            path=str(index),
            label="Combined report",
            kind="report",
            sha256=hashlib.sha256(index.read_bytes()).hexdigest(),
        ),
    )
    _write_new(root / "result.json", result)
    progress(result["summary"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    caps = sub.add_parser(
        "capabilities", help="Show supported typed actions and model limits."
    )
    caps.add_argument("--output", type=Path)
    plan = sub.add_parser("plan", help="Interpret English without running tools.")
    plan.add_argument("query")
    plan.add_argument("--board", type=Path)
    plan.add_argument("--project", type=Path)
    plan.add_argument("--answers", type=Path)
    plan.add_argument("--output", type=Path)
    run = sub.add_parser(
        "run", help="Execute a previously interpreted, unchanged read-only plan."
    )
    run.add_argument("plan", type=Path)
    run.add_argument("--output-root", type=Path, required=True)
    run.add_argument("--python", type=Path)
    run.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    try:
        if args.operation == "capabilities":
            result = capabilities()
        elif args.operation == "plan":
            result = propose(
                args.query,
                {
                    key: str(value)
                    for key in ("board", "project")
                    if (value := getattr(args, key))
                },
                load_json(args.answers) if args.answers else {},
            )
        else:
            result = run_plan(
                load_json(args.plan),
                args.output_root,
                args.python,
                timeout_seconds=args.timeout,
            )
        if getattr(args, "output", None):
            _write_new(args.output, result)
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0 if result.get("status", "ready") in ("ready", "completed") else 1
    except (
        OSError,
        ValueError,
        RuntimeError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
