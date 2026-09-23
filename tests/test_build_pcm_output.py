"""Disposable PCM builds must leave the published feed and release assets alone."""
import json
import sys
import zipfile

import build_pcm


def test_output_dir_builds_zip_without_touching_feed(tmp_path, monkeypatch):
    plugin = tmp_path / "sample_plugin"
    plugin.mkdir()
    identifier = "com.github.wayri.wayricad.sample"
    (plugin / "metadata.json").write_text(json.dumps({
        "name": "Sample", "description": "Sample package",
        "description_full": "Sample package for local build validation",
        "identifier": identifier, "type": "plugin", "license": "GPL-3.0-only",
        "author": {"name": "WayriCAD contributors", "contact": {}},
        "versions": [{"version": "3.3.0", "status": "testing",
                      "kicad_version": "10.0", "runtime": "ipc"}],
    }), encoding="utf-8")
    (plugin / "plugin.json").write_text(json.dumps({"identifier": identifier}), encoding="utf-8")
    (plugin / "__init__.py").write_text("", encoding="utf-8")
    output = tmp_path / "candidate"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["build_pcm.py", "--output-dir", str(output)])
    build_pcm.main()

    assert not (tmp_path / "pcm").exists()
    assert not (tmp_path / "releases").exists()
    with zipfile.ZipFile(output / "WayriCAD-sample-3.3.0-PCM.zip") as archive:
        assert archive.testzip() is None
        assert json.loads(archive.read("metadata.json"))["identifier"] == identifier
        assert "plugins/wayricad_runtime/runtime_setup.py" in archive.namelist()
        assert "plugins/__init__.py" in archive.namelist()
        assert "wayricad_runtime.legacy_menu import register" in archive.read("plugins/__init__.py").decode()
        assert "plugins/wayricad_runtime/legacy_menu.py" in archive.namelist()
