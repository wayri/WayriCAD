"""Validate built artifacts against the checked-in official KiCad schemas."""
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


def validate():
    schemas = ROOT / "tools" / "schemas"
    pcm = json.loads((schemas / "pcm-v2.json").read_text())
    ipc = json.loads((schemas / "ipc-v1.json").read_text())
    feed = json.loads((ROOT / "pcm/pkgs.json").read_text())
    repo = json.loads((ROOT / "pcm/repo.json").read_text())
    Draft7Validator(dict(pcm, **{"$ref": "#/definitions/PackageArray"})).validate(feed)
    Draft7Validator(dict(pcm, **{"$ref": "#/definitions/Repository"})).validate(repo)
    assert len(feed["packages"]) == 19
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
    print("Validated 19 independent PCM ZIPs: official schemas, payload syntax, icons, entrypoints and SHA-256 hashes.")


if __name__ == "__main__":
    validate()
