"""Geometry and bounded placement regression checks, independent of KiCad."""
from dataclasses import replace
import math
import unittest

from component_arranger_plugin import engine as e


def rectangle(w=1.0,h=1.0):
    return ((-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2))


def part(key,x=0,y=0,w=1,h=1,**kwargs):
    return e.Footprint(key,key,x,y,courtyards=(rectangle(w,h),),**kwargs)


class GeometryTests(unittest.TestCase):
    def test_bottom_and_rotation_transform(self):
        fp=part('U1',10,20,angle=90,side='bottom')
        self.assertAlmostEqual(e.transform((1,2),fp)[0],8)
        self.assertAlmostEqual(e.transform((1,2),fp)[1],19)
        fp=replace(fp,side='top')
        self.assertAlmostEqual(e.transform((1,2),fp)[1],21)

    def test_rotated_polygons_not_only_bbox(self):
        a=((0,0),(2,0),(0,2))
        b=((2,2),(2,.5),(.5,2))
        self.assertFalse(e.polygons_conflict(a,b))
        self.assertTrue(e.polygons_conflict(a,b,.4))
        self.assertTrue(e.polygons_conflict(a,((1,1),(2,1),(1,2))))

    def test_crossing_containment_and_clearance(self):
        self.assertTrue(e.polygons_conflict(rectangle(4,1),rectangle(1,4)))
        self.assertTrue(e.polygons_conflict(rectangle(4,4),rectangle()))
        self.assertTrue(e.polygons_conflict(rectangle(),((.5,-.5),(1.5,-.5),(1.5,.5),(.5,.5))))
        self.assertFalse(e.polygons_conflict(rectangle(),((.7,-.5),(1.7,-.5),(1.7,.5),(.7,.5)),.19))
        self.assertTrue(e.polygons_conflict(rectangle(),((.7,-.5),(1.7,-.5),(1.7,.5),(.7,.5)),.21))

    def test_side_and_through_hole_exclusion(self):
        a=part('A',0,0)
        b=part('B',0,0,side='bottom')
        settings=e.Settings('A',(-10,-10,10,10))
        self.assertTrue(e.legal(a,(b,),settings))
        self.assertFalse(e.legal(a,(replace(b,through_hole=True),),settings))
        self.assertFalse(e.legal(replace(a,through_hole=True),(b,),settings))

    def test_concave_boundary_endpoint_test_insufficient(self):
        outline=((0,0),(6,0),(6,6),(4,6),(4,2),(2,2),(2,6),(0,6))
        # Both ends of the long rectangle lie inside lobes; middle bridges cutout.
        fp=part('U1',3,4,w=5,h=1)
        self.assertFalse(e.legal(fp,(),e.Settings('U1',(-1,-1,7,7)),board_outline=outline))

    def test_holes_obstacles_and_routing_margin(self):
        fp=part('U1',0,0,routing_margin=.2)
        settings=e.Settings('U1',(-4,-4,4,4))
        self.assertFalse(e.legal(fp,(),settings,board_holes=(rectangle(.3,.3),)))
        self.assertFalse(e.legal(fp,(),settings,obstacles=(e.Obstacle(rectangle()),)))
        self.assertTrue(e.legal(fp,(),settings,obstacles=(e.Obstacle(rectangle(),('bottom',)),)))
        self.assertFalse(e.legal(fp,(),replace(settings,area=(-.6,-.6,.6,.6))))

    def test_malformed_geometry_rejected(self):
        fp=part('U1')
        settings=e.Settings('U1',(-5,-5,5,5))
        for bad in (replace(fp,courtyards=()),replace(fp,courtyards=(((0,0),(1,1),(0,1),(1,0)),)),replace(fp,x=math.nan)):
            with self.assertRaises(ValueError): e.arrange((bad,),settings)
        with self.assertRaises(ValueError):
            e.arrange((fp,),settings,obstacles=(e.Obstacle(rectangle(),('invalid',)),))
        for bad in (replace(settings,density=0),replace(settings,max_candidates=True),replace(settings,allowed_sides=('inner',)),replace(settings,allowed_angles=())):
            with self.assertRaises(ValueError): e.arrange((fp,),bad)


class CapacitorTests(unittest.TestCase):
    def test_explicit_units_and_fuzzy_metadata(self):
        for text in ('100n','0.1uF','100000pF','1e-7 F','100 nF 16V X7R','0u1','100nF +/-10%'):
            self.assertAlmostEqual(e.parse_capacitance(text),1e-7,places=15,msg=text)
        self.assertAlmostEqual(e.parse_capacitance('4n7'),4.7e-9,places=15)
        self.assertIsNone(e.parse_capacitance('104'))
        self.assertAlmostEqual(e.parse_capacitance('104',allow_code=True),1e-7,places=15)
        for text in ('100','0F','-1uF','not a capacitor','10V'):
            self.assertIsNone(e.parse_capacitance(text),text)
        fp=part('C1',fields={'Capacitor marking':'104'})
        self.assertAlmostEqual(e.capacitance(fp),1e-7,places=15)

    def test_unicode_micro_units(self):
        self.assertAlmostEqual(e.parse_capacitance('0.1\u00b5F'), 1e-7, places=15)
        self.assertAlmostEqual(e.parse_capacitance('0.1\u03bcF'), 1e-7, places=15)

    def test_normalized_fields_and_ambiguous_values(self):
        for name in ('capacitance value','Nominal_Capacitance','Cap Value',
                     'C_VALUE','Component.Value'):
            fp=part('C1',fields={name:'100nF 25V X7R'})
            self.assertAlmostEqual(e.capacitance(fp),1e-7,places=15)
        self.assertIsNone(e.parse_capacitance('10uF/100nF'))
        self.assertIsNone(e.parse_capacitance('100nF or 0.1uF'))
        self.assertIsNone(e.capacitance(part('C1',fields={'Value':'100nF','Capacitance':'1uF'})))
        self.assertIsNone(e.capacitance(part('C1',fields={'Value':'100nF/1uF','Cap Value':'100nF'})))
        self.assertAlmostEqual(e.capacitance(part('C1',fields={'Value':'100nF','Cap Value':'0.1uF'})),1e-7,places=15)
        self.assertIsNone(e.capacitance(part('C1',fields={'Value':'104'})))
        self.assertAlmostEqual(e.capacitance(part('C1',fields={'EIA code':'104'})),1e-7,places=15)

    def test_nearest_pad_distance_order_metric(self):
        anchor=part('U1',pads=(e.Pad('1','VDD',0,0),))
        small=part('C1',4,0,fields={'Value':'1nF'},pads=(e.Pad('1','VDD',-.5,0),))
        large=part('C2',2,0,fields={'Value':'1uF'},pads=(e.Pad('1','VDD',-.5,0),))
        settings=e.Settings('U1',(-8,-8,8,8))
        m=e.metrics((anchor,small,large),settings)
        self.assertEqual(m.capacitor_order_violations,1)
        self.assertAlmostEqual(m.capacitor_distance_mm,5)
        self.assertEqual(e.metrics((anchor,replace(small,x=2),replace(large,x=4)),settings).capacitor_order_violations,0)

    def test_override_and_unknown(self):
        anchor=part('U1',pads=(e.Pad('3','PWR_CUSTOM',0,0),))
        cap=part('C1',2,0,fields={'Value':'unknown'},pads=(e.Pad('1','PWR_CUSTOM',0,0),))
        settings=e.Settings('U1',(-6,-6,6,6),capacitor_targets={'C1':'3'},max_candidates=80)
        result=e.arrange((anchor,cap),settings)
        self.assertTrue(result.complete)
        self.assertTrue(any('unknown' in w for w in result.warnings))
        with self.assertRaises(ValueError): e.arrange((anchor,cap),replace(settings,capacitor_targets={'C1':'99'}))
        mismatched=replace(cap,pads=(e.Pad('1','OTHER',0,0),))
        with self.assertRaisesRegex(ValueError,'shared power pin'):
            e.arrange((anchor,mismatched),settings)
        empty=replace(anchor,pads=(e.Pad('3','',0,0),))
        with self.assertRaisesRegex(ValueError,'shared power pin'):
            e.arrange((empty,cap),settings)



class SearchTests(unittest.TestCase):
    def test_mst_known_length_and_crossings(self):
        fps=(part('A',0,0,pads=(e.Pad('1','N',0,0),)),part('B',3,0,pads=(e.Pad('1','N',0,0),)),part('C',3,4,pads=(e.Pad('1','N',0,0),)))
        self.assertAlmostEqual(e.metrics(fps).length_mm,7)
        fps=(part('A',0,0,pads=(e.Pad('1','N',0,0),)),part('B',2,2,pads=(e.Pad('1','N',0,0),)),part('C',0,2,pads=(e.Pad('1','M',0,0),)),part('D',2,0,pads=(e.Pad('1','M',0,0),)))
        self.assertEqual(e.metrics(fps).crossings,1)

    def test_external_endpoints_score(self):
        fp=part('A',0,0,pads=(e.Pad('1','N',0,0),))
        settings=e.Settings('A',(-2,-2,2,2),external_pads=(e.Pad('ext','N',30,40),))
        self.assertAlmostEqual(e.metrics((fp,),settings).length_mm,50)

    def test_fixed_anchor_legal_deterministic_length_improvement(self):
        a=part('U1',pads=(e.Pad('1','N',0,0),))
        b=part('R1',7,0,pads=(e.Pad('1','N',0,0),))
        settings=e.Settings('U1',(-8,-8,8,8),max_candidates=300,grid_mm=1)
        result=e.arrange((a,b),settings)
        self.assertTrue(result.complete)
        self.assertEqual(result.footprints[0],a)
        self.assertLess(result.after.length_mm,result.before.length_mm)
        self.assertEqual(result,e.arrange((a,b),settings))
        self.assertLessEqual(result.evaluations,300)
        self.assertTrue(all(e.legal(p,result.footprints,settings) for p in result.footprints))

    def test_locked_preserved_and_infeasible_original_retained(self):
        a=part('U1')
        b=part('R1',3,0,locked=True)
        settings=e.Settings('U1',(-5,-5,5,5),max_candidates=100)
        result=e.arrange((a,b),settings)
        self.assertEqual(result.footprints,(a,b))
        bad=e.arrange((a,replace(b,x=0)),settings)
        self.assertFalse(bad.complete)
        self.assertEqual(bad.footprints,(a,replace(b,x=0)))

    def test_bottom_is_used_if_only_legal_option(self):
        a=part('U1',w=2,h=2)
        b=part('R1',0,0,w=2,h=2)
        settings=e.Settings('U1',(-1.1,-1.1,1.1,1.1),allowed_sides=('top','bottom'),max_candidates=200,grid_mm=.1)
        result=e.arrange((a,b),settings)
        self.assertTrue(result.complete)
        self.assertEqual(result.footprints[1].side,'bottom')
        tht=e.arrange((replace(a,through_hole=True),b),settings)
        self.assertFalse(tht.complete)

    def test_rotation_and_requested_density_failure_reported(self):
        a=part('U1',0,0,w=.5,h=.5)
        b=part('R1',4,0,w=3,h=.5,routing_margin=.3)
        settings=e.Settings('U1',(-1,-4.5,1,4.5),allowed_angles=(90,),max_candidates=1000,grid_mm=.25,density=.95)
        result=e.arrange((a,b),settings)
        self.assertTrue(result.complete)
        self.assertEqual(result.footprints[1].angle,90)
        self.assertTrue(any('density' in w for w in result.warnings))
        self.assertTrue(e.legal(result.footprints[1],result.footprints,settings))

    def test_cap_order_restored_or_explicitly_incomplete(self):
        anchor=part('U1',pads=(e.Pad('1','VDD',0,0),))
        small=part('C1',4,0,fields={'Value':'1nF'},pads=(e.Pad('1','VDD',0,0),))
        large=part('C2',2,0,fields={'Value':'1uF'},pads=(e.Pad('1','VDD',0,0),))
        result=e.arrange((anchor,small,large),e.Settings('U1',(-6,-6,6,6),max_candidates=800,grid_mm=.5))
        self.assertTrue(result.complete)
        self.assertEqual(result.after.capacitor_order_violations,0)

    def test_crossing_reduction_is_measured(self):
        fps=(part('A',-3,-3,pads=(e.Pad('1','N',0,0),)),
             part('B',3,3,pads=(e.Pad('1','N',0,0),)),
             part('C',-3,3,pads=(e.Pad('1','M',0,0),)),
             part('D',3,-3,pads=(e.Pad('1','M',0,0),)))
        settings=e.Settings('A',(-5,-5,5,5),max_candidates=1200,grid_mm=1)
        result=e.arrange(fps,settings)
        self.assertTrue(result.complete)
        self.assertEqual(result.before.crossings,1)
        self.assertEqual(result.after.crossings,0)
        self.assertLess(result.after.length_mm,result.before.length_mm)

    def test_45_degree_policy_and_rotated_anchor_area(self):
        anchor=part('U1',angle=45,w=4,h=4)
        other=part('R1',7,0)
        area=e.suggested_area((anchor,other),'U1',density=1)
        self.assertTrue(e.legal(anchor,(),e.Settings('U1',area)))
        settings=e.Settings('U1',(-8,-8,8,8),allowed_angles=(45,),max_candidates=300)
        result=e.arrange((anchor,other),settings)
        self.assertTrue(result.complete)
        self.assertEqual(result.footprints[0],anchor)
        self.assertEqual(result.footprints[1].angle,45)

    def test_explicit_resource_limits_and_package_advisory(self):
        settings=e.Settings('U1',(-100,-100,100,100),max_candidates=20)
        with self.assertRaisesRegex(ValueError,'128'):
            e.arrange(tuple(part('U1' if i == 0 else str(i),i*2,0) for i in range(129)),settings)
        with self.assertRaisesRegex(ValueError,'512'):
            e.arrange((part('U1',pads=tuple(e.Pad(str(i),'N',0,0) for i in range(513))),),settings)
        result=e.arrange((part('U1',package='BGA'),),settings)
        self.assertTrue(any('pin escape' in w for w in result.warnings))

    def test_crossing_priority_cannot_be_traded_for_length(self):
        # A large crossingweight is not required: crossings are lexicographic.
        fps=(part('A',-3,-3,pads=(e.Pad('1','N',0,0),)),
             part('B',3,3,pads=(e.Pad('1','N',0,0),)),
             part('C',-3,3,pads=(e.Pad('1','M',0,0),)),
             part('D',3,-3,pads=(e.Pad('1','M',0,0),)))
        settings=e.Settings('A',(-5,-5,5,5),crossing_weight=0,max_candidates=1200)
        self.assertEqual(e.arrange(fps,settings).after.crossings,0)

    def test_density_target_changes_the_sampled_solution(self):
        anchor=part('U1',pads=(e.Pad('1','N',0,0),))
        other=part('R1',7,0,pads=(e.Pad('1','N',0,0),))
        settings=e.Settings('U1',(-10,-10,10,10),max_candidates=1200)
        loose=e.arrange((anchor,other),replace(settings,density=.2))
        dense=e.arrange((anchor,other),replace(settings,density=.7))
        self.assertTrue(loose.complete and dense.complete)
        self.assertLessEqual(abs(loose.achieved_density-.2),.05+e.EPS)
        self.assertLessEqual(abs(dense.achieved_density-.7),.05+e.EPS)
        self.assertLess(loose.achieved_density,dense.achieved_density)
        self.assertEqual(loose.after.crossings,dense.after.crossings)

    def test_spatial_coverage_with_six_parts_eight_angles_and_two_sides(self):
        data=[('U1',15,15,'IC'),('C1',23,20,'100n'),
              ('C2',11,9,'1u'),('C3',26,9,'10u'),
              ('R1',25,15,'10k'),('R2',10,21,'10k')]
        fps=tuple(part(ref,x,y,w=2,h=1.6,routing_margin=.45,
                       pads=(e.Pad('1','3V3',.6,.3),e.Pad('2','GND',-.6,-.3)),
                       fields={'Value':value}) for ref,x,y,value in data)
        settings=e.Settings('U1',(4,6,26,24),
                            allowed_angles=tuple(range(0,360,45)),
                            allowed_sides=('top','bottom'))
        result=e.arrange(fps,settings)
        self.assertTrue(result.complete,result.warnings)
        self.assertEqual(result.after.capacitor_order_violations,0)
        self.assertLess(result.after.length_mm,result.before.length_mm)
        self.assertLessEqual(result.evaluations,6000)
        self.assertTrue(all(e.legal(fp,result.footprints,settings)
                            for fp in result.footprints))

    def test_anchor_inference_and_area(self):
        a=part('U1',pads=(e.Pad('1','N',0,0),e.Pad('2','M',.2,.2)))
        b=part('R1',3,0,pads=(e.Pad('1','N',0,0),))
        c=part('R2',0,3,pads=(e.Pad('1','M',0,0),))
        self.assertEqual(e.infer_anchor((c,b,a)),'U1')
        area=e.suggested_area((a,b,c),'U1')
        self.assertEqual(area[0],-area[2])
        self.assertEqual(e.classify_package(replace(a,package='Package_BGA:BGA-256')),'BGA')


if __name__=='__main__':
    unittest.main()
