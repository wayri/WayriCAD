"""Uncapped baseline evidence is required before accepting a native diff."""
import unittest
from trace_refiner_plugin.refiner import require_comparable_baseline


class ReportGateTests(unittest.TestCase):
    def test_small_baseline_allowed_and_large_per_type_blocked(self):
        require_comparable_baseline(dict(violations=[dict(type='clearance')]*198))
        for category in ('violations','unconnected_items'):
            with self.assertRaisesRegex(ValueError,'Baseline DRC'):
                require_comparable_baseline({category:[dict(type='clearance')]*199})


if __name__=='__main__':unittest.main()
