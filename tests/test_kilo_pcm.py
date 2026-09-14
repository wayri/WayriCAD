from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "kilo_plugin"


def test_kilo_pcm_metadata_and_feed_are_consistent() -> None:
    metadata = json.loads((ROOT / "embed_3d_plugin" / "metadata.json").read_text(encoding="utf-8"))
    packages = json.loads((ROOT / "pcm" / "pkgs.json").read_text(encoding="utf-8"))
    feed_entry = next(
        package
        for package in packages["packages"]
        if package["identifier"] == "com.github.wayri.wayricad.embed-3d"
    )

    assert metadata["name"] == "WayriCAD Project Library"
    assert not (PLUGIN / 'metadata.json').exists()
    assert (PLUGIN / 'metadata.legacy.json').exists()
    assert not any(p['identifier'] in ('com.github.wayri.wayricad.kilo','com.github.wayri.wayricad.portable-assets') for p in packages['packages'])
    assert metadata["identifier"] == feed_entry["identifier"]
    assert metadata["versions"][0]["version"] == feed_entry["versions"][0]["version"]
    assert metadata["versions"][0]["kicad_version"] == "10.0"
    download_url = feed_entry["versions"][0]["download_url"]
    assert download_url.endswith("/WayriCAD-embed-3d-3.1.0-PCM.zip")
    repo = json.loads((ROOT / "pcm" / "repo.json").read_text(encoding="utf-8"))
    release_tag = repo["resources"]["url"].rsplit("/", 2)[-2]
    assert f"/{release_tag}/" in download_url


def test_kilo_pcm_payload_includes_native_help_icon_and_guarded_wrapper() -> None:
    wrapper = (PLUGIN / "__init__.py").read_text(encoding="utf-8")

    assert "wx.GetApp() is not None" in wrapper
    assert "from kilo.plugin.action_plugin import register" in wrapper
    assert (PLUGIN / "ReadMe.md").is_file()
    assert (PLUGIN / "icon.png").is_file()
    assert (PLUGIN / "LICENSE").is_file()
    assert (PLUGIN / "kilo" / "README.md").is_file()
    assert (PLUGIN / "kilo" / "icon.png").is_file()
    assert (PLUGIN / "help.html").is_file()
    assert (PLUGIN / "help-workflow.png").is_file()
