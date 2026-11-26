"""Physical barrel span and residual geometry are not a broadband stub model."""
from types import SimpleNamespace
import unittest

from trace_impedance_plugin.copper_path import CopperGeometry, via_layers, routing_ambiguity
from trace_impedance_plugin.measurement import TraceMeasurementEngine, StackupLayer, PathMeasurement
from trace_impedance_plugin import bulk
from trace_impedance_plugin.frequency_analysis import sweep

try:
    import pcbnew
except ImportError:
    pcbnew = None


class Via:
    def __init__(self, top=0, bottom=6, micro=False):
        self.top, self.bottom, self.micro = top, bottom, micro
        self.m_Uuid = SimpleNamespace(AsString=lambda: 'via-a')
    def TopLayer(self):return self.top
    def BottomLayer(self):return self.bottom
    def GetViaType(self):return 1 if self.micro else 4
    def IsOnLayer(self, layer):return layer in (self.top,self.bottom)
    def GetPosition(self):return SimpleNamespace(x=0,y=0)
    def GetDrillValue(self):return 300000


def geometry():
    engine = TraceMeasurementEngine(None)
    names = {0:'F.Cu',2:'In1.Cu',4:'In2.Cu',6:'B.Cu'}
    engine._layer_name = names.__getitem__
    engine._stackup_cache = [StackupLayer('F.Cu','copper',.035),
        StackupLayer('D1','core',.1),StackupLayer('In1.Cu','copper',.035),
        StackupLayer('D2','core',.8),StackupLayer('In2.Cu','copper',.035),
        StackupLayer('D3','core',.2),StackupLayer('B.Cu','copper',.035)]
    g = object.__new__(CopperGeometry)
    g.layers = [0,2,4,6];g.engine = engine;g.notes = []
    g.pcb = SimpleNamespace(VIATYPE_MICROVIA=1,PCB_VIA=Via)
    engine._geometry_cache = g
    return g


class ViaGeometryTests(unittest.TestCase):
    def test_physical_span_ignores_unflashed_internal_annuli(self):
        self.assertEqual(via_layers(Via(),[0,2,4,6]),[0,2,4,6])

    def test_through_route_has_no_extension_but_stays_a_partial_via_model(self):
        g=geometry();length=g.engine.via_span_mm(0,6)
        result=g.via_evidence(dict(item=Via(),layer=0,end_layer=6,length_mm=length))
        self.assertAlmostEqual(length,1.205)
        self.assertEqual(result['via_type'],'through')
        self.assertEqual(result['remaining_barrel'],[])
        self.assertEqual(result['stub_status'],'no_extension_beyond_selected_span')

    def test_partial_through_route_separates_barrel_extension(self):
        g=geometry();used=g.engine.via_span_mm(0,2)
        result=g.via_evidence(dict(item=Via(),layer=0,end_layer=2,length_mm=used))
        self.assertAlmostEqual(used,.135)
        residual=result['remaining_barrel'][0]
        self.assertAlmostEqual(residual['length_mm'],1.07)
        self.assertEqual(residual['start_layer'],'In1.Cu')
        self.assertEqual(residual['termination'],'unverified_open_stub_or_connected_branch')
        for key in ('capacitance_pf','input_impedance_ohm','resonance_hz'):
            self.assertIsNone(residual[key])
        self.assertAlmostEqual(used+residual['length_mm'],result['physical_length_mm'])

    def test_blind_buried_microvia_and_reversed_traversal(self):
        g=geometry()
        for via,kind in ((Via(0,2),'blind'),(Via(2,4),'buried'),(Via(0,2,True),'microvia')):
            result=g.via_evidence(dict(item=via,layer=via.bottom,end_layer=via.top,
                length_mm=g.engine.via_span_mm(via.top,via.bottom)))
            self.assertEqual(result['via_type'],kind)
            self.assertEqual(result['remaining_barrel'],[])
            self.assertEqual(result['connected_path_span']['start_layer'],g.engine._layer_name(via.bottom))

    def test_internal_used_span_has_two_candidate_extensions(self):
        g=geometry()
        result=g.via_evidence(dict(item=Via(),layer=4,end_layer=2,length_mm=.835))
        self.assertEqual(len(result['remaining_barrel']),2)

    def test_bulk_barrel_slices_never_claim_unused_lengths_are_stubs(self):
        g=geometry();edges=list(bulk._edges(g.engine,g,Via()))
        self.assertEqual(len(edges),3)
        result=g.via_evidence(edges[0])
        self.assertEqual(result['stub_status'],'not_evaluated_without_terminal_path')
        self.assertIsNone(result['remaining_barrel'])
        self.assertAlmostEqual(sum(edge['length_mm'] for edge in edges),1.205)

    def test_missing_stackup_never_assumes_equal_layer_spacing(self):
        g=geometry();g.engine._stackup_cache[3].thickness_mm=0
        with self.assertRaisesRegex(ValueError,'equal layer spacing'):
            g.engine.via_span_mm(0,6)

    def test_backdrill_and_unknown_endpoints_rejected(self):
        via=Via();via.GetSecondaryDrillSize=lambda: .2
        with self.assertRaisesRegex(ValueError,'Backdrilled'):
            via_layers(via,[0,2,4,6])
        with self.assertRaisesRegex(ValueError,'physical span'):
            via_layers(Via(0,9),[0,2,4,6])

    def test_measurement_retains_stub_blocker_without_adding_residual_RL_in_series(self):
        g=geometry();used=g.engine.via_span_mm(0,2)
        edge=dict(item=Via(),kind='via',layer=0,end_layer=2,length_mm=used,drill_mm=.3,a=(0,0),b=(0,0))
        g.engine._screening_section=lambda *args: {}
        result=PathMeasurement('N','A','B')
        g.engine._measure_edges(result,[edge],100,'Auto')
        self.assertEqual(result.status,'partial')
        self.assertEqual(result.length_mm,used)
        self.assertIsNone(result.segments[0]['capacitance_pf'])
        self.assertIn('VIA_STUB_OR_BRANCH_UNMODELED',{b['code'] for b in result.blockers})
        self.assertTrue(any('remaining barrel' in note for note in result.notes))
        frequency=sweep(result.as_report(),points=2)
        self.assertEqual(frequency['status'],'PARTIAL')
        self.assertTrue(all(row['series_magnitude_ohm'] is None for row in frequency['rows']))

    def test_full_span_via_has_partial_inductance_but_no_loop_totals(self):
        g=geometry()
        edge=dict(item=Via(),kind='via',layer=0,end_layer=6,length_mm=g.engine.via_span_mm(0,6),
                  drill_mm=.3,a=(0,0),b=(0,0))
        g.engine._screening_section=lambda *args: {}
        result=PathMeasurement('N','A','B')
        g.engine._measure_edges(result,[edge],100,'Auto')
        path=result.as_report()
        inductance=path['quantity_coverage']['inductance_nh']
        self.assertGreater(path['inductance_nh'],0)
        self.assertEqual(inductance['isolated_via_partial_subtotal_nh'],path['inductance_nh'])
        self.assertIsNone(inductance['complete_total'])
        self.assertIsNone(path['quantity_coverage']['capacitance_pf']['modeled_subtotal'])
        self.assertEqual(result.as_dict()['C (pF)'],'Unavailable')
        self.assertIsNone(path['segments'][0]['return_loop_inductance_nh'])
        self.assertEqual(sweep(path,points=2)['status'],'PARTIAL')

    def test_sweep_withholds_reactance_when_modeled_tracks_have_an_unresolved_transition(self):
        tracks=[dict(kind='track',width_mm=.2,copper_thickness_mm=.035,length_mm=1,
                     resistance_ohm=.01,inductance_nh=1) for _ in range(2)]
        for path in (dict(status='partial',segments=tracks),
                     dict(segments=tracks,quantity_coverage={'inductance_nh':{'complete_total':None}})):
            result=sweep(path,points=2)
            self.assertEqual(result['status'],'PARTIAL')
            self.assertTrue(all(row['series_reactance_ohm'] is None for row in result['rows']))
            self.assertTrue(all(row['resistance_one_face_ohm'] > 0 for row in result['rows']))

    def test_branch_sweep_does_not_invent_series_channel_impedance(self):
        path={'route_topology':{'branched':True},'segments':[dict(kind='track',width_mm=.2,
            copper_thickness_mm=.035,length_mm=1,resistance_ohm=.01,inductance_nh=1)]}
        result=sweep(path,points=2)
        self.assertEqual(result['status'],'PARTIAL')
        self.assertTrue(all(row['series_reactance_ohm'] is None for row in result['rows']))


class TopologyTests(unittest.TestCase):
    def test_duplicate_endpoint_labels_do_not_join_disconnected_physical_pads(self):
        g=object.__new__(CopperGeometry)
        g.pads=lambda net: {'J1.1':[object(),object()],'J2.1':[object()]}
        route,notes=g.path('N','J1.1','J2.1')
        self.assertIsNone(route)
        self.assertIn('ambiguous',notes[0])
    def graph(self, links):
        graph={}
        for a,b in links:
            edge={'kind':'track','length_mm':1}
            graph.setdefault(a,[]).append((b,edge));graph.setdefault(b,[]).append((a,edge))
        return graph
    def test_linear_route_is_not_ambiguous(self):
        evidence=routing_ambiguity(self.graph([('a','b'),('b','c')]),'a')
        self.assertFalse(evidence['branched']);self.assertFalse(evidence['alternate_paths'])
    def test_branch_and_parallel_routes_are_explicit(self):
        self.assertTrue(routing_ambiguity(self.graph([('a','b'),('b','c'),('b','d')]),'a')['branched'])
        self.assertTrue(routing_ambiguity(self.graph([('a','b'),('b','c'),('a','c')]),'a')['alternate_paths'])
    def test_ideal_duplicate_contacts_are_not_physical_branches(self):
        graph=self.graph([('a','b')])
        for i in range(2):
            edge={'kind':'terminal'}
            graph.setdefault('start',[]).append(('a',edge));graph['a'].append(('start',edge))
        evidence=routing_ambiguity(graph,'start')
        self.assertFalse(evidence['branched']);self.assertFalse(evidence['alternate_paths'])


@unittest.skipIf(pcbnew is None, 'Requires installed native KiCad geometry')
class NativeGeometryTests(unittest.TestCase):
    def engine(self, board):
        e=TraceMeasurementEngine(board)
        e._stackup_cache=[StackupLayer('F.Cu','copper',.035),StackupLayer('D1','core',.1,.1,4.2),
            StackupLayer('In1.Cu','copper',.035),StackupLayer('D2','core',.8,.8,4.2),
            StackupLayer('In2.Cu','copper',.035),StackupLayer('D3','core',.2,.2,4.2),
            StackupLayer('B.Cu','copper',.035)]
        return e
    def pad(self, board, net, name, x, y, layer):
        fp=pcbnew.FOOTPRINT(board);fp.SetReference(name);board.Add(fp)
        pad=pcbnew.PAD(fp);pad.SetNumber('1');pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE);pad.SetSize(pcbnew.VECTOR2I(800000,800000))
        layers=pcbnew.LSET();layers.AddLayer(layer)
        pad.SetLayerSet(layers);pad.SetPosition(pcbnew.VECTOR2I(round(x*1e6),round(y*1e6)))
        pad.SetNet(net);fp.Add(pad)
        return pad
    def track(self, board, net, a, b, layer):
        item=pcbnew.PCB_TRACK(board);item.SetNet(net);item.SetWidth(200000);item.SetLayer(layer)
        item.SetStart(pcbnew.VECTOR2I(*a));item.SetEnd(pcbnew.VECTOR2I(*b));board.Add(item)
    def board(self):
        b=pcbnew.BOARD();b.SetCopperLayerCount(4)
        net=pcbnew.NETINFO_ITEM(b,'SIG');b.Add(net)
        return b,net
    def test_native_connected_span_and_residual_through_blind_microvia(self):
        for bottom,kind,exit_layer in ((pcbnew.B_Cu,pcbnew.VIATYPE_THROUGH,pcbnew.B_Cu),
                            (pcbnew.B_Cu,pcbnew.VIATYPE_THROUGH,pcbnew.In1_Cu),
                            (pcbnew.In1_Cu,pcbnew.VIATYPE_BLIND,pcbnew.In1_Cu),
                            (pcbnew.In1_Cu,pcbnew.VIATYPE_MICROVIA,pcbnew.In1_Cu)):
            with self.subTest(bottom=bottom,kind=kind):
                b,net=self.board()
                self.pad(b,net,'J1',2,5,pcbnew.F_Cu);self.pad(b,net,'J2',8,5,exit_layer)
                via=pcbnew.PCB_VIA(b);via.SetNet(net);via.SetViaType(kind)
                via.SetLayerPair(pcbnew.F_Cu,bottom);via.SetPosition(pcbnew.VECTOR2I(5000000,5000000))
                via.SetWidth(600000);via.SetDrill(300000);b.Add(via)
                self.track(b,net,(2000000,5000000),(5000000,5000000),pcbnew.F_Cu)
                self.track(b,net,(5000000,5000000),(8000000,5000000),exit_layer)
                result=self.engine(b).measure('SIG','J1.1','J2.1')
                self.assertEqual(result.status,'partial')
                section=next(s for s in result.segments if s['kind']=='via')
                self.assertAlmostEqual(section['length_mm'],1.205 if exit_layer==pcbnew.B_Cu else .135)
                residual=section['via_geometry']['remaining_barrel']
                self.assertEqual(bool(residual),bottom!=exit_layer)
                self.assertIsNone(section['capacitance_pf'])
    def zone(self, board, net, rectangles, layer=None):
        if layer is None:layer=pcbnew.F_Cu
        zone=pcbnew.ZONE(board);zone.SetNet(net);zone.SetLayer(layer)
        poly=pcbnew.SHAPE_POLY_SET()
        for x1,y1,x2,y2 in rectangles:
            line=pcbnew.SHAPE_LINE_CHAIN()
            for x,y in ((x1,y1),(x2,y1),(x2,y2),(x1,y2)):line.Append(round(x*1e6),round(y*1e6))
            line.SetClosed(True);poly.AddOutline(line)
        zone.SetFilledPolysList(layer,poly);zone.SetIsFilled(True);board.Add(zone)
    def test_native_filled_zone_corridor_and_disconnected_islands(self):
        for rectangles,expected in (([(0,0,10,10)],'partial'),
                                    ([(0,0,4,10),(6,0,10,10)],'disconnected')):
            with self.subTest(expected=expected):
                b,net=self.board();self.pad(b,net,'J1',2,5,pcbnew.F_Cu);self.pad(b,net,'J2',8,5,pcbnew.F_Cu)
                self.zone(b,net,rectangles)
                result=self.engine(b).measure('SIG','J1.1','J2.1')
                self.assertEqual(result.status,expected)
                if expected=='partial':self.assertTrue(any(s['kind']=='zone' for s in result.segments))

    def test_native_branch_marks_selected_path_as_not_unique(self):
        b,net=self.board()
        self.pad(b,net,'J1',2,5,pcbnew.F_Cu);self.pad(b,net,'J2',8,5,pcbnew.F_Cu)
        self.track(b,net,(2000000,5000000),(8000000,5000000),pcbnew.F_Cu)
        self.track(b,net,(5000000,5000000),(5000000,8000000),pcbnew.F_Cu)
        result=self.engine(b).measure('SIG','J1.1','J2.1')
        self.assertTrue(result.route_topology['branched'])
        self.assertEqual(result.status,'partial');self.assertFalse(result.impedance_valid)
        self.assertIn('ROUTE_AMBIGUOUS',{b['code'] for b in result.blockers})

    def test_native_duplicate_internal_labels_do_not_bridge_a_copper_gap(self):
        b,net=self.board()
        for name,x in (('J1',2),('X',4),('X',6),('J2',8)):
            self.pad(b,net,name,x,5,pcbnew.F_Cu)
        self.track(b,net,(2000000,5000000),(4000000,5000000),pcbnew.F_Cu)
        self.track(b,net,(6000000,5000000),(8000000,5000000),pcbnew.F_Cu)
        result=self.engine(b).measure('SIG','J1.1','J2.1')
        self.assertEqual(result.status,'disconnected')

    def test_overlapping_reference_candidates_are_not_selected(self):
        g=geometry();g.fits=lambda *args: True
        g.engine.dielectric_to_reference=lambda *args: (.1,4.2)
        g.islands=[{'layer':2,'net':'GND','id':'a'},{'layer':2,'net':'GND2','id':'b'}]
        self.assertIsNone(g.reference(0,(0,0),(100,0),.2))
        self.assertEqual(g.reference(0,(0,0),(100,0),.2,all_matches=True),[])

    def test_native_explicit_non_ground_reference_is_partial(self):
        b,net=self.board();reference=pcbnew.NETINFO_ITEM(b,'POWER_RETURN');b.Add(reference)
        self.pad(b,net,'J1',2,5,pcbnew.F_Cu);self.pad(b,net,'J2',8,5,pcbnew.F_Cu)
        self.track(b,net,(2000000,5000000),(8000000,5000000),pcbnew.F_Cu)
        self.zone(b,reference,[(0,0,10,10)],layer=pcbnew.In1_Cu)
        result=self.engine(b).measure('SIG','J1.1','J2.1',reference_layer='In1.Cu')
        self.assertEqual(result.status,'partial');self.assertFalse(result.impedance_valid)
        self.assertIn('REFERENCE_ELECTRICAL_ROLE_UNVERIFIED',{b['code'] for b in result.blockers})


if __name__ == '__main__':unittest.main()
