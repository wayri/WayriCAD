import unittest
from unittest.mock import patch,MagicMock
from signal_integrity_advisor_plugin.quick_si import analyze,screen,html_report
from signal_integrity_advisor_plugin.measurement import PathMeasurement
class ExplicitReturnTests(unittest.TestCase):
 def path(self):return PathMeasurement('DATA','U1.1','J1.1',status='ok',length_mm=1,impedance_valid=True,impedance_ohm=50,propagation_delay_ns=.01)
 def engine(self):
  engine=MagicMock();engine.pads_for_net.return_value=['U1.1','J1.1'];engine.measure.return_value=self.path();return engine
 def test_no_implicit_return_nets(self):
  with patch('signal_integrity_advisor_plugin.quick_si.TraceMeasurementEngine',return_value=self.engine()),patch('wayricad_runtime.return_path.collect_board_evidence') as collect:
   report,path=analyze(object(),'DATA','U1.1','J1.1');collect.assert_not_called();self.assertNotIn('return_path',report)
 def test_explicit_return_review_is_separate_from_line_screen(self):
  from wayricad_runtime.return_path import audit_return_path
  evidence={'signal_net':'DATA','return_nets':['GND'],'layer_order':['F.Cu','B.Cu'],'segments':[]}
  with patch('signal_integrity_advisor_plugin.quick_si.TraceMeasurementEngine',return_value=self.engine()),patch('wayricad_runtime.return_path.collect_board_evidence',return_value=evidence) as collect:
   board=object();report,path=analyze(board,'DATA','U1.1','J1.1',return_nets=['GND'])
   collect.assert_called_once_with(board,'DATA',['GND'])
   self.assertEqual(report['status'],'SCREENED');self.assertEqual(report['return_path']['status'],'INCOMPLETE')
   self.assertIn('Whole selected',report['return_path']['scope'])
   output=html_report(report);self.assertIn('Explicit return-path review',output);self.assertIn('source/load return closure is unresolved',output)
if __name__=='__main__':unittest.main()
