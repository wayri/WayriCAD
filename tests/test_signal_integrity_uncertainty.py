"""Unresolved/mixed geometry must not become a numeric SI pass or failure."""
from types import SimpleNamespace
import unittest
from signal_integrity_advisor_plugin.analysis import SignalIntegrityEngine


class SignalIntegrityUncertaintyTests(unittest.TestCase):
    def validate(self, primary, mate=None, target=50):
        engine=SignalIntegrityEngine.__new__(SignalIntegrityEngine)
        engine.measurement=SimpleNamespace(measure=lambda net,*args:mate if net=='N' else primary)
        return engine.validate_impedance('P','J1.1','U1.1','In1.Cu',100,target,10,
                                         'N' if mate else '', 'J1.2','U1.2')

    def path(self, **overrides):
        return SimpleNamespace(**dict(dict(impedance_valid=True,impedance_ohm=50.,
            status='resolved',notes=[],length_mm=12.,zone_count=0,layer_changes=0),**overrides))

    def test_uniform_valid_single_ended_estimate_can_be_compared(self):
        result=self.validate(self.path())
        self.assertEqual(result.status,'PASS')
        self.assertEqual(result.measured_ohm,50)

    def test_nullable_or_invalid_impedance_is_unknown(self):
        for path in (self.path(impedance_ohm=None),self.path(impedance_valid=False),
                     self.path(status='disconnected'),self.path(impedance_ohm=float('nan'))):
            with self.subTest(path=path):
                result=self.validate(path)
                self.assertEqual(result.status,'UNKNOWN')
                self.assertIsNone(result.measured_ohm)
                self.assertIsNone(result.error_percent)

    def test_differential_coupling_is_not_sum_of_single_ended_estimates(self):
        result=self.validate(self.path(),self.path(),target=100)
        self.assertEqual(result.status,'UNKNOWN')
        self.assertIsNone(result.measured_ohm)

    def test_unresolved_mate_does_not_crash_or_pass(self):
        result=self.validate(self.path(),self.path(impedance_ohm=None,impedance_valid=False),target=100)
        self.assertEqual(result.status,'UNKNOWN')

    def test_nonfinite_target_rejected(self):
        with self.assertRaises(ValueError):self.validate(self.path(),target=float('nan'))


if __name__=='__main__':unittest.main()
