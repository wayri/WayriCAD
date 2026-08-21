from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from portable_assets_plugin.portable_assets.core.engine import (
    PortableOptions,
    ProjectContext,
    Transaction,
    project_signature,
)
from variant_workbench_plugin.kicad_variant_manager import (
    PlannedFile,
    PromotionPlan,
    VariantPromoterError,
    apply_plan,
    project_lock_files,
)


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_PACKAGES = (
    ("portable_assets_plugin", "kiway-portable-assets", "0.2.4"),
    ("variant_workbench_plugin", "kiway-variant-workbench", "0.5.3"),
)


class WorkbenchPluginTests(unittest.TestCase):
    def test_pcm_packages_have_visible_action_plugin_launchers(self) -> None:
        for folder, identifier, version in WORKBENCH_PACKAGES:
            with self.subTest(folder=folder):
                package = ROOT / folder
                metadata = json.loads((package / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(identifier, metadata["identifier"])
                self.assertEqual(version, metadata["versions"][0]["version"])
                self.assertEqual("swig", metadata["versions"][0]["runtime"])
                self.assertTrue((package / "__init__.py").is_file())
                launcher = (package / "legacy_action_plugin.py").read_text(encoding="utf-8")
                self.assertIn("pcbnew.ActionPlugin", launcher)
                self.assertIn("show_toolbar_button = True", launcher)
                self.assertNotIn("KICAD_API_SOCKET", launcher)
                self.assertTrue((package / "help.html").is_file())
                with Image.open(package / "help-workflow.png") as image:
                    self.assertEqual((1200, 680), image.size)

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

    def test_portable_assets_defaults_to_offline_and_hashes_inputs(self) -> None:
        self.assertFalse(PortableOptions().allow_network)
        requirements = (ROOT / "portable_assets_plugin" / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("wxPython", requirements)
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            (root / "demo.kicad_pro").write_text("{}", encoding="utf-8")
            board = root / "demo.kicad_pcb"
            board.write_text("(kicad_pcb)", encoding="utf-8")
            context = ProjectContext.discover(root)
            before = project_signature(context)
            board.write_text("(kicad_pcb (version 1))", encoding="utf-8")
            self.assertNotEqual(before, project_signature(context))

    def test_portable_assets_creates_conventional_and_transaction_backups(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            (root / "demo.kicad_pro").write_text("{}", encoding="utf-8")
            board = root / "demo.kicad_pcb"
            board.write_text("(kicad_pcb)", encoding="utf-8")
            context = ProjectContext.discover(root)
            transaction = Transaction(context)
            transaction.commit({board: b"(kicad_pcb (version 1))"})
            self.assertTrue((transaction.backup_dir / "demo.kicad_pcb").is_file())
            archives = list((root / "demo-backups").glob("demo-*.zip"))
            self.assertEqual(1, len(archives))

    def test_variant_launcher_requires_a_tk_capable_gui_interpreter(self) -> None:
        source = (ROOT / "variant_workbench_plugin" / "variant_manager_plugin.py").read_text(encoding="utf-8")
        self.assertIn("KIWAY_VARIANT_PYTHON", source)
        self.assertIn("import tkinter", source)
        self.assertIn("_tk_python()", source)

    def test_variant_workbench_refuses_active_project_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir).resolve()
            schematic = root / "demo.kicad_sch"
            old_text = "(kicad_sch)"
            schematic.write_text(old_text, encoding="utf-8")
            lock = root / "~demo.kicad_sch.lck"
            lock.write_text("open", encoding="utf-8")
            self.assertEqual([lock], project_lock_files([schematic]))

            planned = PlannedFile(
                path=schematic,
                old_sha256=hashlib.sha256(schematic.read_bytes()).hexdigest(),
                new_text="(kicad_sch (version 1))",
                edits=[],
            )
            plan = PromotionPlan(
                source_root=schematic,
                project_file=None,
                selected_variant="Production",
                keep_source=False,
                schematic_files=[planned],
                project_old_sha256=None,
                project_new_text=None,
                variants_before=["Production"],
                variants_after=[],
                summary=[],
            )
            with self.assertRaisesRegex(VariantPromoterError, "lock files"):
                apply_plan(plan)
            self.assertEqual(old_text, schematic.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
