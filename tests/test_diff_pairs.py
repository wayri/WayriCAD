from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


diff_pairs = _load("trace_impedance_plugin/diff_pairs.py", "kiway_diff_pairs_test")

try:
    import wx  # noqa: F401

    _HAS_WX = True
except ImportError:  # pragma: no cover - CI environments without wxPython
    _HAS_WX = False

if _HAS_WX:
    preview_kit = _load("trace_impedance_plugin/preview_kit.py", "kiway_preview_kit_test")


class DifferentialPairDetectionTests(unittest.TestCase):
    def test_detects_common_suffix_conventions(self):
        names = ["USB_DP", "USB_DM", "ETH_TX_P", "ETH_TX_N", "CLK_+", "CLK_-",
                 "PCIE_RX_DP", "PCIE_RX_DM", "GND", "VCC"]
        pairs = {pair.positive + "/" + pair.negative for pair in diff_pairs.detect_pairs(names)}
        self.assertIn("ETH_TX_P/ETH_TX_N", pairs)
        self.assertIn("PCIE_RX_DP/PCIE_RX_DM", pairs)
        # "+"/"-" pair detected with polarity ordering normalised.
        self.assertTrue(any("CLK_" in value for value in pairs))
        self.assertNotIn("GND/VCC", pairs)

    def test_find_mate_is_case_insensitive_and_rule_labelled(self):
        nets = ["CAN_P", "can_n", "MIDI_P"]
        self.assertEqual("can_n", diff_pairs.find_mate("CAN_P", nets))
        pairs = diff_pairs.detect_pairs(nets)
        self.assertEqual(1, len(pairs))
        self.assertIn("_P/_N", pairs[0].rule)

    def test_loose_tail_rule_rejects_short_words(self):
        self.assertEqual("", diff_pairs.find_mate("CAP", ["CAP", "CAN"]))

    def test_pair_key_collapses_legs(self):
        self.assertEqual(diff_pairs.pair_key("USB_DP"), diff_pairs.pair_key("usb_dn"))
        self.assertNotEqual(diff_pairs.pair_key("USB_DP"), diff_pairs.pair_key("USB"))


@unittest.skipUnless(_HAS_WX, "preview_kit requires wxPython")
class PickHitTestingTests(unittest.TestCase):
    def test_nearest_pick_within_tolerance_wins(self):
        picks = [
            {"sx": 100, "sy": 100, "r": 6, "data": "a"},
            {"sx": 120, "sy": 100, "r": 6, "data": "b"},
        ]
        self.assertEqual("a", preview_kit.pick_nearest(picks, 104, 99)["data"])
        self.assertEqual("b", preview_kit.pick_nearest(picks, 118, 101)["data"])
        self.assertIsNone(preview_kit.pick_nearest(picks, 160, 160))

    def test_large_radius_extends_hit_area(self):
        picks = [{"sx": 0, "sy": 0, "r": 30, "data": "big"}]
        self.assertEqual("big", preview_kit.pick_nearest(picks, 25, 18)["data"])


if __name__ == "__main__":
    unittest.main()
