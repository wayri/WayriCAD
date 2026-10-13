"""Native connector edge breakout, filters and physical obstacle regressions."""
import unittest
import test_advanced_fanout as fixture
from wayricad_runtime.routing import plan_fanout
from wayricad_runtime.connector_escape import envelope
from wayricad_runtime.geometry import board_fingerprint
p=fixture.pcbnew

@unittest.skipIf(p is None, 'Native KiCad required')
class ConnectorTests(unittest.TestCase):
    setUp=fixture.AdvancedFanoutTests.setUp
    pos=staticmethod(fixture.AdvancedFanoutTests.pos)
    pad=fixture.AdvancedFanoutTests.pad

    def connector(self):
        self.fp.SetReference('J1')
        for number,(x,y) in enumerate(((17,19),(20,19),(23,19),(17,21),(20,21),(23,21)),1):
            pad=self.pad('PIN'+str(number),x,y,str(number))
            pad.SetSize(self.pos(1.4,1.4));pad.SetDrillSize(self.pos(.8,.8))
            pad.SetAttribute(p.PAD_ATTRIB_PTH);pad.SetLayerSet(p.LSET.AllCuMask())
        body=p.PCB_SHAPE(self.fp);body.SetShape(p.SHAPE_T_RECT)
        body.SetStart(self.pos(15,17));body.SetEnd(self.pos(25,23));body.SetLayer(p.F_CrtYd)
        self.fp.Add(body);self.fp.BuildCourtyardCaches()

    def plan(self, **settings):
        return plan_fanout(self.board,p,dict({'pattern':'Connector edge','scope':'Reference wildcard','ref':'J1','add_vias':False,'width':.2,'clearance':.2},**settings))

    def test_all_pth_pins_reach_envelope_and_preserve_board(self):
        self.connector();before=board_fingerprint(self.board)
        plans,rejected=self.plan();self.assertFalse(rejected);self.assertEqual(len(plans),6)
        bounds,local,_,_=envelope(self.fp,p,p.F_Cu)
        for plan in plans:
            x,y=local(plan.end);self.assertAlmostEqual(min(abs(x-(bounds[0]-p.FromMM(.5))),abs(x-(bounds[2]+p.FromMM(.5))),abs(y-(bounds[1]-p.FromMM(.5))),abs(y-(bounds[3]+p.FromMM(.5)))),0,delta=2)
            self.assertFalse(plan.start_via)
        self.assertEqual(before,board_fingerprint(self.board))

    def test_pin_and_net_filters_intersect(self):
        self.connector();plans,rejected=self.plan(pad_filter='1,2,3',net_filter='PIN2,PIN6')
        self.assertFalse(rejected);self.assertEqual([x.pad.GetNumber() for x in plans],['2'])

    def test_all_connector_scope_and_existing_smd_scope(self):
        self.connector();plans,rejected=self.plan(scope='All connector pads')
        self.assertFalse(rejected);self.assertEqual(len(plans),6)
        plans,_=self.plan(scope='All SMD pads');self.assertFalse(plans)

    def test_bottom_layer_needs_no_source_via(self):
        self.connector();plans,rejected=self.plan(escape_layer='B.Cu',pad_filter='1')
        self.assertFalse(rejected);self.assertFalse(plans[0].start_via)
        self.assertEqual(plans[0].layer,p.B_Cu)

    def test_rotated_connector_exit_is_local(self):
        self.connector();self.fp.SetOrientationDegrees(90)
        plans,rejected=self.plan(connector_exit='Top',pad_filter='1')
        self.assertFalse(rejected);bounds,local,_,_=envelope(self.fp,p,p.F_Cu)
        self.assertAlmostEqual(local(plans[0].end)[1],bounds[1]-p.FromMM(.5),delta=2)

    def test_npth_is_not_routed(self):
        self.connector();list(self.fp.Pads())[0].SetAttribute(p.PAD_ATTRIB_NPTH)
        plans,_=self.plan();self.assertEqual(len(plans),5)

    def test_existing_route_is_not_duplicated(self):
        self.connector();pad=list(self.fp.Pads())[0]
        track=p.PCB_TRACK(self.board);track.SetStart(pad.GetPosition());track.SetEnd(self.pos(17,16));track.SetLayer(p.F_Cu);track.SetWidth(p.FromMM(.2));track.SetNetCode(pad.GetNetCode());self.board.Add(track)
        plans,rejected=self.plan(pad_filter=pad.GetNumber())
        self.assertFalse(plans);self.assertIn('already has',rejected[0])

if __name__=='__main__':unittest.main()
