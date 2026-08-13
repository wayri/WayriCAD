from __future__ import annotations

import unittest

from signal_integrity_advisor_plugin.analysis import PROTOCOL_PRESETS, SignalIntegrityEngine


class SignalIntegrityTests(unittest.TestCase):
    def test_i2c_pullup_reports_valid_range_and_standard_candidate(self):
        result = SignalIntegrityEngine.i2c_pullup(3.3, 100.0, 300.0, 3.0, 0.4)
        self.assertEqual("PASS", result.status)
        self.assertLess(result.minimum_ohm, result.maximum_ohm)
        self.assertIsNotNone(result.recommended_ohm)
        self.assertGreaterEqual(result.recommended_ohm, result.minimum_ohm)
        self.assertLessEqual(result.recommended_ohm, result.maximum_ohm)

    def test_i2c_pullup_fails_when_electrical_limits_do_not_overlap(self):
        result = SignalIntegrityEngine.i2c_pullup(5.0, 1000.0, 100.0, 1.0, 0.4)
        self.assertEqual("FAIL", result.status)
        self.assertIsNone(result.recommended_ohm)

    def test_protocol_targets_are_editable_numeric_presets(self):
        self.assertIn("CAN / CAN FD", PROTOCOL_PRESETS)
        self.assertIn("USB4 (editable)", PROTOCOL_PRESETS)
        for preset in PROTOCOL_PRESETS.values():
            self.assertGreater(preset["target"], 0)
            self.assertGreater(preset["tolerance"], 0)


if __name__ == "__main__":
    unittest.main()
