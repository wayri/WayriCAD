import unittest
import random

from signal_integrity_advisor_plugin.return_path.analysis import CopperSegment, ReferenceRegion, ReturnPathAnalyzer, ViaPoint


class ReturnPathScalingTests(unittest.TestCase):
    def test_indexed_point_membership_matches_unindexed_polygon_reference(self):
        from signal_integrity_advisor_plugin.return_path.analysis import _inside
        outline=((-5,-5),(5,-5),(5,5),(1,5),(1,1),(-1,1),(-1,5),(-5,5))
        holes=(((-3,-3),(-2,-3),(-2,-2),(-3,-2)),)
        region=ReferenceRegion('GND','In1.Cu',(-5,-5,5,5),outline,holes)
        rng=random.Random(47)
        points=[(rng.uniform(-6,6),rng.uniform(-6,6)) for _ in range(2000)]
        points.extend(outline+holes[0]+((0,-5),(1,3),(-2.5,-3)))
        for point in points:
            expected=_inside(point,outline) and not any(_inside(point,h) for h in holes)
            self.assertEqual(region.contains(point),expected,point)

    def test_spatial_filters_preserve_local_coverage_and_transition_results(self):
        segments=[CopperSegment('CLK','F.Cu',(0,0),(2,0),0.2)]
        regions=[ReferenceRegion('GND','In1.Cu',(-1,-1,3,1))]
        regions.extend(ReferenceRegion('GND','In1.Cu',(100+i,100,101+i,101)) for i in range(2000))
        vias=[ViaPoint('CLK',(0,0),('F.Cu','In1.Cu')),ViaPoint('GND',(1,0),('F.Cu','In1.Cu'))]
        vias.extend(ViaPoint('GND',(100+i,100),('F.Cu','In1.Cu')) for i in range(2000))
        result=ReturnPathAnalyzer().audit(segments,vias,regions,layer_order=('F.Cu','In1.Cu'))
        self.assertEqual([],result.findings)

    def test_region_bounds_rejection_preserves_hole_semantics(self):
        region=ReferenceRegion('GND','In1.Cu',(-5,-5,5,5),
            ((-5,-5),(5,-5),(5,5),(-5,5)),
            (((-.5,-.5),(.5,-.5),(.5,.5),(-.5,.5)),))
        covered=CopperSegment('SIG','F.Cu',(-4,2),(4,2),.2)
        split=CopperSegment('SIG','F.Cu',(-4,0),(4,0),.2)
        self.assertTrue(region.covers(covered))
        self.assertFalse(region.covers(split))

    def test_coupling_index_accounts_for_primary_trace_width(self):
        result=ReturnPathAnalyzer().audit([
            CopperSegment('BUS_P','F.Cu',(0,0),(5,0),4.0),
            CopperSegment('BUS_N','F.Cu',(0,2.4),(5,2.4),.2),
        ],[],[],differential_gap_limit_mm=.5,differential_skew_limit_mm=.5)
        self.assertNotIn('Differential-pair uncoupling',{finding.check for finding in result.findings})


if __name__=='__main__':unittest.main()
