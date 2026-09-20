from __future__ import annotations

import json
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]



class WorkbenchPluginTests(unittest.TestCase):
    def test_plugin_registry_matches_active_metadata_directories(self) -> None:
        from build_pcm import discover_plugins
        from extract_pins_plugin.dependency_manager import SUITE_PACKAGES

        directories = {path.name for path in ROOT.glob("*_plugin") if path.is_dir()}
        active = {path.name for path in discover_plugins(ROOT)}
        registered = {folder for folder, _label in SUITE_PACKAGES}

        self.assertSetEqual(active, directories)
        self.assertSetEqual(registered, active)

    def test_active_pcm_packages_have_visible_ipc_actions(self) -> None:
        from build_pcm import discover_plugins
        packages = discover_plugins(ROOT)
        self.assertEqual(16, len(packages))
        for package in packages:
            with self.subTest(folder=package.name):
                metadata = json.loads((package / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual("3.3.0", metadata["versions"][0]["version"])
                self.assertEqual("ipc", metadata["versions"][0]["runtime"])
                manifest = json.loads((package / "plugin.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["identifier"], manifest["identifier"])
                self.assertEqual("python", manifest["runtime"]["type"])
                self.assertTrue(manifest["actions"])
                self.assertTrue(any(action.get("show-button") for action in manifest["actions"]))
                for action in manifest["actions"]:
                    self.assertTrue((package / action["entrypoint"]).is_file())
                    self.assertIn("pcb", action["scopes"])
                self.assertTrue((package / "help.html").is_file())
                with Image.open(package / "icon.png") as icon:
                    self.assertGreaterEqual(icon.width, 32)
                    self.assertGreaterEqual(icon.height, 32)

    def test_pcm_feed_uses_only_kicad_supported_runtime_values(self) -> None:
        feed = json.loads((ROOT / "pcm" / "pkgs.json").read_text(encoding="utf-8"))
        invalid = [
            (package["identifier"], version["version"], version.get("runtime"))
            for package in feed["packages"]
            for version in package["versions"]
            if version.get("runtime") not in {"swig", "ipc"}
        ]
        self.assertEqual([], invalid)

if __name__ == "__main__":
    unittest.main()
