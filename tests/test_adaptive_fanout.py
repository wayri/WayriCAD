"""Native adaptive escapes: real board obstacles and unchanged existing copper."""
import unittest
import math
from unittest.mock import patch
import test_advanced_fanout as fixture
from wayricad_runtime.routing import FanoutPlanner, plan_fanout
from wayricad_runtime.adaptive_fanout import adaptive_paths, MAX_CANDIDATES
from wayricad_runtime.geometry import board_fingerprint
p=fixture.pcbnew

@unittest.skipIf(p is None,'Native KiCad required')
class AdaptiveTests(unittest.TestCase):
 setUp=fixture.AdvancedFanoutTests.setUp
 pos=staticmethod(fixture.AdvancedFanoutTests.pos)
 pad=fixture.AdvancedFanoutTests.pad
 def track(self,pad,a,b):
  track=p.PCB_TRACK(self.board);track.SetStart(self.pos(*a));track.SetEnd(self.pos(*b));track.SetWidth(p.FromMM(.15));track.SetLayer(p.F_Cu);track.SetNetCode(pad.GetNetCode());self.board.Add(track);return track
 def search(self,pad,**options):
  planner=FanoutPlanner(self.board,p,dict(pattern='Radial outward',width=.15,clearance=.1,via_diameter=.5,via_drill=.2,add_vias=True))
  values=dict(planner._dimensions(),adaptive_radius=2,adaptive_step=.25);values.update(options)
  outline=p.SHAPE_POLY_SET();self.assertTrue(self.board.GetBoardPolygonOutlines(outline,False))
  return adaptive_paths(planner,self.fp,pad,values,'Radial outward',[],list(self.fp.Pads()),list(self.board.GetTracks()),list(self.board.Zones()),outline,p.FromMM(.1))
 def test_unobstructed_is_deterministic_and_read_only(self):
  pad=self.pad('SIGNAL',22,20);before=board_fingerprint(self.board)
  a,reason=self.search(pad);self.assertFalse(reason);b,_=self.search(pad)
  self.assertEqual([(v.x,v.y) for v in a.path],[(v.x,v.y) for v in b.path]);self.assertEqual(before,board_fingerprint(self.board))
  self.assertTrue(a.add_via);self.assertLessEqual(a.length_mm,2)
 def test_obstacle_changes_nearest_escape_without_mutation(self):
  pad=self.pad('SIGNAL',22,20);baseline,_=self.search(pad)
  other=self.pad('BLOCK',p.ToMM(baseline.end.x),p.ToMM(baseline.end.y));other.SetSize(self.pos(.4,.4))
  before=board_fingerprint(self.board);candidate,reason=self.search(pad);self.assertFalse(reason)
  self.assertNotEqual((candidate.end.x,candidate.end.y),(baseline.end.x,baseline.end.y));self.assertEqual(before,board_fingerprint(self.board))
 def test_continues_two_segment_open_stub(self):
  pad=self.pad('SIGNAL',22,20);self.track(pad,(22,20),(23,20));self.track(pad,(23,20),(24,20))
  before=board_fingerprint(self.board);candidate,reason=self.search(pad);self.assertFalse(reason)
  self.assertEqual((candidate.start.x,candidate.start.y),(p.FromMM(24),p.FromMM(20)));self.assertFalse(candidate.start_via)
  self.assertEqual(before,board_fingerprint(self.board));self.assertEqual(len(list(self.board.GetTracks())),2)
 def test_refuses_branch_and_other_pad_connection(self):
  pad=self.pad('SIGNAL',22,20);self.track(pad,(22,20),(23,20));self.track(pad,(23,20),(24,20));self.track(pad,(23,20),(23,21))
  candidate,reason=self.search(pad);self.assertIsNone(candidate);self.assertIn('branched',reason)
 def test_refuses_existing_via_at_stub_end(self):
  pad=self.pad('SIGNAL',22,20);self.track(pad,(22,20),(23,20));via=p.PCB_VIA(self.board);via.SetPosition(self.pos(23,20));via.SetWidth(p.FromMM(.5));via.SetDrill(p.FromMM(.2));via.SetLayerPair(p.F_Cu,p.B_Cu);via.SetNetCode(pad.GetNetCode());self.board.Add(via)
  candidate,reason=self.search(pad);self.assertIsNone(candidate);self.assertIn('vias/arcs',reason)
 def test_budget_and_impossible_search_fail_explicitly(self):
  pad=self.pad('SIGNAL',22,20)
  candidate,reason=self.search(pad,adaptive_step=.001);self.assertIsNone(candidate);self.assertIn('radius/step',reason)
  obstacle=self.pad('BLOCK',22,20);obstacle.SetSize(self.pos(10,10))
  candidate,reason=self.search(pad);self.assertIsNone(candidate);self.assertIn('search exhausted',reason)
 def test_full_planner_continues_stub_and_retains_original_items(self):
  pad=self.pad('SIGNAL',22,20);self.track(pad,(22,20),(23,20));before=board_fingerprint(self.board)
  plans,rejected=plan_fanout(self.board,p,dict(routing_mode='Adaptive',pattern='Perimeter pitch expansion',adaptive_radius=2,adaptive_step=.25,width=.15,clearance=.1,via_diameter=.5,via_drill=.2))
  self.assertFalse(rejected);self.assertEqual(len(plans),1)
  self.assertEqual((plans[0].start.x,plans[0].start.y),(p.FromMM(23),p.FromMM(20)));self.assertEqual(before,board_fingerprint(self.board))
 def test_actual_other_pad_and_midsegment_branch_refused(self):
  pad=self.pad('SIGNAL',22,20);self.track(pad,(22,20),(24,20))
  other=self.pad('SIGNAL',24,20);other.SetNetCode(pad.GetNetCode())
  candidate,reason=self.search(pad);self.assertIsNone(candidate);self.assertIn('another pad',reason)
  self.fp.Remove(other);self.track(pad,(23,20),(23,21))
  candidate,reason=self.search(pad);self.assertIsNone(candidate);self.assertIn('interior junction',reason)
 def test_perimeter_launch_is_outward_aligned_and_monotonic_when_rotated(self):
  from wayricad_runtime.perimeter_escape import _basis
  pad=self.pad('SIGNAL',22,20);pad.SetSize(self.pos(.9,.25))
  for rotation in (0,37,90):
   self.fp.SetOrientationDegrees(rotation)
   plans,rejected=plan_fanout(self.board,p,dict(routing_mode='Adaptive',pattern='Perimeter pitch expansion',adaptive_radius=2,adaptive_step=.25,width=.15,clearance=.1,via_diameter=.5,via_drill=.2,launch_length=.5))
   self.assertFalse(rejected);candidate=plans[0];_,normal,tangent=_basis(self.fp,pad)
   a,b=candidate.path[:2];dx,dy=b.x-a.x,b.y-a.y
   self.assertLessEqual(abs(dx*tangent[0]+dy*tangent[1]),2)
   self.assertGreaterEqual(dx*normal[0]+dy*normal[1],p.FromMM(.95)-2)
   for a,b in zip(candidate.path,candidate.path[1:]):self.assertGreaterEqual((b.x-a.x)*normal[0]+(b.y-a.y)*normal[1],-2)
   self.assertLessEqual(math.hypot(candidate.end.x-pad.GetPosition().x,candidate.end.y-pad.GetPosition().y),p.FromMM(2)+2)
 def test_perimeter_avoids_endpoint_obstacle_and_reports_insufficient_radius(self):
  pad=self.pad('SIGNAL',22,20);pad.SetSize(self.pos(.9,.25))
  self.pad('BLOCK',23.35,20)
  settings=dict(routing_mode='Adaptive',pattern='Perimeter pitch expansion',adaptive_radius=2,adaptive_step=.25,width=.15,clearance=.1,via_diameter=.5,via_drill=.2,launch_length=.2,net_filter='SIGNAL')
  plans,rejected=plan_fanout(self.board,p,settings);self.assertFalse(rejected)
  self.assertNotEqual(plans[0].end.y,pad.GetPosition().y)
  settings.update(adaptive_radius=.25,adaptive_step=.25,launch_length=.5)
  plans,rejected=plan_fanout(self.board,p,settings);self.assertFalse(plans);self.assertIn('radius is insufficient',rejected[0])
 def test_time_budget_has_actionable_failure(self):
  pad=self.pad('SIGNAL',22,20)
  with patch('wayricad_runtime.adaptive_fanout.time.monotonic',side_effect=[0,4]):candidate,reason=self.search(pad)
  self.assertIsNone(candidate);self.assertIn('time budget',reason)
if __name__=='__main__':unittest.main()

