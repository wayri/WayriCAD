from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
GUIDED_PACKAGES = (
    "bulk_label_editor_plugin",
    "extract_pins_plugin",
    "fanout_generator_plugin",
    "test_point_descriptor_plugin",
    "trace_impedance_plugin",
    "via_stitching_plugin",
)


class SuiteUxTests(unittest.TestCase):
    def test_every_plugin_embeds_an_annotated_help_visual(self) -> None:
        for package in GUIDED_PACKAGES:
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
            for package in GUIDED_PACKAGES
        }
        self.assertEqual(1, len(hashes))

    def test_dependency_manager_has_visual_help_and_guarded_install_actions(self) -> None:
        help_text = (ROOT / "extract_pins_plugin" / "help.html").read_text(encoding="utf-8")
        self.assertIn('src="help-dependencies.png"', help_text)
        with Image.open(ROOT / "extract_pins_plugin" / "help-dependencies.png") as image:
            self.assertEqual((1200, 680), image.size)
            self.assertEqual("PNG", image.format)
        dialog = (ROOT / "extract_pins_plugin" / "dependency_dialog.py").read_text(encoding="utf-8")
        self.assertIn("Confirm Dependency Installation", dialog)
        self.assertIn("Install Recommended", dialog)
        self.assertIn("Restart PCB Editor", dialog)

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
                self.assertIn("PCB_GROUP", source)
                self.assertIn("_persistent_groups", source)

                preview_body = source.split("    def preview(", 1)[1].split("    def show_on_pcb(", 1)[0]
                self.assertNotIn("self.board.Add(", preview_body)
                pcb_preview_body = source.split("    def show_on_pcb(", 1)[1].split("    def clear_pcb_preview(", 1)[0]
                self.assertIn("self.board.Add(", pcb_preview_body)

        fanout = (ROOT / "fanout_generator_plugin" / "fanout_generator_plugin.py").read_text(encoding="utf-8")
        for capability in (
            "Selected pads", "Selected footprints", "Reference wildcard", "Auto-refresh from PCB selection",
            "Dogbone outward", "Dogbone inward", "BGA/LGA grid outward", "Quadrant outward",
            "Quadrant inward", "Four-corner outward", "Four-corner inward", "Via-in-pad",
            "on_preview_row_activated", "KiWay Fanout Commit",
        ):
            self.assertIn(capability, fanout)

        stitching = (ROOT / "via_stitching_plugin" / "via_stitching_plugin.py").read_text(encoding="utf-8")
        for capability in (
            "Only inside target-net copper zone", "Auto-refresh from PCB selection",
            "outside target copper", "other-net zone", "HitTestFilledArea",
            "on_preview_row_activated", "KiWay Via Stitch Commit",
        ):
            self.assertIn(capability, stitching)
        self.assertNotIn("self.board.GetSelection()", stitching)

    def test_kicad10_selection_adapter_and_analysis_crosslinks(self) -> None:
        for package in GUIDED_PACKAGES:
            source = (ROOT / package / "selection_utils.py").read_text(encoding="utf-8")
            self.assertIn("ClearSelected", source)
            self.assertIn("setter()", source)
            self.assertNotIn("setter(id(item) in target_ids)", source)

        tp = (ROOT / "test_point_descriptor_plugin" / "test_point_descriptor_plugin.py").read_text(encoding="utf-8")
        for field in ("Connected IC", "IC Pin", "IC Pin Function", "Terminal Net", "Intermediate Components", "Trace Path"):
            self.assertIn(field, tp)
        self.assertIn("resolve_connected_ics", tp)

        rlc = (ROOT / "trace_impedance_plugin" / "trace_impedance_plugin.py").read_text(encoding="utf-8")
        for capability in ("Auto-refresh from PCB selection", "Reference Layer Used", "SetMinSize", "on_selection_timer"):
            target = rlc + (ROOT / "trace_impedance_plugin" / "measurement.py").read_text(encoding="utf-8")
            self.assertIn(capability, target)

    def test_pcb_interactive_plugins_are_modeless(self) -> None:
        cases = (
            ("bulk_label_editor_plugin", "bulk_label_editor_plugin.py", "bulk_label_editor_plugin.py", "BulkLabelEditorFrame"),
            ("fanout_generator_plugin", "fanout_generator_plugin.py", "fanout_generator_plugin.py", "FanoutFrame"),
            ("via_stitching_plugin", "via_stitching_plugin.py", "via_stitching_plugin.py", "ViaFrame"),
            ("extract_pins_plugin", "extract_pins_plugin.py", "plugin_dialog_v2.py", "PluginDialogV2"),
        )
        for package, launcher_module, frame_module, dialog_name in cases:
            with self.subTest(package=package):
                launcher = (ROOT / package / launcher_module).read_text(encoding="utf-8")
                frame = (ROOT / package / frame_module).read_text(encoding="utf-8")
                self.assertIn(f"class {dialog_name}(wx.Frame)", frame)
                self.assertNotIn("ShowModal()", launcher)

    def test_pin_extractor_preserves_selection_filters_and_visual_preview(self) -> None:
        source = (ROOT / "extract_pins_plugin" / "plugin_dialog_v2.py").read_text(encoding="utf-8")
        for label in (
            "PCB selection",
            "Wildcard filters",
            "Selection + filters",
            "Follow PCB selection",
            "Preview Extraction",
            "Endpoint Trace",
            "Net / label wildcards",
            "Resolve endpoint refs",
            "Trace through refs",
            "Preview Endpoint Map",
            "Components In Between",
            "Export Preview...",
            "System map",
            "Signal flow",
            "Power flow",
            "Refresh Visual Preview",
            "Export This SVG...",
            "Highlight Net",
            "Select Copper",
            "Consolidate repeated routes",
            "IC Pin Connections and Flow Chart",
            "Power Tree & Net Rules",
            "Force-signal patterns",
            "Build Power Tree",
            "Export Tree SVG...",
            "Zoom in",
            "Fit diagram",
            "kiway://net/",
        ):
            self.assertIn(label, source)
        self.assertIn("wxhtml2.WebView.New", source)
        self.assertIn("fp.SetSelected()", source)
        self.assertIn("SetHighLightNet", source)
        self.assertIn("summarize_source_destination_table", source)
        self.assertIn("PowerTreeAnalyzer", source)
        self.assertIn("trace_matching_nets", source)

        help_text = (ROOT / "extract_pins_plugin" / "help.html").read_text(encoding="utf-8")
        self.assertIn('src="help-diagrams.png"', help_text)
        for anchor in ("#pins", "#endpoint-trace", "#net-rules", "#signal-flow", "#ic-chart", "#power-tree", "#troubleshooting"):
            self.assertIn(f'href="{anchor}"', help_text)
        help_launcher = (ROOT / "extract_pins_plugin" / "help_utils.py").read_text(encoding="utf-8")
        self.assertIn("path.as_uri()", help_launcher)
        self.assertIn("wxhtml2.WebView.New", help_launcher)
        with Image.open(ROOT / "extract_pins_plugin" / "help-diagrams.png") as image:
            self.assertEqual((1200, 680), image.size)

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
