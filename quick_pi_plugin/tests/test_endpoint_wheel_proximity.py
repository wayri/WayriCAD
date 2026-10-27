"""Native wheel targeting on close, overlapping, grouped and source contacts."""
import unittest
from unittest.mock import patch

from quick_pi_plugin.tests import test_live_ui as live_tests
from quick_pi_plugin.tests import test_sink_wheel as sink_tests


@unittest.skipIf(live_tests.wx is None,'Native KiCad wx runtime required')
class EndpointWheelTests(unittest.TestCase):
    setUp=live_tests.LiveUITests.setUp
    tearDown=live_tests.LiveUITests.tearDown
    until=live_tests.LiveUITests.until
    event=live_tests.LiveUITests.event
    multi=sink_tests.SinkWheelTests.multi

    def test_near_sink_outside_copper_targets_only_that_load(self):
        frame=self.multi();ax=frame.views[2][0].axes[0]
        x,y=ax.transData.transform((10.,.5));x,y=ax.transData.inverted().transform((x+12.,y))
        with patch.object(frame,'_queue_live_current') as queue:
            self.assertTrue(frame._live_wheel(self.event(xdata=x,ydata=y)))
        args=queue.call_args.args
        self.assertAlmostEqual(args[1][0],1.01)
        self.assertEqual(args[1][1],2.)

    def test_overlap_consumes_scroll_without_changing_total_or_sinks(self):
        frame=self.multi()
        first=dict(frame._live_endpoint_anchors[0]);other=dict(first,index=1,label='Other load')
        frame._live_endpoint_anchors=[first,other]
        before=frame.live_current.GetValue()
        with patch.object(frame,'_queue_live_current') as queue:
            self.assertTrue(frame._live_wheel(self.event(xdata=first['center'][0],ydata=first['center'][1])))
        queue.assert_not_called()
        self.assertEqual(frame.live_current.GetValue(),before)
        self.assertIn('ambiguous',frame.status.GetLabel())

    def test_source_proximity_scales_total_and_plain_wheel_still_zooms(self):
        frame=self.multi();ax=frame.views[2][0].axes[0]
        source=next(row for row in frame._live_endpoint_anchors if row['role']=='source')
        x,y=ax.transData.transform(source['center']);x,y=ax.transData.inverted().transform((x-12.,y))
        with patch.object(frame,'_queue_live_current') as queue:
            self.assertFalse(frame._live_wheel(self.event(xdata=x,ydata=y,key=None)))
            self.assertTrue(frame._live_wheel(self.event(xdata=x,ydata=y)))
        self.assertEqual(len(queue.call_args.args),1)
        self.assertAlmostEqual(queue.call_args.args[0],3.01)


if __name__=='__main__':unittest.main()
