from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    "bulk_label_editor_plugin",
    "connector_icd_plugin",
    "extract_pins_plugin",
    "fanout_generator_plugin",
    "net_hygiene_plugin",
    "test_coverage_plugin",
    "test_point_descriptor_plugin",
    "trace_impedance_plugin",
    "via_stitching_plugin",
)


class SuiteUxTests(unittest.TestCase):
    def test_every_plugin_embeds_an_annotated_help_visual(self) -> None:
        for package in PACKAGES:
            with self.subTest(package=package):
                help_text = (ROOT / package / "help.html").read_text(encoding="utf-8")
                self.assertIn('src="help-workflow.png"', help_text)
                self.assertIn("Annotated interface walkthrough", help_text)
                with Image.open(ROOT / package / "help-workflow.png") as image:
                    self.assertEqual((1200, 680), image.size)
                    self.assertEqual("PNG", image.format)

    def test_guided_workflow_component_is_identical_in_standalone_packages(self) -> None:
        hashes = {
            hashlib.sha256((ROOT / package / "guided_ui.py").read_bytes()).hexdigest()
            for package in PACKAGES
        }
        self.assertEqual(1, len(hashes))

    def test_geometry_tools_enforce_preview_before_commit(self) -> None:
        for package, module in (
            ("fanout_generator_plugin", "fanout_generator_plugin.py"),
            ("via_stitching_plugin", "via_stitching_plugin.py"),
        ):
            with self.subTest(package=package):
                source = (ROOT / package / module).read_text(encoding="utf-8")
                self.assertIn("Create and inspect a preview before committing.", source)
                self.assertIn("self.preview_plan", source)
                self.assertIn("self.preview_items = []", source)
                self.assertIn("self.Bind(wx.EVT_CLOSE, self.on_close)", source)
                self.assertIn("GeometryPreview", source)
                self.assertIn("Preview in Window", source)
                self.assertIn("Show on PCB", source)
                self.assertIn("Commit to PCB", source)
                self.assertIn("Undo Last Commit", source)
                self.assertIn("Redo Last Commit", source)

                preview_body = source.split("    def preview(", 1)[1].split("    def show_on_pcb(", 1)[0]
                self.assertNotIn("self.board.Add(", preview_body)
                pcb_preview_body = source.split("    def show_on_pcb(", 1)[1].split("    def clear_pcb_preview(", 1)[0]
                self.assertIn("self.board.Add(", pcb_preview_body)

    def test_board_mutating_plugins_remain_inside_action_plugin_run(self) -> None:
        cases = (
            ("bulk_label_editor_plugin", "bulk_label_editor_plugin.py", "BulkLabelEditorFrame"),
            ("fanout_generator_plugin", "fanout_generator_plugin.py", "FanoutFrame"),
            ("via_stitching_plugin", "via_stitching_plugin.py", "ViaFrame"),
            ("extract_pins_plugin", "plugin_ui.py", "PluginUI"),
        )
        for package, module, dialog_name in cases:
            with self.subTest(package=package):
                source = (ROOT / package / module).read_text(encoding="utf-8")
                self.assertIn(f"class {dialog_name}(wx.Dialog)", source)
                if module != "plugin_ui.py":
                    self.assertIn("dialog.ShowModal()", source)

    def test_bulk_operation_history_is_visible(self) -> None:
        bulk = (ROOT / "bulk_label_editor_plugin" / "bulk_label_editor_plugin.py").read_text(encoding="utf-8")
        self.assertIn("Undo Last Apply", bulk)
        self.assertIn("Redo Last Apply", bulk)
        extractor = (ROOT / "extract_pins_plugin" / "plugin_ui.py").read_text(encoding="utf-8")
        self.assertIn("Show Group on PCB", extractor)
        self.assertIn("PCB preview required", extractor)
        self.assertIn("Undo Group", extractor)
        self.assertIn("Redo Group", extractor)


if __name__ == "__main__":
    unittest.main()
