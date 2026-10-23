"""Native connector search regressions for indexed checks and pad contacts."""
import unittest
from unittest.mock import patch

import test_connector_escape as fixture
from wayricad_runtime.routing import FanoutPlanner

p = fixture.p


@unittest.skipIf(p is None, 'Native KiCad required')
class ConnectorSearchTests(unittest.TestCase):
    setUp = fixture.ConnectorTests.setUp
    pos = staticmethod(fixture.ConnectorTests.pos)
    pad = fixture.ConnectorTests.pad
    connector = fixture.ConnectorTests.connector
    plan = fixture.ConnectorTests.plan

    def test_default_clearance_keeps_indexed_obstacles(self):
        self.connector()
        original = FanoutPlanner._blocked
        checks = []

        def checked(planner, plan, accepted, pads, tracks, zones, outline, margin):
            indices = planner._obstacle_indices
            checks.append((pads is indices[0], tracks is indices[1], zones is indices[2]))
            return original(planner, plan, accepted, pads, tracks, zones, outline, margin)

        with patch.object(FanoutPlanner, '_blocked', checked):
            plans, rejected = self.plan(pad_filter='1,2,3')
        self.assertFalse(rejected)
        self.assertEqual(len(plans), 3)
        self.assertTrue(checks)
        self.assertTrue(all(all(row) for row in checks))
        self.assertTrue(all(len(plan.path) == 2 for plan in plans))

    def test_midsegment_pad_contact_is_not_duplicated(self):
        self.connector()
        pad = next(item for item in self.fp.Pads() if item.GetNumber() == '1')
        track = p.PCB_TRACK(self.board)
        track.SetStart(self.pos(16, 19))
        track.SetEnd(self.pos(18, 19))
        track.SetLayer(p.F_Cu)
        track.SetWidth(p.FromMM(.2))
        track.SetNetCode(pad.GetNetCode())
        self.board.Add(track)
        plans, rejected = self.plan(pad_filter='1')
        self.assertFalse(plans)
        self.assertEqual(len(rejected), 1)
        self.assertIn('already has connected copper', rejected[0])


if __name__ == '__main__':
    unittest.main()
