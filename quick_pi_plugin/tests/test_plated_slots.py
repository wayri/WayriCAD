"""Analytical slot barrels and native rotated-slot contact/mesh acceptance."""
import importlib.util
import math
import unittest
import numpy as np
from quick_pi_plugin.barrel import barrel_area_mm2,drill_dimensions
from quick_pi_plugin.solver import solve,SolverError
from quick_pi_plugin.tests.test_solver import strip,combine


class PlatedSlotTests(unittest.TestCase):
    def test_area_matches_difference_of_expanded_capsules(self):
        def capsule_area(x,y):return min(x,y)*abs(x-y)+math.pi*min(x,y)**2/4
        for dims in ((.8,2.4),(2.4,.8),(.8,.8)):
            with self.subTest(dimensions=dims):
                t=.025
                expected=capsule_area(dims[0]+2*t,dims[1]+2*t)-capsule_area(*dims)
                self.assertAlmostEqual(barrel_area_mm2({'drill_size_mm':list(dims)},t),expected,places=14)
        self.assertAlmostEqual(barrel_area_mm2({'drill_mm':.8},.025),math.pi*((.8/2+.025)**2-(.8/2)**2),places=14)

    def test_slot_series_resistance_density_and_joule_energy(self):
        a,source,top=strip();b,bottom,sink=strip(z=1.6);mesh,n=combine(a,b)
        mesh['vias']=[{'id':'slot','top_nodes':top,'bottom_nodes':[i+n for i in bottom],
            'length_mm':1.6,'drill_mm':.8,'drill_size_mm':[2.4,.8],'drill_shape':'obround','plating_mm':.025}]
        result=solve(mesh,source,[i+n for i in sink],sink_current=2)
        # Independent outer-minus-inner stadium area, in square metres.
        area=((.85*1.6+math.pi*.85**2/4)-(.8*1.6+math.pi*.8**2/4))*1e-6
        barrel_r=1.724e-8*.0016/area
        strip_r=1.724e-8*.01/(.001*.000035)
        self.assertAlmostEqual(result['drop_over_current_ohm'],2*strip_r+barrel_r,places=12)
        self.assertAlmostEqual(result['vias'][0]['power_W'],4*barrel_r,places=12)
        self.assertAlmostEqual(result['vias'][0]['current_density_A_mm2'],2/(area*1e6),places=9)
        self.assertLess(result['current_balance_error_A'],1e-10)
        self.assertLess(result['energy_relative_error'],1e-10)

    def test_invalid_shapes_and_dimensions_are_not_substituted(self):
        for record in ({'drill_size_mm':[1,2],'drill_shape':'circle'},
                       {'drill_size_mm':[1,2],'drill_shape':'rectangle'},
                       {'drill_size_mm':[1,float('nan')]},{'drill_size_mm':[True,1]},
                       {'drill_mm':.5,'drill_size_mm':[1,2]}):
            with self.subTest(record=record),self.assertRaises(ValueError):drill_dimensions(record)
        for t in (0,-1,True,float('inf')):
            with self.subTest(plating=t),self.assertRaises(ValueError):barrel_area_mm2({'drill_mm':1},t)

    def test_full3d_rejects_slots_before_loading_gmsh(self):
        from quick_pi_plugin.full3d import build_volume_mesh,VolumeModelError
        with self.assertRaisesRegex(VolumeModelError,'2.5D'):
            build_volume_mesh({'vias':[{'drill_mm':.8,'drill_size_mm':[2.4,.8]}]})


try:import pcbnew as p
except ImportError:p=None


@unittest.skipIf(p is None or importlib.util.find_spec('vtkmodules') is None,'Native KiCad and VTK required')
class NativeSlotTests(unittest.TestCase):
    def test_rotated_native_holes_mesh_contacts_and_barrel_conservation(self):
        from quick_pi_plugin.board_geometry import extract
        from quick_pi_plugin.mesh import build_mesh,contains
        point=lambda x,y:p.VECTOR2I(p.FromMM(x),p.FromMM(y))
        for angle in (0,45,90):
            with self.subTest(angle=angle):
                board=p.BOARD();net=p.NETINFO_ITEM(board,'RAIL');board.Add(net)
                for layer in (p.F_Cu,p.B_Cu):
                    poly=p.SHAPE_POLY_SET();poly.NewOutline()
                    for x,y in ((0,0),(10,0),(10,10),(0,10)):poly.Append(p.FromMM(x),p.FromMM(y))
                    zone=p.ZONE(board);zone.SetLayer(layer);zone.SetNet(net);zone.Outline().Append(poly)
                    zone.SetFilledPolysList(layer,poly);zone.SetIsFilled(True);board.Add(zone)
                fp=p.FOOTPRINT(board);fp.SetReference('J1');board.Add(fp)
                pad=p.PAD(fp);pad.SetNumber('1');pad.SetNet(net);pad.SetAttribute(p.PAD_ATTRIB_PTH)
                pad.SetShape(p.PAD_SHAPE_OVAL);pad.SetSize(point(3,1.6));pad.SetPosition(point(5,5))
                pad.SetDrillShape(p.PAD_DRILL_SHAPE_OBLONG);pad.SetDrillSize(point(2.4,.8))
                pad.SetLayerSet(p.LSET.AllCuMask());pad.SetOrientationDegrees(angle);fp.Add(pad)
                override=[{'id':p.F_Cu,'z_mm':.0175,'thickness_mm':.035},
                          {'id':p.B_Cu,'z_mm':1.5825,'thickness_mm':.035}]
                geometry=extract(board,'RAIL',stackup_override=override)
                barrel=geometry['vias'][0]
                self.assertEqual(barrel['drill_size_mm'],[2.4,.8]);self.assertEqual(barrel['drill_shape'],'obround')
                self.assertAlmostEqual(barrel['drill_angle_deg'],angle)
                for layer in geometry['layers']:self.assertFalse(contains([[5,5]],layer['polygons'])[0])
                mesh=build_mesh(geometry,edge_mm=1,backend='vtk');points=np.array(mesh['points_mm'])
                self.assertEqual(mesh['vias'][0]['drill_size_mm'],[2.4,.8])
                source=np.flatnonzero((abs(points[:,0])<1e-8)&(abs(points[:,2]-.0175)<1e-8)).tolist()
                sink=np.flatnonzero((abs(points[:,0]-10)<1e-8)&(abs(points[:,2]-1.5825)<1e-8)).tolist()
                result=solve(mesh,source,sink,sink_current=1)
                expected=1.724e-8*.001565/barrel_area_mm2(barrel,.025)/1e-6
                self.assertAlmostEqual(result['vias'][0]['current_A'],1,places=8)
                self.assertAlmostEqual(result['vias'][0]['power_W'],expected,places=10)
                self.assertLess(result['energy_relative_error'],1e-6)


if __name__=='__main__':unittest.main()
