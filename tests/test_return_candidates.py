"""Geometric suggestions retain domain identity and missing evidence."""
import copy
import unittest
from unittest.mock import patch

from wayricad_runtime.return_candidates import (
    suggest_return_candidates, suggest_return_candidates_from_evidence,
)


def evidence():
    def region(net, x0, x1):
        return {"net": net, "layer": "B.Cu", "outer": [[x0, -1], [x1, -1],
                [x1, 1], [x0, 1]], "holes": []}
    return {"signal_net": "SIG", "return_nets": ["GND", "REF"],
            "layer_order": ["F.Cu", "B.Cu"],
            "segments": [{"layer": "F.Cu", "start": [0, 0], "end": [2, 0]}],
            "reference_regions": [region("GND", 0, .5), region("REF", 0, 2)],
            "return_vias": [], "signal_vias": [], "terminals": []}


class ReturnCandidateTests(unittest.TestCase):
    def test_geometry_beats_name_and_source_is_unchanged(self):
        source = evidence()
        before = copy.deepcopy(source)
        result = suggest_return_candidates_from_evidence(source)
        rows = result["candidates"]
        self.assertEqual([row["net"] for row in rows], ["REF", "GND"])
        self.assertEqual(rows[0]["covered_samples"], 5)
        self.assertEqual(rows[0]["coverage_fraction"], 1)
        self.assertEqual(rows[1]["coverage_fraction"], .4)
        self.assertEqual(source, before)

    def test_domains_stay_separate_and_absent_adjacent_layer_counts_missing(self):
        source = evidence()
        source["reference_regions"][1]["layer"] = "F.Cu"
        rows = {row["net"]: row for row in suggest_return_candidates_from_evidence(source)["candidates"]}
        self.assertEqual(rows["REF"]["total_samples"], 5)
        self.assertEqual(rows["REF"]["covered_samples"], 0)
        self.assertEqual(rows["REF"]["coverage_fraction"], 0)

    def test_unfilled_net_and_truncation_are_explicit(self):
        result = suggest_return_candidates_from_evidence(
            evidence(), max_candidates=2, zone_inventory={"AGND": ["B.Cu"], "SIG": []})
        self.assertTrue(result["truncated"])
        self.assertEqual(result["omitted_nets"], ["REF"])
        self.assertEqual(result["candidate_count"], 3)
        row = next(row for row in result["candidates"] if row["net"] == "AGND")
        self.assertEqual(row["evidence_status"], "UNFILLED_REFERENCE_EVIDENCE")
        self.assertEqual(row["status"], "UNFILLED_REFERENCE_EVIDENCE")
        self.assertIsNone(row["coverage_fraction"])

    def test_unknown_route_has_no_coverage_fraction(self):
        for unsupported in ([], ["Arc on F.Cu"]):
            source = evidence()
            source["segments"] = []
            source["unsupported_geometry"] = unsupported
            for row in suggest_return_candidates_from_evidence(source)["candidates"]:
                self.assertIsNone(row["coverage_fraction"])
                self.assertIn("EVIDENCE", row["status"])
        source = evidence()
        source["unsupported_geometry"] = ["Arc on F.Cu"]
        row = suggest_return_candidates_from_evidence(source)["candidates"][0]
        self.assertIsNone(row["coverage_fraction"])
        self.assertEqual(row["covered_samples"], 5)

    def test_limits_reject_unbounded_or_invalid_requests(self):
        for limit in (True, 0, 33, 1.5):
            with self.assertRaises(ValueError):
                suggest_return_candidates_from_evidence(evidence(), max_candidates=limit)
        for pitch in (True, 0, float("nan")):
            with self.assertRaises(ValueError):
                suggest_return_candidates_from_evidence(evidence(), sample_pitch_mm=pitch)

    def test_board_wrapper_collects_once_and_preserves_unfilled_net_identity(self):
        class Layers:
            def CuStack(self): return [0, 31]
        class Zone:
            def __init__(self, net, filled=True): self.net, self.filled = net, filled
            def GetNetname(self): return self.net
            def GetIsRuleArea(self): return False
            def IsOnLayer(self, layer): return layer == 31
            def IsFilled(self): return self.filled
            def HasFilledPolysForLayer(self, layer): return self.filled
        class Board:
            def GetEnabledLayers(self): return Layers()
            def Zones(self): return [Zone("REF"), Zone("GND"), Zone("AGND", False), Zone("SIG")]
            def GetLayerName(self, layer): return "B.Cu"
        board = Board()
        with patch("wayricad_runtime.return_candidates.collect_board_evidence", return_value=evidence()) as collect:
            result = suggest_return_candidates(board, "SIG")
        collect.assert_called_once_with(board, "SIG", ["AGND", "GND", "REF"])
        rows = {row["net"]: row for row in result["candidates"]}
        self.assertEqual(rows["AGND"]["unfilled_reference_layers"], ["B.Cu"])
        self.assertEqual(rows["REF"]["unfilled_reference_layers"], [])


if __name__ == "__main__":
    unittest.main()
