from __future__ import annotations

import hashlib
import json
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
ENGINEERING_WORKBENCHES = (
    ("return_path_auditor_plugin", "return_path_auditor_plugin.py"),
    ("harness_workbench_plugin", "harness_workbench_plugin.py"),
    ("manufacturing_readiness_plugin", "manufacturing_readiness_plugin.py"),
    ("pdn_decoupling_plugin", "pdn_decoupling_plugin.py"),
    ("protocol_constraint_composer_plugin", "protocol_constraint_composer_plugin.py"),
)
ACTION_PLUGIN_MODULES = (
    ("bulk_label_editor_plugin", "bulk_label_editor_plugin.py"),
    ("extract_pins_plugin", "extract_pins_plugin.py"),
    ("fanout_generator_plugin", "fanout_generator_plugin.py"),
    ("harness_workbench_plugin", "harness_workbench_plugin.py"),
    ("heater_designer_plugin", "heater_designer_plugin.py"),
    ("kilo_plugin", "kilo/plugin/action_plugin.py"),
    ("manufacturing_readiness_plugin", "manufacturing_readiness_plugin.py"),
    ("pdn_decoupling_plugin", "pdn_decoupling_plugin.py"),
    ("planar_magnetics_plugin", "planar_magnetics_plugin.py"),
    ("portable_assets_plugin", "legacy_action_plugin.py"),
    ("protocol_constraint_composer_plugin", "protocol_constraint_composer_plugin.py"),
    ("return_path_auditor_plugin", "return_path_auditor_plugin.py"),
    ("signal_integrity_advisor_plugin", "signal_integrity_advisor_plugin.py"),
    ("test_point_descriptor_plugin", "test_point_descriptor_plugin.py"),
    ("trace_impedance_plugin", "trace_impedance_plugin.py"),
    ("variant_workbench_plugin", "legacy_action_plugin.py"),
    ("via_stitching_plugin", "via_stitching_plugin.py"),
)


class SuiteUxTests(unittest.TestCase):
    def test_every_pcm_package_has_unique_icon_docs_help_and_actual_capture(self) -> None:
        packages = sorted(
            path for path in ROOT.iterdir()
            if path.is_dir() and (path / "metadata.json").is_file()
        )
        self.assertEqual(22, len(packages))
        icon_hashes = {}
        for package in packages:
            with self.subTest(package=package.name):
                icon = package / "icon.png"
                help_file = package / "help.html"
                screenshot = package / "help-workflow.png"
                readme = next(
                    (candidate for candidate in (package / "ReadMe.md", package / "README.md")
                     if candidate.is_file()),
                    None,
                )
                self.assertIsNotNone(readme)
                self.assertTrue(help_file.is_file())
                self.assertIn('WayriCAD', help_file.read_text(encoding="utf-8"))
                with Image.open(icon) as image:
                    self.assertEqual((64, 64), image.size)
                    self.assertEqual("PNG", image.format)
                for theme in ("", "-dark"):
                    for size in (24, 48, 96):
                        with Image.open(package / "resources" / f"icon{theme}-{size}.png") as image:
                            self.assertEqual((size, size), image.size)
                digest = hashlib.sha256(icon.read_bytes()).hexdigest()
                icon_hashes.setdefault(digest, []).append(package.name)
        self.assertEqual([], [names for names in icon_hashes.values() if len(names) > 1])

    def test_every_plugin_embeds_an_annotated_help_visual(self) -> None:
        for package in GUIDED_PACKAGES:
            with self.subTest(package=package):
                help_text = (ROOT / package / "help.html").read_text(encoding="utf-8")
                self.assertIn('src="help-workflow.png"', help_text)
                self.assertIn("<h1", help_text)
                with Image.open(ROOT / package / "help-workflow.png") as image:
                    self.assertGreaterEqual(image.width, 900)
                    self.assertGreaterEqual(image.height, 500)
                    self.assertEqual("PNG", image.format)

    def test_guided_workflow_component_is_identical_in_standalone_packages(self) -> None:
        hashes = {
            hashlib.sha256((ROOT / package / "guided_ui.py").read_bytes()).hexdigest()
            for package in GUIDED_PACKAGES
        }
        self.assertEqual(1, len(hashes))

    def test_engineering_workbenches_follow_kicad_design_language(self) -> None:
        guide_hashes = set()
        for package, module in ENGINEERING_WORKBENCHES:
            with self.subTest(package=package):
                source = (ROOT / package / module).read_text(encoding="utf-8")
                help_text = (ROOT / package / "help.html").read_text(encoding="utf-8")
                guide = ROOT / package / "guided_ui.py"
                guide_hashes.add(hashlib.sha256(guide.read_bytes()).hexdigest())
                self.assertIn("add_workflow", source)
                self.assertIn("self.guide", source)
                self.assertIn("make_sortable", source)
                self.assertIn('src="help-workflow.png"', help_text)
                with Image.open(ROOT / package / "help-workflow.png") as image:
                    self.assertGreaterEqual(image.width, 900)
                    self.assertGreaterEqual(image.height, 500)
                    self.assertEqual("PNG", image.format)
        self.assertEqual(1, len(guide_hashes))

    def test_every_action_plugin_defines_light_and_dark_icons(self) -> None:
        for package, module in ACTION_PLUGIN_MODULES:
            with self.subTest(package=package):
                source = (ROOT / package / module).read_text(encoding="utf-8")
                self.assertIn("icon_file_name", source)
                self.assertIn("dark_icon_file_name", source)
                with Image.open(ROOT / package / "icon.png") as icon:
                    self.assertEqual("PNG", icon.format)
                    self.assertGreaterEqual(icon.width, 64)
                    self.assertGreaterEqual(icon.height, 64)
                    self.assertIsNotNone(icon.getbbox())
                metadata = json.loads((ROOT / package / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(
                    f"https://raw.githubusercontent.com/wayri/WayriCAD/develop/{package}/icon.png",
                    metadata["resources"]["icon"],
                )
        for icon_path in ROOT.glob("*_plugin/**/icon.png"):
            with self.subTest(icon=str(icon_path.relative_to(ROOT))):
                with Image.open(icon_path) as icon:
                    self.assertEqual((64, 64), icon.size)

    def test_dependency_manager_has_visual_help_and_guarded_install_actions(self) -> None:
        help_text = (ROOT / "extract_pins_plugin" / "help.html").read_text(encoding="utf-8")
        self.assertIn('src="help-dependencies.png"', help_text)
        with Image.open(ROOT / "extract_pins_plugin" / "help-dependencies.png") as image:
            self.assertGreaterEqual(image.width, 900)
            self.assertGreaterEqual(image.height, 500)
            self.assertEqual("PNG", image.format)
        dialog = (ROOT / "extract_pins_plugin" / "dependency_dialog.py").read_text(encoding="utf-8")
        self.assertIn("Confirm Dependency Installation", dialog)
        self.assertIn("Install Recommended", dialog)
        self.assertIn("Restart PCB Editor", dialog)

    def test_geometry_tools_keep_review_nonmutating(self) -> None:
        import ast
        for package, filename in (("fanout_generator_plugin", "fanout_generator_plugin.py"),
                                  ("via_stitching_plugin", "via_stitching_plugin.py")):
            tree = ast.parse((ROOT / package / filename).read_text(encoding="utf-8"))
            for method in ast.walk(tree):
                if isinstance(method, ast.FunctionDef) and method.name in {"preview", "show_on_pcb"}:
                    mutations = [n.func.attr for n in ast.walk(method) if isinstance(n, ast.Call)
                                 and isinstance(n.func, ast.Attribute) and n.func.attr in {"Add", "Remove"}
                                 and ast.unparse(n.func.value) == "self.board"]
                    self.assertEqual([], mutations, f"{package}.{method.name}")

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
        for capability in ("Follow PCB selection", "Reference Layer Used", "SetMinSize", "on_selection_timer", "Board Stackup", "Engineering Notes", "wx.Notebook"):
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
            "wayricad://net/",
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
            self.assertGreaterEqual(image.width, 900)
            self.assertGreaterEqual(image.height, 500)

    def test_bulk_operation_history_is_visible(self) -> None:
        bulk = (ROOT / "bulk_label_editor_plugin" / "bulk_label_editor_plugin.py").read_text(encoding="utf-8")
        self.assertIn('label="Undo"', bulk)
        self.assertIn('label="Redo"', bulk)
        extractor = (ROOT / "extract_pins_plugin" / "plugin_ui.py").read_text(encoding="utf-8")
        self.assertIn("Show Group on PCB", extractor)
        self.assertIn("PCB preview required", extractor)
        self.assertIn("Undo Group", extractor)
        self.assertIn("Redo Group", extractor)


if __name__ == "__main__":
    unittest.main()
