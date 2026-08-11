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
IPC_PACKAGES = (
    ("portable_assets_plugin", "kiway-portable-assets", "0.2.0"),
    ("variant_workbench_plugin", "kiway-variant-workbench", "0.5.0"),
)


class IpcPluginTests(unittest.TestCase):
    def test_pcm_and_ipc_manifests_match(self) -> None:
        for folder, identifier, version in IPC_PACKAGES:
            with self.subTest(folder=folder):
                package = ROOT / folder
                metadata = json.loads((package / "metadata.json").read_text(encoding="utf-8"))
                manifest = json.loads((package / "plugin.json").read_text(encoding="utf-8"))
                self.assertEqual(identifier, metadata["identifier"])
                self.assertEqual(identifier, manifest["identifier"])
                self.assertEqual(version, metadata["versions"][0]["version"])
                self.assertEqual("ipc", metadata["versions"][0]["runtime"])
                self.assertEqual("python", manifest["runtime"]["type"])
                self.assertTrue((package / "help.html").is_file())
                with Image.open(package / "help-workflow.png") as image:
                    self.assertEqual((1200, 680), image.size)

                action = manifest["actions"][0]
                for theme in ("icons-light", "icons-dark"):
                    sizes = []
                    for icon_name in action[theme]:
                        with Image.open(package / icon_name) as icon:
                            sizes.append(icon.size)
                    self.assertEqual([(32, 32), (64, 64)], sizes)

    def test_portable_assets_defaults_to_offline_and_hashes_inputs(self) -> None:
        self.assertFalse(PortableOptions().allow_network)
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            (root / "demo.kicad_pro").write_text("{}", encoding="utf-8")
            board = root / "demo.kicad_pcb"
            board.write_text("(kicad_pcb)", encoding="utf-8")
            context = ProjectContext.discover(root)
            before = project_signature(context)
            board.write_text("(kicad_pcb (version 1))", encoding="utf-8")
            self.assertNotEqual(before, project_signature(context))

    def test_variant_workbench_refuses_active_project_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
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
