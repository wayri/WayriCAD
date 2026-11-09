import math
import json
import io
import importlib.util
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from quick_emerge_plugin.model import validate_config
from quick_emerge_plugin.research_antennas import (
    axial_ratio_db,
    get_template,
    list_templates,
    polarization_handedness,
    rectangular_array_phases,
    example_config,
)
from quick_emerge_plugin.research_studies import solve_rectangular_array_factor
from quick_emerge_plugin.research_validation import compare_with_publication


class ResearchAntennaTests(unittest.TestCase):
    def test_registry_contains_published_satellite_s_and_x_case(self):
        item = get_template("kabir-2023-cubesat-sx-shared-aperture")
        self.assertEqual(item["geometry"]["board_mm"], [60.0, 60.0])
        self.assertEqual(item["geometry"]["s_feed_xy_mm"], [5.7, 0.0])
        self.assertEqual(item["geometry"]["x_feed_xy_mm"], [12.3, -10.4])
        self.assertEqual(item["published_targets"]["x_band_ar_ghz"], [8.433, 8.5])
        self.assertIn("10.3390/electronics12214439", item["citation"]["doi"])

    def test_category_wildcards_filter_without_leaking_registry_state(self):
        rows = list_templates("*band")
        self.assertTrue(any(row["id"] == "liu-2020-cubesat-yagi" for row in rows))
        rows[0]["geometry"]["kind"] = "changed"
        self.assertNotEqual(get_template(rows[0]["id"])["geometry"]["kind"], "changed")

    def test_published_yagi_substrate_thickness_is_preserved(self):
        item = get_template("liu-2020-cubesat-yagi")
        self.assertEqual(item["geometry"]["substrate_height_mm"], 0.6)

    def test_solver_only_and_datasheet_values_are_labeled(self):
        patch = get_template("rezaeipour-2021-dual-feed-patch")
        shared = get_template("kabir-2023-cubesat-sx-shared-aperture")
        self.assertIn("solver enclosure", patch["geometry"]["board_extent_provenance"])
        self.assertIn("Nominal Rogers", shared["geometry"]["material_permittivity_provenance"])

    @unittest.skipUnless(importlib.util.find_spec("emerge"), "Actual EMerge 3 solver runtime required")
    def test_full_wave_research_geometries_commit_in_real_emerge(self):
        import emerge as em

        from quick_emerge_plugin.research_geometry import build_research_geometry

        template_ids = (
            "rezaeipour-2021-dual-feed-patch",
            "yang-2016-wlan-monopole",
            "liu-2020-cubesat-yagi",
            "kabir-2023-cubesat-sx-shared-aperture",
        )
        for template_id in template_ids:
            with self.subTest(template=template_id):
                model, _air, ports, _widths, _height, _bounds = build_research_geometry(
                    em, np, example_config(template_id)
                )
                self.assertGreater(len(model._quick_conductors), 0)
                self.assertGreater(len(ports), 0)
                if template_id == "rezaeipour-2021-dual-feed-patch":
                    self.assertAlmostEqual(model._quick_excitation_weights[0], 2 ** -0.5)
                    self.assertAlmostEqual(model._quick_excitation_weights[1], 2 ** -0.5)

    def test_verho_scan_law_uses_paper_pitch(self):
        broadside = rectangular_array_phases("verho-2023-aesa-4x4", 0)
        self.assertAlmostEqual(broadside["phase_x_deg"], 0.0)
        self.assertAlmostEqual(broadside["phase_y_deg"], 0.0)
        scan = rectangular_array_phases("verho-2023-aesa-4x4", 30)
        expected = -360.0 * 0.04 * math.sin(math.radians(30)) / (299792458.0 / 3e9)
        self.assertAlmostEqual(scan["phase_x_deg"], expected)
        self.assertAlmostEqual(scan["phase_y_deg"], 0.0)
        self.assertEqual(len(scan["weights_ri"]), 16)

    def test_axial_ratio_distinguishes_linear_and_circular_fields(self):
        self.assertTrue(math.isinf(axial_ratio_db(1, 0)))
        self.assertAlmostEqual(axial_ratio_db(1, 1j), 0.0, places=12)
        self.assertEqual(polarization_handedness(1, 0), "linear-or-degenerate")
        self.assertNotEqual(polarization_handedness(1, 1j), polarization_handedness(1, -1j))

    def test_rejects_non_array_scan_requests(self):
        with self.assertRaisesRegex(ValueError, "rectangular array"):
            rectangular_array_phases("yang-2016-wlan-monopole", 10)
        with self.assertRaisesRegex(ValueError, "theta"):
            rectangular_array_phases("verho-2023-aesa-4x4", 90)

    def test_research_config_restricts_template_excitation_pairs(self):
        raw = example_config("kabir-2023-cubesat-sx-shared-aperture")
        raw["advanced"]["research_excitation"] = "x-band"
        config = validate_config(raw)
        self.assertEqual(config["advanced"]["research_excitation"], "x-band")
        with self.assertRaisesRegex(ValueError, "compatible excitation"):
            validate_config({"advanced": {
                "study": "research_antenna",
                "research_template": "yang-2016-wlan-monopole",
                "research_excitation": "rhcp",
            }})

    def test_dual_feed_auto_uses_the_published_equal_phase_linear_state(self):
        config = example_config("rezaeipour-2021-dual-feed-patch")
        self.assertEqual(config["advanced"]["research_excitation"], "auto")
        with self.assertRaisesRegex(ValueError, "Invalid advanced research_excitation"):
            validate_config({"advanced": {
                "study": "research_antenna",
                "research_template": "rezaeipour-2021-dual-feed-patch",
                "research_excitation": "linear-x",
            }})

    def test_array_factor_peak_tracks_requested_scan(self):
        config = validate_config({"points": 21, "advanced": {
            "study": "research_antenna",
            "research_template": "verho-2023-aesa-4x4",
            "scan_theta_deg": 35,
        }})
        result = solve_rectangular_array_factor(np, config, {"backend": "test"})
        self.assertLess(abs(result["array_factor"]["scan_error_deg"]), 0.26)
        self.assertIn("No mutual coupling", result["assumptions"][2])
        self.assertEqual(result["port_count"], 0)
        self.assertEqual(result["array_factor"]["element_count"], 16)
        self.assertEqual(result["publication_comparison"]["overall"], "pass")
        self.assertEqual(len(result["research_sha256"]), 64)

    def test_array_factor_validates_renders_and_builds_a_report(self):
        from matplotlib.figure import Figure

        from quick_emerge_plugin import plots
        from quick_emerge_plugin.model import source_identity
        from quick_emerge_plugin.reporting import build_html_report, validate_report_result

        config = example_config("verho-2023-aesa-4x4")
        result = solve_rectangular_array_factor(np, config, {"backend": "test", "version": 1})
        with tempfile.TemporaryDirectory() as directory:
            board = Path(directory) / "board.kicad_pcb"
            board.write_text("(kicad_pcb)", encoding="utf-8")
            result["source"] = source_identity(board)
            self.assertIsNone(validate_report_result(result))
            document = build_html_report(result, include_figures=False)
        self.assertIn("Ideal array-factor result", document)
        figure = Figure()
        plots.array_factor(figure, result)
        self.assertEqual(len(figure.axes[0].lines), 3)

    def test_full_wave_report_uses_recorded_research_geometry_not_generic_patch_defaults(self):
        from quick_emerge_plugin.model import config_digest, source_identity
        from quick_emerge_plugin.report_settings import active_settings
        from quick_emerge_plugin.reporting import validate_report_result
        from quick_emerge_plugin.research_antennas import template_digest

        config = example_config("yang-2016-wlan-monopole")
        research = get_template("yang-2016-wlan-monopole")
        frequencies = [config["f_start_hz"], config["f_stop_hz"]]
        with tempfile.TemporaryDirectory() as directory:
            board = Path(directory) / "board.kicad_pcb"
            board.write_text("(kicad_pcb)", encoding="utf-8")
            result = {
                "schema": 1, "config": config, "config_sha256": config_digest(config),
                "source": source_identity(board), "backend": {"backend": "test", "version": 1},
                "model_scope": "published-research-antenna-template", "port_count": 1,
                "frequencies_hz": frequencies, "s_parameters": {"S11": [[0.5, 0.0], [0.4, 0.0]]},
                "research": research, "research_sha256": template_digest(research),
                "assumptions": [research["model_scope"]],
            }
            self.assertIsNotNone(validate_report_result(result))
        labels = [label for _group, label, _value in active_settings(result)]
        self.assertIn("board mm", labels)
        self.assertNotIn("Patch width [mm]", labels)

    def test_array_factor_solve_does_not_require_emerge_or_emit_touchstone_ports(self):
        from quick_emerge_plugin import backend
        config = validate_config({"points": 21, "advanced": {
            "study": "research_antenna",
            "research_template": "verho-2023-aesa-4x4",
            "scan_theta_deg": 20,
        }})
        with mock.patch.object(backend, "runtime_info", side_effect=AssertionError("must not load EMerge")):
            result = backend.solve(config, progress=lambda *args, **kwargs: None)
        self.assertEqual(result["port_count"], 0)
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(backend.write_touchstone(directory, result))
            self.assertFalse(any(Path(directory).iterdir()))

    def test_example_configs_are_validated_and_cli_writes_portable_setup(self):
        config = example_config("kabir-2023-cubesat-sx-shared-aperture")
        self.assertEqual(config["advanced"]["study"], "research_antenna")
        self.assertEqual(config["field_z_mm"], 24.0)
        from quick_emerge_plugin.__main__ import main
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "sx.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--write-research-setup", "kabir-2023-cubesat-sx-shared-aperture", str(destination)]), 0)
            record = json.loads(destination.read_text(encoding="utf-8"))
            self.assertNotIn("source", record)
            self.assertEqual(record["config"]["advanced"]["research_template"],
                             "kabir-2023-cubesat-sx-shared-aperture")

    def test_committed_setups_match_generated_configs(self):
        root = Path(__file__).resolve().parents[2] / "examples" / "quick_emerge" / "research_antennas"
        files = {
            "rezaeipour-2021-dual-feed-patch": "rezaeipour-2021-dual-feed-patch.json",
            "yang-2016-wlan-monopole": "yang-2016-wlan-monopole.json",
            "liu-2020-cubesat-yagi": "liu-2020-cubesat-yagi.json",
            "verho-2023-aesa-4x4": "verho-2023-aesa-4x4.json",
            "kabir-2023-cubesat-sx-shared-aperture": "kabir-2023-cubesat-sx.json",
        }
        for template, filename in files.items():
            with self.subTest(template=template):
                record = json.loads((root / filename).read_text(encoding="utf-8"))
                self.assertEqual(record["config"], example_config(template))

    def test_sx_stack_requires_air_and_sampling_clearance(self):
        config = example_config("kabir-2023-cubesat-sx-shared-aperture")
        config["air_margin_mm"] = 19.0
        config["field_z_mm"] = 18.0
        with self.assertRaisesRegex(ValueError, "elevated PRS stack"):
            validate_config(config)

    def test_axial_ratio_comparison_requires_frequency_inside_published_band(self):
        config = example_config("kabir-2023-cubesat-sx-shared-aperture")
        config["advanced"]["research_excitation"] = "s-band"
        result = {
            "research": get_template("kabir-2023-cubesat-sx-shared-aperture"),
            "config": config,
            "frequencies_hz": [2.02e9],
            "s_parameters": {"S11": [[0.1, 0.0]], "S22": [[0.1, 0.0]]},
            "radiation": {"frequency_hz": 8.46e9,
                          "boresight_polarization": {"axial_ratio_db": 1.0}},
        }
        comparison = compare_with_publication(result)
        self.assertEqual(comparison["checks"][1]["status"], "insufficient")
        self.assertIn("outside", comparison["checks"][1]["detail"])

    def test_publication_comparison_reports_failure_and_insufficient_sampling(self):
        template = get_template("yang-2016-wlan-monopole")
        result = {"research": template, "frequencies_hz": [2.45e9],
                  "s_parameters": {"S11": [[0.5, 0.0]]}}
        comparison = compare_with_publication(result)
        self.assertEqual(comparison["overall"], "fail")
        self.assertEqual(comparison["checks"][0]["status"], "fail")
        self.assertEqual(comparison["checks"][1]["status"], "insufficient")

    def test_native_preview_uses_research_geometry_not_generic_patch(self):
        from quick_emerge_plugin.scene_data import preview_geometry, research_scene
        config = example_config("kabir-2023-cubesat-sx-shared-aperture")
        descriptor = preview_geometry(config)
        self.assertEqual(descriptor["kind"], "kabir_sx_shared_aperture")
        parts, ports = research_scene(descriptor)
        self.assertGreaterEqual(len(parts), 5)
        self.assertEqual(len(ports), 2)
        self.assertEqual(ports[0][0][:2], (0.0, -5.7))
        self.assertEqual(ports[1][0][:2], (-10.4, -12.3))
        s_patch = next(shape for category, shape, z, color, opacity in parts
                       if category == "copper" and z == descriptor["upper_layer_height_mm"])
        self.assertEqual(len(s_patch["holes_mm"]), 4)


if __name__ == "__main__":
    unittest.main()
