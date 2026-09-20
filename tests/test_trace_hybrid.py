"""Topology and model regressions; native geometry cases run in KiCad Python."""
import importlib.util
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'trace_impedance_plugin'


def load(name):
    spec = importlib.util.spec_from_file_location('_test_hybrid_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


measurement, model, copper = load('measurement'), load('rlc_model'), load('copper_path')
try:
    import pcbnew as pcb
except ImportError:
    pcb = None


class PureModels(unittest.TestCase):
    def test_invalid_frequency_rejected_before_board_access(self):
        engine = measurement.TraceMeasurementEngine(None)
        for frequency in (float('nan'), float('inf'), -1):
            with self.assertRaises(ValueError):
                engine.measure('N', 'A.1', 'B.1', frequency)
            with self.assertRaises(ValueError):
                engine.measure_zone('N', 'A.1', 'B.1', 'zone', frequency_mhz=frequency)

    def test_invalid_wide_line_never_becomes_near_zero_impedance(self):
        for solver in (model.z0_microstrip, model.z0_stripline_symmetric):
            with self.assertRaises(ValueError):
                solver(20, .1, .035, 4.5)
        self.assertTrue(all(z > 0 for _, z in model.z0_width_sweep(.1, .035, 4.5)))

    def test_barrel_r_and_l_scale_and_capacitance_is_unknown(self):
        short, long = model.via_barrel(.8,.3), model.via_barrel(1.6,.3)
        self.assertAlmostEqual(long['resistance_ohm'],2*short['resistance_ohm'])
        self.assertGreater(long['inductance_nh'],short['inductance_nh'])
        self.assertIsNone(long['capacitance_pf'])

    def test_ground_name_is_a_candidate_heuristic(self):
        for name in ('GND','/Power/AGND','DGND_1','VSS'):
            self.assertTrue(copper.ground_name(name))
        self.assertFalse(copper.ground_name('BACKGROUND'))

    def test_disconnected_report_has_unknown_totals(self):
        r = measurement.PathMeasurement('N','A.1','B.1').as_report()
        self.assertIsNone(r['resistance_ohm'])
        self.assertIsNone(r['impedance_ohm'])
        self.assertFalse(r['totals_complete'])


@unittest.skipIf(pcb is None, 'Requires native KiCad Python')
class NativeCopper(unittest.TestCase):
    def setUp(self):
        self.board = pcb.BOARD()
        self.net = pcb.NETINFO_ITEM(self.board, 'SIGNAL', 1)
        self.ground = pcb.NETINFO_ITEM(self.board, 'GND', 2)
        self.board.Add(self.net)
        self.board.Add(self.ground)

    def pos(self, x, y):
        return pcb.VECTOR2I(round(x*1e6),round(y*1e6))

    def pad(self, ref, x, y, layer=0):
        fp = pcb.FOOTPRINT(self.board)
        fp.SetReference(ref)
        self.board.Add(fp)
        pad = pcb.PAD(fp)
        pad.SetNumber('1')
        pad.SetAttribute(pcb.PAD_ATTRIB_SMD)
        layers = pcb.LSET()
        layers.AddLayer(layer)
        pad.SetLayerSet(layers)
        pad.SetShape(pcb.PAD_SHAPE_CIRCLE)
        pad.SetSize(self.pos(.4,.4))
        pad.SetPosition(self.pos(x,y))
        pad.SetNet(self.net)
        fp.Add(pad)
        return pad

    def track(self, a, b, layer=0):
        item = pcb.PCB_TRACK(self.board)
        item.SetStart(self.pos(*a)); item.SetEnd(self.pos(*b))
        item.SetWidth(pcb.FromMM(.2)); item.SetLayer(layer); item.SetNet(self.net)
        self.board.Add(item)
        return item

    def zone(self, corners, layer=0, ground=False, holes=()):
        zone = pcb.ZONE(self.board)
        zone.SetLayer(layer); zone.SetNet(self.ground if ground else self.net)
        poly = pcb.SHAPE_POLY_SET()
        def chain(points):
            c = pcb.SHAPE_LINE_CHAIN()
            for xy in points: c.Append(self.pos(*xy))
            c.SetClosed(True)
            return c
        poly.AddOutline(chain(corners))
        for hole in holes: poly.AddHole(chain(hole),0)
        zone.SetFilledPolysList(layer,poly)
        zone.SetIsFilled(True)
        self.board.Add(zone)
        return zone

    def engine(self):
        engine = measurement.TraceMeasurementEngine(self.board)
        # The in-memory fixture has no saved Board Setup stackup. Supply its
        # explicit test geometry instead of relying on production defaults.
        engine._stackup_cache = [
            measurement.StackupLayer('F.Cu', 'copper', .035),
            measurement.StackupLayer('dielectric 1', 'core', .2, .2, 4.2),
            measurement.StackupLayer('B.Cu', 'copper', .035),
        ]
        return engine

    def test_disconnected_pad_cannot_teleport_to_nearest_track(self):
        self.pad('A',0,0); self.pad('B',10,0)
        self.track((1,0),(10,0))
        self.assertEqual(self.engine().measure('SIGNAL','A.1','B.1').status,'disconnected')

    def test_cross_layer_coincident_endpoints_require_a_via(self):
        self.pad('A',0,0); self.pad('B',10,0,pcb.B_Cu)
        self.track((0,0),(5,0)); self.track((5,0),(10,0),pcb.B_Cu)
        self.assertEqual(self.engine().measure('SIGNAL','A.1','B.1').status,'disconnected')
        via = pcb.PCB_VIA(self.board)
        via.SetPosition(self.pos(5,0)); via.SetWidth(pcb.FromMM(.6)); via.SetDrill(pcb.FromMM(.3))
        via.SetLayerPair(pcb.F_Cu,pcb.B_Cu); via.SetNet(self.net); self.board.Add(via)
        result = self.engine().measure('SIGNAL','A.1','B.1')
        self.assertEqual(result.via_count,1)
        self.assertEqual(result.layer_changes,1)
        self.assertGreater(result.length_mm,10)
        self.assertGreater(result.resistance_ohm,0)
        reverse = self.engine().measure('SIGNAL','B.1','A.1')
        self.assertEqual(reverse.layer_changes,1)
        self.assertAlmostEqual(reverse.resistance_ohm,result.resistance_ohm)

    def test_zone_hole_does_not_become_a_direct_copper_shortcut(self):
        self.pad('A',1,5); self.pad('B',9,5)
        self.zone([(0,0),(10,0),(10,10),(0,10)],holes=[[(4,4),(6,4),(6,6),(4,6)]])
        e=self.engine(); z=e.zone_options('SIGNAL')[0]
        self.assertAlmostEqual(z['area_mm2'],96)
        result=e.measure_zone('SIGNAL','A.1','B.1',z['id'])
        self.assertNotEqual(result.status,'disconnected')
        self.assertGreater(result.length_mm,8)
        self.assertGreater(len(result.segments),1)
        g=e._geometry();island=g.islands[0]
        for section in result.segments:
            a=tuple(round(v*1e6) for v in section['start_mm'])
            b=tuple(round(v*1e6) for v in section['end_mm'])
            self.assertTrue(g.fits(island,a,b,.2,routing=True))

    def test_arc_traversal_preserves_actual_circular_length(self):
        self.pad('A',0,0);self.pad('B',10,0)
        arc=pcb.PCB_ARC(self.board)
        arc.SetStart(self.pos(0,0));arc.SetMid(self.pos(5,5));arc.SetEnd(self.pos(10,0))
        arc.SetWidth(pcb.FromMM(.2));arc.SetLayer(pcb.F_Cu);arc.SetNet(self.net);self.board.Add(arc)
        result=self.engine().measure('SIGNAL','A.1','B.1')
        self.assertEqual(result.track_count,1)
        self.assertAlmostEqual(result.length_mm,math.pi*5,places=5)
        self.assertTrue(all(s['geometry'].startswith('arc') for s in result.segments))

    def test_island_with_more_than_128_contacts_remains_measurable(self):
        for i in range(150):self.pad('P'+str(i),1+i*.2,1)
        self.zone([(0,0),(32,0),(32,2),(0,2)])
        result=self.engine().measure('SIGNAL','P0.1','P149.1')
        self.assertNotEqual(result.status,'disconnected')
        self.assertGreater(result.zone_count,0)
        self.assertGreater(result.length_mm,0)

    def test_thermal_spoke_connects_through_actual_pad_copper(self):
        self.pad('A',1,5);self.pad('B',9,5)
        zone=self.zone([(0,0),(10,0),(10,10),(0,10)],holes=[[(.5,4.5),(1.5,4.5),(1.5,5.5),(.5,5.5)]])
        g=self.engine()._geometry()
        filled=pcb.SHAPE_POLY_SET(zone.GetFilledPolysList(pcb.F_Cu))
        spoke=g.polygon([(1100000,4850000),(1600000,4850000),(1600000,5150000),(1100000,5150000)])
        filled.BooleanAdd(spoke);zone.SetFilledPolysList(pcb.F_Cu,filled)
        result=self.engine().measure('SIGNAL','A.1','B.1')
        self.assertNotEqual(result.status,'disconnected')
        self.assertGreater(result.zone_count,0)

    def test_pad_isolated_inside_zone_void_stays_disconnected(self):
        self.pad('A',1,5);self.pad('B',9,5)
        self.zone([(0,0),(10,0),(10,10),(0,10)],holes=[[(.5,4.5),(1.5,4.5),(1.5,5.5),(.5,5.5)]])
        self.assertEqual(self.engine().measure('SIGNAL','A.1','B.1').status,'disconnected')

    def test_split_islands_do_not_connect(self):
        self.pad('A',1,1); self.pad('B',9,1)
        self.zone([(0,0),(2,0),(2,2),(0,2)])
        self.zone([(8,0),(10,0),(10,2),(8,2)])
        self.assertEqual(self.engine().measure('SIGNAL','A.1','B.1').status,'disconnected')

    def test_hybrid_path_uses_tracks_and_a_finite_zone_corridor(self):
        self.pad('A',0,1); self.pad('B',10,1)
        self.track((0,1),(3,1)); self.track((7,1),(10,1))
        self.zone([(2,0),(8,0),(8,2),(2,2)])
        self.zone([(-1,-1),(11,-1),(11,3),(-1,3)],pcb.B_Cu,True)
        r=self.engine().measure('SIGNAL','A.1','B.1')
        self.assertEqual((r.track_count,r.zone_count,r.via_count),(2,1,0))
        self.assertAlmostEqual(r.length_mm,10)
        self.assertGreater(r.inductance_nh,0)
        self.assertGreater(r.capacitance_pf,0)
        self.assertFalse(r.impedance_valid)
        self.assertEqual(r.ground_nets,['GND'])

    def test_full_island_capacitance_uses_overlap_not_bbox(self):
        self.pad('A',2,1); self.pad('B',8,1)
        self.zone([(0,0),(10,0),(10,2),(0,2)])
        self.zone([(1,-1),(9,-1),(9,3),(1,3)],pcb.B_Cu,True)
        e=self.engine(); z=e.zone_options('SIGNAL')[0]
        r=e.measure_zone('SIGNAL','A.1','B.1',z['id'],corridor_width_mm=.2)
        self.assertAlmostEqual(r.overlap_area_mm2,16)
        self.assertAlmostEqual(r.zone_area_mm2,20)
        self.assertIsNone(r.as_report()['impedance_ohm'])
        expected=model.EPS0*4.2*16e-6/.0002*1e12
        self.assertAlmostEqual(r.capacitance_pf,expected)


if __name__ == '__main__':
    unittest.main()
