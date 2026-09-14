"""Real KiCad polygon extraction: holes, islands, contacts and explicit stackup."""
import json
import tempfile
from pathlib import Path
import unittest

try:
    import pcbnew as p
except ImportError:
    p=None


@unittest.skipIf(p is None,'Requires native KiCad 10 polygon geometry')
class BoardGeometryTests(unittest.TestCase):
    def setUp(self):
        from quick_pi_plugin.board_geometry import extract
        self.extract=extract;self.board=p.BOARD();self.net=p.NETINFO_ITEM(self.board,'VCC');self.board.Add(self.net)
        self.override=[{'id':p.F_Cu,'z_mm':.0175,'thickness_mm':.035},
                       {'id':p.B_Cu,'z_mm':1.5825,'thickness_mm':.035}]

    def point(self,x,y):return p.VECTOR2I(p.FromMM(x),p.FromMM(y))

    def rectangle(self,x0,y0,x1,y1):
        poly=p.SHAPE_POLY_SET();poly.NewOutline()
        for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1)):poly.Append(p.FromMM(x),p.FromMM(y))
        return poly

    def zone(self,poly,layer=None,filled=True):
        zone=p.ZONE(self.board);zone.SetLayer(p.F_Cu if layer is None else layer);zone.SetNet(self.net)
        zone.Outline().Append(poly)
        if filled:zone.SetFilledPolysList(zone.GetLayer(),poly);zone.SetIsFilled(True)
        self.board.Add(zone);return zone

    def pad(self,x,y,number='1',plated=False,drill=.8):
        fp=p.FOOTPRINT(self.board);fp.SetReference('J'+number);self.board.Add(fp)
        pad=p.PAD(fp);pad.SetNumber(number);pad.SetPosition(self.point(x,y));pad.SetSize(self.point(2,2));pad.SetNet(self.net)
        if plated:
            pad.SetAttribute(p.PAD_ATTRIB_PTH);pad.SetDrillSize(self.point(drill,drill));pad.SetLayerSet(p.LSET.AllCuMask())
        else:
            pad.SetAttribute(p.PAD_ATTRIB_SMD);layers=p.LSET();layers.AddLayer(p.F_Cu);pad.SetLayerSet(layers)
        fp.Add(pad);return pad

    def area(self,records):
        def ring(points):return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1])))/2
        return sum(ring(x['outer'])-sum(ring(h) for h in x['holes']) for x in records)

    def test_zone_voids_and_islands_survive_contact_partition(self):
        poly=self.rectangle(0,0,10,10);hole=poly.NewHole()
        for x,y in ((6,6),(6,8),(8,8),(8,6)):poly.Append(p.FromMM(x),p.FromMM(y),0,hole)
        poly.Append(self.rectangle(20,0,22,2));self.zone(poly)
        self.pad(2,2);self.pad(2.5,2,number='2')  # overlapping contacts must both become mesh boundaries
        result=self.extract(self.board,'VCC',stackup_override=self.override)
        layer=next(x for x in result['layers'] if x['id']==p.F_Cu)
        self.assertEqual(len(layer['polygons']),2)
        self.assertAlmostEqual(self.area(layer['polygons']),100,places=6)
        self.assertAlmostEqual(self.area(layer['mesh_regions']),100,places=6)
        self.assertGreater(len(layer['mesh_regions']),len(layer['polygons']))
        self.assertEqual(len(result['terminals']),2)
        json.dumps(result,allow_nan=False)

    def test_other_net_drill_is_removed_from_every_intersected_copper_layer(self):
        self.zone(self.rectangle(0,0,10,10));self.zone(self.rectangle(0,0,10,10),p.B_Cu)
        other=p.NETINFO_ITEM(self.board,'GND');self.board.Add(other)
        via=p.PCB_VIA(self.board);via.SetPosition(self.point(5,5));via.SetWidth(p.FromMM(2));via.SetDrill(p.FromMM(1))
        via.SetViaType(p.VIATYPE_THROUGH);via.SetLayerPair(p.F_Cu,p.B_Cu);via.SetNet(other);self.board.Add(via)
        result=self.extract(self.board,'VCC',stackup_override=self.override)
        self.assertEqual(result['vias'],[])
        for layer in result['layers']:
            self.assertEqual(len(layer['polygons'][0]['holes']),1)
            self.assertLess(self.area(layer['polygons']),100-.78)

    def test_plated_pad_and_via_have_actual_annular_contacts_and_span(self):
        pad=self.pad(3,3,plated=True)
        via=p.PCB_VIA(self.board);via.SetPosition(self.point(8,3));via.SetWidth(p.FromMM(1));via.SetDrill(p.FromMM(.4))
        via.SetViaType(p.VIATYPE_THROUGH);via.SetLayerPair(p.F_Cu,p.B_Cu);via.SetNet(self.net);self.board.Add(via)
        result=self.extract(self.board,'VCC',stackup_override=self.override)
        self.assertEqual({v['kind'] for v in result['vias']},{'plated_pad','via'})
        self.assertEqual(result['terminals'][0]['label'],'J1.1')
        for barrel in result['vias']:
            self.assertEqual(barrel['layers'],[p.F_Cu,p.B_Cu])
            self.assertTrue(all(polys[0]['holes'] for polys in barrel['polygons'].values()))

    def test_unfilled_zone_and_missing_stackup_fail_closed(self):
        self.zone(self.rectangle(0,0,10,10),filled=False)
        with self.assertRaisesRegex(ValueError,'stackup'):self.extract(self.board,'VCC')
        with self.assertRaisesRegex(ValueError,'unfilled'):self.extract(self.board,'VCC',stackup_override=self.override)

    def test_actual_saved_stackup_has_no_default_thickness_guess(self):
        from quick_pi_plugin.board_geometry import stackup
        source='''(kicad_pcb (setup (stackup
         (layer "F.Mask" (type "Top Solder Mask") (thickness .01))
         (layer "F.Cu" (type "copper") (thickness .07))
         (layer "dielectric 1" (type "core") (thickness 1.1))
         (layer "B.Cu" (type "copper") (thickness .035)))))'''
        layers=stackup(self.board,p,source)
        self.assertAlmostEqual(layers[0]['z_mm'],.035)
        self.assertAlmostEqual(layers[1]['z_mm'],1.1875)
        self.assertEqual(layers[0]['thickness_mm'],.07)
        with self.assertRaisesRegex(ValueError,'thickness'):
            stackup(self.board,p,source.replace('(thickness 1.1)',''))

    def test_close_disconnected_tracks_are_not_snapped_together(self):
        for start,end in (((0,0),(5,0)),((5.03,0),(10,0))):
            track=p.PCB_TRACK(self.board);track.SetStart(self.point(*start));track.SetEnd(self.point(*end))
            track.SetWidth(p.FromMM(.01));track.SetLayer(p.F_Cu);track.SetNet(self.net);self.board.Add(track)
        result=self.extract(self.board,'VCC',stackup_override=self.override,curve_tolerance_mm=.001)
        self.assertEqual(len(result['layers'][0]['polygons']),2)

    def test_arc_copper_is_extracted_from_native_curvature(self):
        arc=p.PCB_ARC(self.board);arc.SetStart(self.point(0,0));arc.SetMid(self.point(5,5));arc.SetEnd(self.point(10,0))
        arc.SetWidth(p.FromMM(.5));arc.SetLayer(p.F_Cu);arc.SetNet(self.net);self.board.Add(arc)
        result=self.extract(self.board,'VCC',stackup_override=self.override)
        self.assertEqual(result['counts']['arcs'],1)
        # A semicircle of radius 5 and width .5 has area about 7.85 mm²,
        # plus endpoint caps. A straight substitute would be about 5.2 mm².
        self.assertGreater(result['area_mm2'],7.5)
        self.assertLess(result['area_mm2'],8.2)


if __name__=='__main__':unittest.main()
