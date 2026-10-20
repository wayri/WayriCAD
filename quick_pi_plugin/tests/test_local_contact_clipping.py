"""Native local drill clipping versus full-copper intersection, without rasterization."""
import random
import unittest
try:import pcbnew as p
except ImportError:p=None


@unittest.skipIf(p is None,'Native KiCad polygon engine required')
class LocalContactClippingTests(unittest.TestCase):
    def rectangle(self,x,y,w,h):
        result=p.SHAPE_POLY_SET();result.NewOutline()
        for a,b in ((x,y),(x+w,y),(x+w,y+h),(x,y+h)):
            result.Append(p.FromMM(a),p.FromMM(b))
        return result

    def assert_same_domain(self,a,b):
        difference=p.SHAPE_POLY_SET(a);difference.BooleanSubtract(b)
        reverse=p.SHAPE_POLY_SET(b);reverse.BooleanSubtract(a)
        self.assertAlmostEqual(difference.Area()/1e12,0.,places=8)
        self.assertAlmostEqual(reverse.Area()/1e12,0.,places=8)

    def test_index_preserves_nested_holes_islands_negative_coordinates_and_large_fallback(self):
        from quick_pi_plugin.board_geometry import _NativeContourIndex
        holes=self.rectangle(-100,-100,200,200)
        holes.BooleanSubtract(self.rectangle(-10,-10,20,20))
        holes.Append(self.rectangle(-2,-2,4,4));holes.Simplify()
        index=_NativeContourIndex(p,holes)
        self.assertTrue(index.large)
        for box in ((-3,-3,6,6),(-20,-20,40,40),(-150,-150,300,300),(200,200,1,1)):
            contact=self.rectangle(*box)
            expected=p.SHAPE_POLY_SET(contact);expected.BooleanSubtract(holes)
            self.assert_same_domain(index.subtract_from(contact),expected)
        # Copper inside a hole in the drilled union remains copper.
        surviving=index.subtract_from(self.rectangle(5,5,1,1))
        self.assertAlmostEqual(surviving.Area()/1e12,1.,12)

    def test_seeded_local_subtraction_matches_full_copper_intersection(self):
        from quick_pi_plugin.board_geometry import _NativeContourIndex,_partition
        rng=random.Random(717)
        for trial in range(12):
            contacts=[self.rectangle(rng.randrange(-10,100),rng.randrange(-10,100),
                                    rng.randrange(1,8),rng.randrange(1,8)) for _ in range(24)]
            copper=self.rectangle(0,0,100,100)
            for contact in contacts:copper.Append(contact)
            copper.Simplify()
            holes=p.SHAPE_POLY_SET()
            for _ in range(120):
                holes.Append(self.rectangle(rng.randrange(-12,105),rng.randrange(-12,105),
                                           rng.randrange(1,5),rng.randrange(1,5)))
            # A drilled union with an enclosed material island is not solid.
            ring=self.rectangle(30,30,12,12);ring.BooleanSubtract(self.rectangle(33,33,6,6))
            holes.Append(ring);holes.Simplify()
            copper.BooleanSubtract(holes);index=_NativeContourIndex(p,holes)
            old=[];new=[]
            for contact in contacts:
                full=p.SHAPE_POLY_SET(contact);full.BooleanIntersection(copper)
                local=index.subtract_from(contact);self.assert_same_domain(local,full)
                if full.OutlineCount():old.append(full)
                if local.OutlineCount():new.append(local)
            # Native Boolean operations may rotate the first vertex or retain
            # different redundant collinear vertices. Compare electrode
            # membership areas and prove no cell crosses any contact boundary.
            def membership(records):
                areas={}
                for record in records:
                    cell=p.SHAPE_POLY_SET();cell.NewOutline()
                    for x,y in record['outer']:cell.Append(p.FromMM(x),p.FromMM(y))
                    for ring in record['holes']:
                        hole=cell.NewHole()
                        for x,y in ring:cell.Append(p.FromMM(x),p.FromMM(y),0,hole)
                    area=cell.Area();signature=[]
                    for contact in contacts:
                        inside=p.SHAPE_POLY_SET(cell);inside.BooleanIntersection(contact)
                        part=inside.Area()
                        self.assertTrue(abs(part)<1 or abs(part-area)<1)
                        signature.append(part>0)
                    key=tuple(signature);areas[key]=areas.get(key,0)+area
                self.assertEqual(sum(areas.values()),copper.Area())
                return areas
            self.assertEqual(membership(_partition(p,copper,old,None)),membership(_partition(p,copper,new,None)))

    def test_rotated_slots_and_foreign_drill_update_shared_native_contacts_once(self):
        from quick_pi_plugin.board_geometry import extract
        from quick_pi_plugin.mesh import build_mesh,contains
        from quick_pi_plugin.solver import solve
        import numpy as np
        point=lambda x,y:p.VECTOR2I(p.FromMM(x),p.FromMM(y))
        for angle in (0,45,90):
            board=p.BOARD();net=p.NETINFO_ITEM(board,'RAIL');board.Add(net)
            for layer in (p.F_Cu,p.B_Cu):
                plane=self.rectangle(0,0,10,10)
                zone=p.ZONE(board);zone.SetLayer(layer);zone.SetNet(net);zone.Outline().Append(plane)
                zone.SetFilledPolysList(layer,plane);zone.SetIsFilled(True);board.Add(zone)
            fp=p.FOOTPRINT(board);fp.SetReference('J1');board.Add(fp)
            pad=p.PAD(fp);pad.SetNumber('1');pad.SetNet(net);pad.SetAttribute(p.PAD_ATTRIB_PTH)
            pad.SetShape(p.PAD_SHAPE_OVAL);pad.SetSize(point(3,1.6));pad.SetPosition(point(5,5))
            pad.SetDrillShape(p.PAD_DRILL_SHAPE_OBLONG);pad.SetDrillSize(point(2.4,.8))
            pad.SetLayerSet(p.LSET.AllCuMask());pad.SetOrientationDegrees(angle);fp.Add(pad)
            other=p.FOOTPRINT(board);other.SetReference('H1');board.Add(other)
            hole=p.PAD(other);hole.SetNumber('1');hole.SetAttribute(p.PAD_ATTRIB_NPTH)
            hole.SetShape(p.PAD_SHAPE_CIRCLE);hole.SetSize(point(.5,.5));hole.SetDrillSize(point(.5,.5))
            hole.SetPosition(point(5.7,5.7));hole.SetLayerSet(p.LSET.AllCuMask());other.Add(hole)
            override=[{'id':p.F_Cu,'z_mm':.0175,'thickness_mm':.035},
                      {'id':p.B_Cu,'z_mm':1.5825,'thickness_mm':.035}]
            geometry=extract(board,'RAIL',stackup_override=override)
            terminal=geometry['terminals'][0];barrel=geometry['vias'][0]
            for layer in (p.F_Cu,p.B_Cu):
                records=terminal['polygons'][str(layer)]
                self.assertIs(records,barrel['polygons'][str(layer)])
                self.assertFalse(contains([[5.7,5.7]],records)[0])
                self.assertFalse(contains([[5,5]],records)[0])
            mesh=build_mesh(geometry,edge_mm=1,backend='vtk');points=np.asarray(mesh['points_mm'])
            source=np.flatnonzero((abs(points[:,0])<1e-8)&(abs(points[:,2]-.0175)<1e-8)).tolist()
            sink=np.flatnonzero((abs(points[:,0]-10)<1e-8)&(abs(points[:,2]-1.5825)<1e-8)).tolist()
            result=solve(mesh,source,sink,sink_current=1)
            self.assertAlmostEqual(result['vias'][0]['current_A'],1.,8)
            self.assertLess(result['current_balance_error_A'],1e-8)
            self.assertLess(result['energy_relative_error'],1e-6)


if __name__=='__main__':unittest.main()
