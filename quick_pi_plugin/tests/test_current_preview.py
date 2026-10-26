"""Cursor readout values, units and pending-state honesty."""
import unittest
from quick_pi_plugin.current_preview import comparison,values
from quick_pi_plugin.tests.test_report import bundle
from quick_pi_plugin.live_current import LiveCurrentModel


class CurrentPreviewTests(unittest.TestCase):
    def fixture(self):
        base=bundle();base['request'].update(action='solve',source_voltage=1.,sink_current=2.)
        return base,LiveCurrentModel(base).update(4.)

    def test_selected_local_metric_and_current_before_after(self):
        before,after=self.fixture()
        rows=comparison(before,after,'density',('sheet',0))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['before'],2.)
        self.assertEqual(rows[0]['after'],4.)
        self.assertAlmostEqual(rows[1]['after'],2*rows[1]['before'])
        self.assertEqual(rows[1]['unit'],'A/mm²')

    def test_all_metrics_quadratic_loss_and_pending_unknown(self):
        before,after=self.fixture()
        a=values(before,('sheet',0));b=values(after,('sheet',0))
        self.assertAlmostEqual(b['loss'],4*a['loss'])
        self.assertAlmostEqual(b['melt'],4*a['melt'])
        pending=comparison(before,None,'density',('sheet',0),all_fields=True,pending_current=3.)
        self.assertEqual(len(pending),10)
        self.assertEqual(pending[0]['after'],3.)
        self.assertTrue(all(row['after'] is None for row in pending[1:]))

    def test_projection_retains_known_sink_voltage_without_inventing_local_j(self):
        before,_=self.fixture()
        value=values(before,sink=0)
        self.assertIsNotNone(value['voltage'])
        self.assertIsNone(value['density'])
