"""Saved-board view and deliberately bounded thermal interpolation checks."""
import json
import unittest
from pathlib import Path

from quick_therm_plugin.thermal_board_view import _drill_ring, _hull, _inside, build_board_thermal_view


FIXTURE = (Path(__file__).resolve().parents[2] / "mechanical_check_plugin" /
           "tests" / "fixtures" / "validation-fixture.kicad_pcb")


def result(refs=("J1", "C1", "C3")):
    temps = {"J1": 40., "C1": 50., "C3": 60.}
    rows = [{"reference": ref, "junction_c": temps[ref], "power_w": i + 1.}
            for i, ref in enumerate(refs)]
    return {"components": rows, "coverage": {"scoped": len(rows) + 1,
            "solved": len(rows), "excluded": [{"reference": "C2", "issues": ["missing power"]}]}}


class PureGeometryTests(unittest.TestCase):
    def test_rotated_slot_display_preserves_drill_envelope(self):
        ring = _drill_ring([10., 20.], [3.6, 1.], 90.)
        self.assertAlmostEqual(max(p[0] for p in ring)-min(p[0] for p in ring), 1.)
        self.assertAlmostEqual(max(p[1] for p in ring)-min(p[1] for p in ring), 3.6)
        self.assertTrue(_inside([10., 20.], ring))
        angled = _drill_ring([10., 20.], [3.6, 1.], 45.)
        self.assertAlmostEqual(angled[0][0], 10. + 1.8 / 2**.5)
        self.assertAlmostEqual(angled[0][1], 20. - 1.8 / 2**.5)
        self.assertEqual(_drill_ring([0., 0.], [0., 0.]), [])

    def test_hull_and_concave_outline_mask(self):
        self.assertEqual(len(_hull([[0, 0], [3, 0], [1, 1], [0, 3]])), 3)
        concave = [[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4]]
        self.assertTrue(_inside([.5, 3], concave))
        self.assertFalse(_inside([3, 3], concave))


class NativeBoardViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import pcbnew
        except ImportError:
            raise unittest.SkipTest("Native KiCad pcbnew binding unavailable")
        cls.board = pcbnew.LoadBoard(str(FIXTURE))

    def test_outline_positions_analytics_and_mask(self):
        view = build_board_thermal_view(self.board, result(), grid_size=30)
        self.assertEqual(view["bbox_mm"], [0., 0., 60., 40.])
        self.assertEqual(len(view["outline"]), 1)
        self.assertTrue(view["drills"])
        self.assertTrue(all(len(row["contour_mm"]) >= 12 for row in view["drills"]))
        self.assertEqual(view["field"]["status"], "available")
        components = {row["reference"]: row for row in view["components"]}
        self.assertEqual(components["J1"]["position_mm"], [11., 8.])
        self.assertEqual(components["J1"]["id"], next(fp.m_Uuid.AsString() for fp in self.board.GetFootprints() if fp.GetReference() == "J1"))
        self.assertTrue(components["J1"]["top_side"])
        self.assertEqual(len(components["J1"]["bbox_mm"]), 4)
        self.assertEqual(view["bbox_status"], "verified_outline")
        self.assertAlmostEqual(view["board_thickness_mm"], 1.6)
        self.assertEqual(view["fields_by_side"]["top"]["status"], "available")
        self.assertEqual(view["fields_by_side"]["bottom"]["status"], "unavailable")
        self.assertEqual(components["C1"]["junction_c"], 50.)
        self.assertEqual(components["C2"]["issues"], ["missing power"])
        self.assertIsNone(components["H1"]["junction_c"])
        stats = view["analytics"]
        self.assertEqual(stats["temperature_c"], {"min": 40., "max": 60., "mean": 50., "median": 50.})
        self.assertEqual(stats["hottest_reference"], "C3")
        self.assertEqual(stats["coverage"]["scoped"], 4)
        grid = view["field"]["values_c"]
        self.assertIsNone(grid[0][0])  # Outside the component support hull.
        self.assertTrue(any(value is not None for line in grid for value in line))
        json.dumps(view, allow_nan=False)

    def test_insufficient_anchors_do_not_create_field(self):
        view = build_board_thermal_view(self.board, result(("J1", "C1")), grid_size=12)
        self.assertEqual(view["field"]["status"], "unavailable")
        self.assertEqual(view["field"]["values_c"], [])

    def test_result_reference_must_match_saved_board(self):
        data = result(("J1", "C1", "C3"))
        data["components"][0]["reference"] = "U404"
        with self.assertRaisesRegex(ValueError, "absent from saved board"):
            build_board_thermal_view(self.board, data)

    def test_native_outline_feeds_conduction_radiation_airflow_model(self):
        from quick_therm_plugin.thermal_network import solve_thermal_network
        data=result()
        data.update(environment='air',ambient_c=25.)
        for row in data['components']:row['heat_path']='air'
        view=build_board_thermal_view(self.board,data,grid_size=16)
        modeled=solve_thermal_network(view,data,{
            'board_k_w_mk':0.3,'board_thickness_mm':view['board_thickness_mm'],
            'board_emissivity':0.9,'board_airflow_m_s':1.,'sink_airflow_m_s':0.})
        self.assertEqual(modeled['status'],'converged')
        self.assertGreater(modeled['board_field']['sampled_max_c'],25.)
        self.assertLess(abs(modeled['heat_balance']['residual_w']),modeled['heat_balance']['tolerance_w'])
        json.dumps(modeled,allow_nan=False)


if __name__ == "__main__":
    unittest.main()
