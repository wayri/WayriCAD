"""Return-path screening checks that run without native KiCad bindings."""
import unittest

from quick_pi_plugin.return_path import audit_return_path


LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


def plane(layer, *, hole=None):
    return {"net": "GND", "layer": layer,
            "outer": [[-1, -1], [11, -1], [11, 2], [-1, 2]],
            "holes": [hole] if hole else []}


def line(layer, start=(0, 0), end=(10, 0)):
    return {"layer": layer, "start": list(start), "end": list(end), "width_mm": .2}


def evidence(**changes):
    data = {"signal_net": "VCC", "return_nets": ["GND"], "layer_order": LAYERS,
            "segments": [line("F.Cu")], "signal_vias": [], "return_vias": [],
            "reference_regions": [plane("In1.Cu")],
            "unfilled_reference_layers": [], "unsupported_geometry": []}
    data.update(changes)
    return data


class ReturnPathTests(unittest.TestCase):
    def test_covered_track_has_no_findings_but_no_proof_claim(self):
        result = audit_return_path(evidence())
        self.assertEqual(result["warning_count"], 0)
        self.assertIn("not a proof", result["basis"])

    def test_hole_crossing_signal_yields_local_gap(self):
        hole = [[4, -.5], [6, -.5], [6, .5], [4, .5]]
        result = audit_return_path(evidence(reference_regions=[plane("In1.Cu", hole=hole)]))
        self.assertEqual([f["code"] for f in result["findings"]], ["REFERENCE_GAP_SAMPLED"])
        self.assertGreaterEqual(result["findings"][0]["position_mm"][0], 4)

    def test_unfilled_zone_is_unknown_instead_of_false_warning(self):
        result = audit_return_path(evidence(reference_regions=[], unfilled_reference_layers=["In1.Cu"]))
        self.assertEqual(result["warning_count"], 0)
        self.assertEqual(result["findings"][0]["level"], "unknown")

    def test_transition_reports_missing_spanning_return_via(self):
        segments = [line("F.Cu", (0, 0), (5, 0)), line("B.Cu", (5, 0), (10, 0))]
        via = {"net": "VCC", "position": [5, 0], "layers": LAYERS}
        data = evidence(segments=segments, signal_vias=[via],
                        reference_regions=[plane("In1.Cu"), plane("In2.Cu")])
        codes = [f["code"] for f in audit_return_path(data)["findings"]]
        self.assertIn("NO_NEARBY_RETURN_VIA", codes)
        data["return_vias"] = [{"net": "GND", "position": [5.5, 0], "layers": LAYERS}]
        codes = [f["code"] for f in audit_return_path(data)["findings"]]
        self.assertNotIn("NO_NEARBY_RETURN_VIA", codes)

    def test_unused_through_via_layers_do_not_create_fake_transition(self):
        via = {"net": "VCC", "position": [5, 0], "layers": LAYERS}
        result = audit_return_path(evidence(signal_vias=[via]))
        self.assertIn("TRANSITION_LAYERS_UNKNOWN", [f["code"] for f in result["findings"]])

    def test_unknown_arc_and_bad_pitch(self):
        result = audit_return_path(evidence(unsupported_geometry=["Arc on F.Cu"]))
        self.assertIn("UNSUPPORTED_GEOMETRY", [f["code"] for f in result["findings"]])
        with self.assertRaises(ValueError):
            audit_return_path(evidence(), sample_pitch_mm=0)


if __name__ == "__main__":
    unittest.main()
