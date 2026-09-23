"""Validate built artifacts against the checked-in official KiCad schemas."""
import argparse
import ast
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / ".build-tools").is_dir():
    sys.path.insert(0, str(ROOT / ".build-tools"))
from jsonschema import Draft7Validator
from PIL import Image


def validate_candidate_archives(directory):
    """Validate disposable current-source ZIPs before anyone installs them."""
    directory = Path(directory)
    schemas = ROOT / "tools" / "schemas"
    pcm = json.loads((schemas / "pcm-v2.json").read_text())
    ipc = json.loads((schemas / "ipc-v1.json").read_text())
    sources = {}
    for path in ROOT.glob("*_plugin/metadata.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        version = metadata["versions"][0]["version"]
        archive_name = f"WayriCAD-{path.parent.name.removesuffix('_plugin').replace('_', '-')}-{version}-PCM.zip"
        sources[archive_name] = (metadata["identifier"], version)
    archives = sorted(directory.glob("WayriCAD-*-PCM.zip"))
    if not sources or {path.name for path in archives} != set(sources):
        raise ValueError("Candidate ZIPs differ from the active source inventory.")
    for path in archives:
        identifier, version = sources[path.name]
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise ValueError(f"Corrupt archive member {bad} in {path.name}")
            names = archive.namelist()
            if len(names) != len({name.casefold() for name in names}) or any(name.startswith("/") or "\\" in name or ".." in name.split("/")
                                                    for name in names):
                raise ValueError(f"Unsafe or duplicate archive member in {path.name}")
            if any(name != "metadata.json" and not name.startswith(("plugins/", "resources/"))
                   for name in names):
                raise ValueError(f"Unexpected PCM archive path in {path.name}")
            metadata = json.loads(archive.read("metadata.json"))
            manifest = json.loads(archive.read("plugins/plugin.json"))
            Draft7Validator(pcm).validate(metadata)
            Draft7Validator(ipc).validate(manifest)
            if metadata["identifier"] != identifier or manifest["identifier"] != identifier:
                raise ValueError(f"Identifier mismatch in {path.name}")
            if metadata["versions"][0]["version"] != version:
                raise ValueError(f"Version mismatch in {path.name}")
            initializer = ast.parse(archive.read("plugins/__init__.py"), path.name + ":plugins/__init__.py")
            versions = [node.value.value for node in initializer.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == "__version__"
                                for target in node.targets) and isinstance(node.value, ast.Constant)]
            if versions != [version]:
                raise ValueError(f"Generated initializer version missing or inconsistent in {path.name}")
            if ("plugins/wayricad_runtime/launcher.py" not in names or
                    "plugins/wayricad_runtime/legacy_menu.py" not in names or
                    "plugins/requirements.txt" not in names):
                raise ValueError(f"Standalone runtime missing in {path.name}")
            seen_actions = set()
            for action in manifest["actions"]:
                if action["identifier"] in seen_actions:
                    raise ValueError(f"Duplicate action identifier in {path.name}")
                seen_actions.add(action["identifier"])
                if action.get("scopes") != ["pcb"]:
                    raise ValueError(f"KiCad 10 action must be PCB-scoped in {path.name}")
                if "plugins/" + action["entrypoint"] not in names:
                    raise ValueError(f"Missing action entrypoint in {path.name}")
                for theme in ("icons-light", "icons-dark"):
                    icons = action.get(theme, [])
                    if len(icons) != 3:
                        raise ValueError(f"Expected 24/48/96 action icons in {path.name}")
                    for size, icon in zip((24, 48, 96), icons):
                        with Image.open(BytesIO(archive.read("plugins/" + icon))) as image:
                            if image.size != (size, size):
                                raise ValueError(f"Wrong action icon size in {path.name}")
            for name in names:
                if name.endswith(".py"):
                    compile(archive.read(name), path.name + ":" + name, "exec")
    print(f"Validated {len(archives)} disposable PCM ZIPs: official schemas, independent runtime, actions, icons and Python syntax.")


def validate_repository(repo, feed_bytes, schema):
    """Validate the protocol KiCad selects, not just the advertised $schema.

    KiCad 10 FetchRepository defaults schema_version to 1 and uses that
    validator for fetchPackages too. See kicad/pcm/pcm.cpp in KiCad's source.
    """
    if repo.get("schema_version") != 2:
        raise ValueError("PCM repository must declare schema_version: 2; $schema alone does not select v2 in KiCad.")
    Draft7Validator(dict(schema, **{"$ref": "#/definitions/Repository"})).validate(repo)
    digest = repo["packages"].get("sha256")
    if not digest or hashlib.sha256(feed_bytes).hexdigest() != digest:
        raise ValueError("PCM packages SHA-256 missing or mismatched; publish repo.json and pkgs.json together.")
    feed = json.loads(feed_bytes)
    Draft7Validator(dict(schema, **{"$ref": "#/definitions/PackageArray"})).validate(feed)
    if not feed["packages"]:
        raise ValueError("PCM package feed is empty.")
    return feed


def validate():
    schemas = ROOT / "tools" / "schemas"
    pcm = json.loads((schemas / "pcm-v2.json").read_text())
    ipc = json.loads((schemas / "ipc-v1.json").read_text())
    repo = json.loads((ROOT / "pcm/repo.json").read_text())
    feed = validate_repository(repo, (ROOT / "pcm/pkgs.json").read_bytes(), pcm)
    expected = {json.loads(p.read_text(encoding="utf-8"))["identifier"] for p in ROOT.glob("*_plugin/metadata.json")}
    assert expected and {p["identifier"] for p in feed["packages"]} == expected, "Feed differs from source plugin inventory"
    identifiers = set()
    for package in feed["packages"]:
        Draft7Validator(pcm).validate(package)
        identifier = package["identifier"]
        assert identifier not in identifiers
        identifiers.add(identifier)
        for version in package["versions"]:
            path = ROOT / "releases" / version["download_url"].rsplit("/", 1)[1]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == version["download_sha256"], path
            assert path.stat().st_size == version["download_size"], path
            with zipfile.ZipFile(path) as archive:
                assert archive.testzip() is None, path
                names = archive.namelist()
                assert len(set(names)) == len(names), path
                assert all(not n.startswith("/") and ".." not in n.split("/") for n in names), path
                assert all(n == "metadata.json" or n.startswith(("plugins/", "resources/")) for n in names), path
                metadata = json.loads(archive.read("metadata.json"))
                Draft7Validator(pcm).validate(metadata)
                assert metadata["identifier"] == identifier
                assert all(not key.startswith("download_") for v in metadata["versions"] for key in v)
                manifest = json.loads(archive.read("plugins/plugin.json"))
                Draft7Validator(ipc).validate(manifest)
                assert manifest["identifier"] == identifier
                for action in manifest["actions"]:
                    assert "plugins/" + action["entrypoint"] in names
                    for theme in ("icons-light", "icons-dark"):
                        for size, icon in zip((24, 48, 96), action[theme]):
                            with Image.open(BytesIO(archive.read("plugins/" + icon))) as image:
                                assert image.size == (size, size)
                with Image.open(BytesIO(archive.read("resources/icon.png"))) as image:
                    assert image.size == (64, 64)
                assert "plugins/wayricad_runtime/launcher.py" in names
                assert "plugins/LICENSE" in names
                for name in names:
                    if name.endswith(".py"):
                        compile(archive.read(name), str(path) + ":" + name, "exec")
    resources = ROOT / "releases/resources.zip"
    assert hashlib.sha256(resources.read_bytes()).hexdigest() == repo["resources"]["sha256"]
    with zipfile.ZipFile(resources) as archive:
        assert set(archive.namelist()) == {i + "/icon.png" for i in identifiers}
    print(f"Validated {len(identifiers)} independent PCM ZIPs: official schemas, payload syntax, icons, entrypoints and SHA-256 hashes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path,
                        help="Validate current-source disposable PCM ZIPs without using the published feed.")
    args = parser.parse_args()
    if args.archive_dir is None:
        validate()
    else:
        validate_candidate_archives(args.archive_dir)
