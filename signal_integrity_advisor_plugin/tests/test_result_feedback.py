"""Readability and evidence labels without a GUI or native board runtime."""
import unittest

from signal_integrity_advisor_plugin.result_feedback import eye_feedback, summary_text


class FeedbackTests(unittest.TestCase):
    def test_header_uses_displayed_case_not_different_main_inputs(self):
        values=dict(net='DRAFT',start='U1.1',end='J1.1')
        report=dict(path=dict(net_name='CLOCK',start_pad='U2.3',end_pad='J2.4'),delay_ns=.123456)
        text,tip=summary_text(values,report,saved_board=True)
        self.assertIn('CLOCK',text);self.assertIn('U2.3 → J2.4',text)
        self.assertNotIn('DRAFT',text);self.assertIn('0.1235 ns',text)
        self.assertIn('Saved PCB snapshot',tip)

    def test_unavailable_reason_remains_readable_in_tooltip(self):
        reason='Via return-loop inductance is missing. '+('Long channel evidence. '*20)
        text,tip=summary_text(dict(net='DATA'),dict(eye=dict(status='UNAVAILABLE',reason=reason)))
        self.assertIn('Eye unavailable',text);self.assertIn(reason,tip)
        self.assertIn('Open Setup',tip)
        self.assertNotIn(reason,text)

    def test_model_labels_do_not_infer_unknown_results_are_ideal(self):
        self.assertEqual(eye_feedback(None),('', 'Eye / step'))
        self.assertEqual(eye_feedback(dict(model='board-section-rlc-prbs7'))[0],'Board RLC eye')
        self.assertEqual(eye_feedback(dict(model='uniform-lossless-line-prbs7'))[0],'Ideal-line eye')
        self.assertEqual(eye_feedback(dict(model='future-channel'))[0],'Eye result')

    def test_missing_inputs_and_nonfinite_delay_are_not_fake_results(self):
        text,tip=summary_text(dict(net='',start='',end=''),dict(delay_ns=float('nan')))
        self.assertIn('Set up a path',text);self.assertNotIn('nan',text)


if __name__=='__main__':unittest.main()
