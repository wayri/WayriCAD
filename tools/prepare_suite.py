"""Regenerate the common IPC manifests and package dependencies."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    for source in sorted(ROOT.glob("*/metadata.json")):
        folder = source.parent
        metadata = json.loads(source.read_text(encoding="utf-8"))
        short_name = folder.name.removesuffix("_plugin").replace("_", "-")
        short_name = {"protocol-constraint-composer": "protocol-constraints", "test-point-descriptor": "test-points"}.get(short_name, short_name)
        metadata["identifier"] = "com.github.wayri.wayricad." + short_name
        metadata["$schema"] = "https://go.kicad.org/pcm/schemas/v2"
        # The distributed bundle includes the GPL suite runtime; imported MIT notices remain intact.
        metadata["license"] = "GPL-3.0-only"
        for version in metadata["versions"]:
            version.update(version="3.0.0", runtime="ipc", kicad_version="10.0", status="testing")
            for key in list(version):
                if key.startswith("download_") or key in {"install_size", "kicad_version_max"}:
                    del version[key]
        write_json(source, metadata)
        entrypoint = "desktop_entrypoint.py" if folder.name == "bom_studio_plugin" else "ipc_entrypoint.py"
        manifest = {
            "$schema": "https://go.kicad.org/api/schemas/v1",
            "identifier": metadata["identifier"], "name": metadata["name"],
            "description": metadata["description"],
            "runtime": {"type": "python", "min_version": "3.10.0"},
            "actions": [{"identifier": "open", "name": metadata["name"],
                "description": metadata["description"], "show-button": True,
                "scopes": ["pcb"], "entrypoint": entrypoint,
                "icons-light": [f"resources/icon-{n}.png" for n in (24, 48, 96)],
                "icons-dark": [f"resources/icon-dark-{n}.png" for n in (24, 48, 96)]}],
        }
        write_json(folder / "plugin.json", manifest)
        if entrypoint == "ipc_entrypoint.py":
            candidates = []
            for path in sorted(folder.rglob("*.py")):
                if "tests" in path.parts:
                    continue
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                    if isinstance(node, ast.ClassDef) and any("ActionPlugin" in ast.unparse(b) for b in node.bases):
                        candidates.append((path, node.name))
            if not candidates:
                raise ValueError(f"No action class in {folder}")
            path, classname = candidates[0]
            write_json(folder / "wayricad-tool.json", {
                "tool": folder.name, "name": metadata["name"],
                "module": ".".join(path.relative_to(folder).with_suffix("").parts), "class": classname,
            })
            (folder / entrypoint).write_text(
                '"""KiCad IPC entry point; shared runtime is bundled by build_pcm.py."""\n'
                'from pathlib import Path\nimport sys\n'
                'ROOT = Path(__file__).resolve().parent\n'
                'if not (ROOT / "wayricad_runtime").is_dir():\n'
                '    sys.path.insert(0, str(ROOT.parent))\n'
                'from wayricad_runtime.launcher import main\n'
                'if __name__ == "__main__":\n    main(ROOT)\n', encoding="utf-8")
        requirements = ["kicad-python>=0.8.0,<0.9", "wxPython>=4.2.3,<5"]
        # Extractor graph backends and several engineering tools use NetworkX.
        if any("import networkx" in p.read_text(encoding="utf-8-sig", errors="replace") for p in folder.rglob("*.py")):
            requirements.append("networkx>=2.8,<4")
        # Keep additional dependencies declared by the imported application.
        req_path = folder / "requirements.txt"
        if req_path.exists():
            for line in req_path.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#") and not any(line.lower().startswith(p) for p in ("kicad-python", "wxpython", "networkx", "pywebview")):
                    requirements.append(line)
        req_path.write_text("\n".join(dict.fromkeys(requirements)) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
