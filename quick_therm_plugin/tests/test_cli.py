"""The independent QuickTherm CLI keeps its own request contract."""

import contextlib
from io import StringIO
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from quick_therm_plugin.cli import main


class QuickThermCLITests(TestCase):
    def test_reviewed_config_pass_gate_propagates_failed_limits(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            config = Path(temporary) / "thermal.json"
            config.write_text(json.dumps({"environment": "air", "field_map": {
                "power_w": "Power_W", "theta_ja_air_k_per_w": "RthetaJA"},
                "limit_fields": {"maximum_c": "Tmax_C"},
                "references": ["U1"], "probes": [{"label": "P1", "x_mm": 1,
                                                   "y_mm": 2, "side": "top"}]}), encoding="utf-8")
            result = {"temperature_limits": {"status": "FAIL"}}
            with patch("quick_therm_plugin.service.run_job", return_value=result) as run_job:
                with contextlib.redirect_stdout(StringIO()):
                    status = main(["C:/Projects/Example/board.kicad_pcb", "--config", str(config),
                                   "--require-limits-pass"])
            self.assertEqual(status, 3)
            self.assertEqual(run_job.call_args.args[0]["probes"][0]["label"], "P1")

    def test_air_request_maps_saved_fields_without_quick_pi(self):
        result = {"quick_therm": {"environment": "air"}}
        with patch("quick_therm_plugin.service.run_job", return_value=result) as run_job:
            with contextlib.redirect_stdout(StringIO()) as output:
                status = main(["C:/Projects/Example/board.kicad_pcb", "--environment", "air",
                               "--power-field", "Power_W", "--theta-ja-field", "RthetaJA",
                               "--thermal-refs", "U1", "U2"])
        self.assertEqual(status, 0)
        request = run_job.call_args.args[0]
        self.assertEqual(request["action"], "quick_therm")
        self.assertEqual(request["field_map"], {
            "power_w": "Power_W", "theta_ja_air_k_per_w": "RthetaJA",
        })
        self.assertEqual(request["references"], ["U1", "U2"])
        self.assertEqual(json.loads(output.getvalue()), result)

    def test_rejects_output_overwriting_board(self):
        board = Path("C:/Projects/Example/board.kicad_pcb")
        with contextlib.redirect_stdout(StringIO()) as output:
            status = main([str(board), "--power-field", "Power_W",
                           "--theta-ja-field", "RthetaJA", "--output", str(board)])
        self.assertEqual(status, 2)
        self.assertIn("must not overwrite", json.loads(output.getvalue())["error"])

    def test_calculix_export_routes_reviewed_settings_to_worker(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            config = Path(temporary) / "thermal.json"
            config.write_text(json.dumps({"field_map": {"power_w": "Power_W"},
                "calculix_settings": {"gmsh_mesh_size_mm": .5,
                    "dielectric_k_w_mk": .3, "bottom_temperature_c": 20}}),
                encoding="utf-8")
            target = Path(temporary) / "thermal-deck"
            with patch("quick_therm_plugin.service.run_job", return_value={"calculix": {
                    "status": "needs_gmsh", "result_status": "not_solved"}}) as run_job:
                with contextlib.redirect_stdout(StringIO()):
                    status = main(["C:/Projects/Example/board.kicad_pcb", "--config",
                                   str(config), "--calculix-dir", str(target),
                                   "--run-calculix"])
            self.assertEqual(status, 0)
            request = run_job.call_args.args[0]
            self.assertEqual(request["calculix_export_dir"], str(target.resolve()))
            self.assertTrue(request["calculix_run"])
            self.assertEqual(request["calculix_settings"]["gmsh_mesh_size_mm"], .5)

    def test_calculix_rejects_missing_reviewed_settings(self):
        with contextlib.redirect_stdout(StringIO()) as output:
            status = main(["C:/Projects/Example/board.kicad_pcb", "--power-field",
                           "Power_W", "--theta-ja-field", "RthetaJA",
                           "--calculix-dir", "C:/Projects/Example/deck"])
        self.assertEqual(status, 2)
        self.assertIn("calculix_settings", json.loads(output.getvalue())["error"])
