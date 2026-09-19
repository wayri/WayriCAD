import math,unittest
from wayricad_runtime.routing import plan_fanout,fanout_items
try:import pcbnew as p
except ImportError:p=None

@unittest.skipIf(p is None,'Native KiCad required')
class PerimeterExpansionTests(unittest.TestCase):
 def fixture(self,qfp=False,rotation=0):
  b=p.BOARD();f=p.FOOTPRINT(b);f.SetReference('U1');f.SetPosition(self.xy(20,20));b.Add(f)
  for a,z in (((0,0),(40,0)),((40,0),(40,40)),((40,40),(0,40)),((0,40),(0,0))):
   line=p.PCB_SHAPE(b);line.SetShape(p.SHAPE_T_SEGMENT);line.SetLayer(p.Edge_Cuts);line.SetStart(self.xy(*a));line.SetEnd(self.xy(*z));b.Add(line)
  for side in range(4 if qfp else 2):
   angle=(side if qfp else side*2)*math.pi/2
   for i in range(8):
    n=p.NETINFO_ITEM(b,'N'+str(side*8+i));b.Add(n);pad=p.PAD(f);pad.SetNumber(str(side*8+i+1));pad.SetNet(n);pad.SetAttribute(p.PAD_ATTRIB_SMD);pad.SetShape(p.PAD_SHAPE_RECT);pad.SetSize(self.xy(.9,.25));pad.SetOrientationDegrees(-math.degrees(angle));t=(i-3.5)*.5
    pad.SetPosition(self.xy(20+4*math.cos(angle)-t*math.sin(angle),20+4*math.sin(angle)+t*math.cos(angle)));ls=p.LSET();ls.AddLayer(p.F_Cu);pad.SetLayerSet(ls);f.Add(pad)
  f.SetOrientationDegrees(rotation);return b,f
 @staticmethod
 def xy(x,y):return p.VECTOR2I(p.FromMM(x),p.FromMM(y))
 def plan(self,b,**options):
  return plan_fanout(b,p,dict(dict(pattern='Perimeter pitch expansion',spread_pitch=.8,width=.15,clearance=.1,via_diameter=.5,via_drill=.2),**options))
 def test_qfp_and_soic_all_pads_use_straight_then_45_bends(self):
  for qfp in (False,True):
   b,f=self.fixture(qfp);plans,rejected=self.plan(b);self.assertFalse(rejected);self.assertEqual(len(plans),32 if qfp else 16)
   for plan in plans:
    normal=(plan.path[1].x-plan.path[0].x,plan.path[1].y-plan.path[0].y)
    self.assertTrue(normal[0]==0 or normal[1]==0)
    for a,z in zip(plan.path,plan.path[1:]):
     dx,dy=abs(z.x-a.x),abs(z.y-a.y);self.assertTrue(dx==0 or dy==0 or abs(dx-dy)<=2)
   self.assertEqual(len(fanout_items(b,p,plans)),len(plans)*4)
 def test_rotated_package_preserves_pitch_and_pad_alignment(self):
  b,f=self.fixture(rotation=90);plans,rejected=self.plan(b);self.assertFalse(rejected)
  endpoints=sorted(p.ToMM(plan.end.x) for plan in plans if int(plan.pad.GetNumber())<=8)
  for a,z in zip(endpoints,endpoints[1:]):self.assertAlmostEqual(z-a,.8,places=5)
 def test_outer_pads_bend_before_inner_pads(self):
  b,f=self.fixture();plans,rejected=self.plan(b);lookup={plan.pad.GetNumber():plan for plan in plans}
  self.assertLess(lookup['1'].path[1].x,lookup['4'].path[1].x)
 def test_small_pitch_rejected_and_via_in_pad_still_independent(self):
  b,f=self.fixture();plans,rejected=self.plan(b,add_vias=False,spread_pitch=.2)
  self.assertFalse(plans);self.assertTrue(all('Outer pitch' in reason for reason in rejected))
 def test_grid_is_not_misinterpreted_as_a_perimeter_bank(self):
  b,f=self.fixture();pad=next(iter(f.Pads()));pad.SetPosition(self.xy(23,18.25))
  plans,rejected=self.plan(b);self.assertTrue(any('Multiple pad rows' in reason for reason in rejected))
 def test_auto_pitch_fits_vias_and_preserves_native_pitch(self):
  b,f=self.fixture();plans,rejected=self.plan(b,spread_pitch=0);self.assertFalse(rejected)
  end=sorted(p.ToMM(plan.end.y) for plan in plans if int(plan.pad.GetNumber())<=8)
  self.assertTrue(all(z-a>=.6 for a,z in zip(end,end[1:])))
 def test_selected_subset_keeps_full_bank_geometry(self):
  b,f=self.fixture();all_plans,rejected=self.plan(b);self.assertFalse(rejected)
  expected={plan.pad.GetNumber():[(v.x,v.y) for v in plan.path] for plan in all_plans}
  selected={'2','4','7'}
  for pad in f.Pads():
   if pad.GetNumber() in selected:pad.SetSelected()
  plans,rejected=self.plan(b,scope='Selected pads');self.assertFalse(rejected)
  self.assertEqual({plan.pad.GetNumber() for plan in plans},selected)
  for plan in plans:self.assertEqual([(v.x,v.y) for v in plan.path],expected[plan.pad.GetNumber()])
 def test_group_filter_keeps_full_bank_ordering(self):
  b,f=self.fixture();baseline,rejected=self.plan(b);self.assertFalse(rejected)
  expected={plan.pad.GetNumber():[(v.x,v.y) for v in plan.path] for plan in baseline}
  plans,rejected=self.plan(b,groups=[{'name':'Subset','match':{'pad':'2,4,7'},'settings':{}}],unmatched='skip')
  self.assertEqual(len(plans),3)
  for plan in plans:
   self.assertEqual(plan.group_name,'Subset');self.assertEqual([(v.x,v.y) for v in plan.path],expected[plan.pad.GetNumber()])
 def test_arbitrary_rotation_preserves_package_relative_45_bends(self):
  from wayricad_runtime.perimeter_escape import path
  from wayricad_runtime.routing import FanoutPlanner
  b,f=self.fixture(rotation=37)
  plans,rejected=self.plan(b);self.assertFalse(rejected);self.assertEqual(len(plans),16)
  settings=dict(FanoutPlanner.defaults,spread_pitch=.8,width=.15,clearance=.1,via_diameter=.5)
  angle=math.radians(37)
  for pad in f.Pads():
   points=path(f,pad,p,settings)
   self.assertLessEqual(abs(points[0].x-pad.GetPosition().x),1)
   self.assertLessEqual(abs(points[0].y-pad.GetPosition().y),1)
   for a,z in zip(points,points[1:]):
    dx,dy=z.x-a.x,z.y-a.y
    x,y=abs(dx*math.cos(angle)-dy*math.sin(angle)),abs(dx*math.sin(angle)+dy*math.cos(angle))
    self.assertTrue(min(x,y)<=2 or abs(x-y)<=2)
if __name__=='__main__':unittest.main()
