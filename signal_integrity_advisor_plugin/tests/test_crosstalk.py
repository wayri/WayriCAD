"""Independent analytic checks and native geometry contracts for local coupling."""
import copy
import math
from pathlib import Path
import tempfile
import unittest

from signal_integrity_advisor_plugin import crosstalk as ct


class ModalPhysicsTests(unittest.TestCase):
    def test_ground_image_kernel_matches_exact_cylinder_capacitance(self):
        # Independent analytic C'=2*pi*epsilon/acosh(center_height/radius).
        for radius, height in ((.1,.5),(.2,.3)):
            n=128
            points=[(radius*math.cos(2*math.pi*i/n),height+radius*math.sin(2*math.pi*i/n)) for i in range(n)]
            panels=list(zip(points,points[1:]+points[:1]))
            charge=ct._solve(ct._potential_matrix(panels),[1.]*n)
            measured=ct.EPS0*sum(charge)
            exact=2*math.pi*ct.EPS0/math.acosh(height/radius)
            self.assertAlmostEqual(measured/exact,1,delta=.001)

    def test_refinement_thickness_thin_limit_and_units(self):
        thin=ct.coupled_modes(.15,.15,.2,4)
        finite=ct.coupled_modes(.15,.15,.2,4,.035)
        near_thin=ct.coupled_modes(.15,.15,.2,4,.00001)
        scaled=ct.coupled_modes(1.5,1.5,2,4,.35)
        self.assertLess(finite['z_even_ohm'],thin['z_even_ohm'])
        self.assertLess(finite['panel_refinement_relative'],.02)
        self.assertLess(finite['coupling_refinement_relative'],.02)
        refined=ct._finite_capacitances(.15,.15,.2,.035,4,32)
        reference_k=(refined[1]-refined[0])/sum(refined)
        self.assertAlmostEqual(finite['coupling']/reference_k,1,delta=.02)
        for key in ('z_even_ohm','z_odd_ohm'):
            self.assertAlmostEqual(near_thin[key]/thin[key],1,delta=.005)
            self.assertAlmostEqual(scaled[key]/finite[key],1,places=10)
        for mode in ('even','odd'):
            inductance=finite['l_'+mode+'_nh_m']*1e-9
            capacitance=finite['c_'+mode+'_pf_m']*1e-12
            self.assertAlmostEqual(math.sqrt(inductance/capacitance),finite['z_'+mode+'_ohm'])
            self.assertAlmostEqual(1/math.sqrt(inductance*capacitance),299792458/2,places=5)

    def test_far_separation_zero_coupling_and_material_scaling(self):
        far=ct.coupled_modes(.2,400,.2,4,.035)
        self.assertLess(far['coupling'],1e-6)
        self.assertLessEqual(far['coupling_refinement_absolute'],max(1e-9,.02*abs(far['coupling'])))
        self.assertEqual(ct.matched_step(50,50,1,.1,1)['next_peak_v'],0)
        air=ct.coupled_modes(.2,.2,.2,1,.035)
        fr4=ct.coupled_modes(.2,.2,.2,4,.035)
        self.assertAlmostEqual(air['z_even_ohm']/fr4['z_even_ohm'],2)

    def test_exact_matched_modal_step_and_delay(self):
        # Independent even/odd modal voltage division at t=0+.
        ze,zo,vs=60.,40.,3.3
        resistance=math.sqrt(ze*zo)
        expected=vs/2*(ze/(resistance+ze)-zo/(resistance+zo))
        response=ct.matched_step(ze,zo,1,.08,vs)
        self.assertAlmostEqual(response['next_peak_v'],expected,places=13)
        self.assertAlmostEqual(response['next_peak_time_ns'],.1)
        self.assertEqual(response['fext_peak_v'],0)
        # Direct independently summed scalar TL modes, including source/load
        # reflections, reproduce the entire waveform at every stored breakpoint.
        ramp=lambda t:min(1.,max(0.,t/.1))
        def near(z,t):
            gamma=(resistance-z)/(resistance+z)
            launch=(vs/2)*z/(resistance+z)
            return launch*ramp(t)+sum(launch*gamma*(1+gamma)*gamma**(2*n)*ramp(t-2*(n+1)) for n in range(25))
        def far(z,t):
            gamma=(resistance-z)/(resistance+z)
            launch=(vs/2)*z/(resistance+z)
            return sum(launch*(1+gamma)*gamma**(2*n)*ramp(t-(2*n+1)) for n in range(25))
        for t,v in response['next_samples']:
            self.assertAlmostEqual(v,near(ze,t)-near(zo,t),delta=1e-12)
            self.assertAlmostEqual(far(ze,t)-far(zo,t),0,delta=1e-12)
        slow=ct.matched_step(ze,zo,.01,1,vs)
        self.assertLess(slow['next_peak_v'],expected*.03)

    def test_rejected_geometry_and_inputs(self):
        for args in ((.2,0,.2,4),(.001,.2,.2,4),(.2,.2,.2,.5),(.2,.2,.2,4,.3)):
            with self.assertRaises(ValueError):ct.coupled_modes(*args)


def segment(start,end,*,width=.2,layer='F.Cu',offset=0):
    return dict(kind='track',geometry='straight',start_mm=start,end_mm=end,width_mm=width,
                layer=layer,offset_mm=offset,length_mm=ct._distance(start,end),item_uuids=['test'])


class GeometryTests(unittest.TestCase):
    def test_overlap_true_gap_reciprocity_and_reversed_direction(self):
        a=segment([0,0],[10,0])
        b=segment([8,.5],[2,.5],offset=4)
        ab=ct.parallel_overlap(a,b)
        ba=ct.parallel_overlap(b,a)
        self.assertEqual(ab['length_mm'],6)
        self.assertAlmostEqual(ab['gap_mm'],.3)
        self.assertEqual(ab['direction'],'opposite')
        self.assertEqual(ab['near_victim_role'],'receiver-side')
        self.assertEqual(ab['aggressor_interval_mm'],[2,8])
        self.assertEqual(ab['victim_interval_mm'],[4,10])
        self.assertEqual(ab['length_mm'],ba['length_mm'])
        self.assertAlmostEqual(ab['gap_mm'],ba['gap_mm'])

    def test_crossing_layers_and_disjoint_tracks_do_not_become_parallel(self):
        a=segment([0,0],[10,0])
        for b in (segment([5,-1],[5,1]),segment([0,.5],[10,.5],layer='B.Cu'),segment([11,.5],[12,.5])):
            self.assertIsNone(ct.parallel_overlap(a,b))

    def test_config_rejects_unknown_ids_missing_reference_and_nan(self):
        cases=[{'id':'a'},{'id':'b'}]
        good={'aggressor':'a','victim':'b','rise_ns':1,'swing_v':1,
              'reference':{'model':'homogeneous-plane','layer':'B.Cu','height_mm':.2,'epsilon_r':4}}
        self.assertEqual(ct.checked_pairs({'crosstalk':[good]},cases)[0]['aggressor'],'a')
        for changes in ({'aggressor':'missing'},{'victim':'a'},{'rise_ns':float('nan')},{'reference':{}}):
            with self.assertRaises(ValueError):ct.checked_pairs({'crosstalk':[dict(good,**changes)]},cases)


try:
    import pcbnew
except ImportError:
    pcbnew=None


@unittest.skipIf(pcbnew is None,'KiCad native Python required')
class NativeCouplingTests(unittest.TestCase):
    def make_board(self,path,*,crossing=False,extra=False):
        board=pcbnew.BOARD()
        point=lambda x,y:pcbnew.VECTOR2I(pcbnew.FromMM(x),pcbnew.FromMM(y))
        front=pcbnew.LSET();front.AddLayer(pcbnew.F_Cu)
        for code,name,y in ((1,'A',10),(2,'B',10.5)):
            board.Add(pcbnew.NETINFO_ITEM(board,name,code))
            start,end=((20,5),(20,15)) if crossing and code==2 else ((5,y),(35,y))
            for ref,xy in ((f'U{code}',start),(f'J{code}',end)):
                fp=pcbnew.FOOTPRINT(board);fp.SetReference(ref);fp.SetPosition(point(*xy));board.Add(fp)
                pad=pcbnew.PAD(fp);pad.SetNumber('1');pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
                pad.SetPosition(point(*xy));pad.SetSize(point(.2,.2));pad.SetLayerSet(front);pad.SetNetCode(code);fp.Add(pad)
            track=pcbnew.PCB_TRACK(board);track.SetStart(point(*start));track.SetEnd(point(*end))
            track.SetWidth(pcbnew.FromMM(.2));track.SetLayer(pcbnew.F_Cu);track.SetNetCode(code);board.Add(track)
        if extra:
            fp=pcbnew.FOOTPRINT(board);fp.SetReference('TP1');fp.SetPosition(point(20,10));board.Add(fp)
            pad=pcbnew.PAD(fp);pad.SetNumber('1');pad.SetPosition(point(20,10));pad.SetSize(point(.2,.2));pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD);pad.SetLayerSet(front);pad.SetNetCode(1);fp.Add(pad)
        pcbnew.SaveBoard(str(path),board)
        cases=[dict(id=name,net=name,start=f'U{i}.1',end=f'J{i}.1',inputs={'z0_ohm':50.,'epsilon_eff':4.}) for i,name in ((1,'A'),(2,'B'))]
        pair={'id':'ab','aggressor':'A','victim':'B','rise_ns':.1,'swing_v':1.,
              'reference':{'model':'homogeneous-plane','layer':'B.Cu','height_mm':.2,'epsilon_r':4.}}
        return pcbnew.LoadBoard(str(path)),{'cases':cases,'crosstalk':[pair]}

    def test_native_geometry_numeric_coverage_direction_and_immutability(self):
        from signal_integrity_advisor_plugin.study import run_study
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'pair.kicad_pcb'
            board,config=self.make_board(path)
            before=path.read_bytes()
            report=run_study(board,config)
            pair=report['crosstalk'][0]
            self.assertEqual(pair['status'],'REVIEW',pair)
            self.assertEqual(len(pair['sections']),1,pair)
            section=pair['sections'][0]
            self.assertAlmostEqual(section['length_mm'],30)
            self.assertAlmostEqual(section['gap_mm'],.3)
            self.assertGreater(section['next_peak_v'],0)
            self.assertAlmostEqual(section['delay_ns'],30*2/299.792458)
            self.assertAlmostEqual(pair['coverage']['victim']['unmodeled_length_mm'],0)
            from signal_integrity_advisor_plugin.report_plots import crosstalk_html
            pair['id']='<img src=x onerror=alert(1)>'
            document=crosstalk_html(report)
            self.assertIn('href="#si-case-0"',document)
            self.assertIn('href="#si-case-1"',document)
            self.assertIn('NEXT mV',document)
            self.assertNotIn('<img src=x',document)
            self.assertIn('&lt;img',document)
            config['cases'][1].update(start='J2.1',end='U2.1')
            reverse=run_study(board,config)['crosstalk'][0]['sections'][0]
            self.assertEqual(reverse['near_victim_role'],'receiver-side')
            self.assertAlmostEqual(reverse['next_peak_v'],section['next_peak_v'])
            self.assertEqual(before,path.read_bytes())

    def test_crossings_remain_unresolved_and_branch_loading_is_not_hidden(self):
        from signal_integrity_advisor_plugin.study import run_study
        with tempfile.TemporaryDirectory() as directory:
            for crossing,extra in ((True,False),(False,True)):
                board,config=self.make_board(Path(directory)/'pair.kicad_pcb',crossing=crossing,extra=extra)
                pair=run_study(board,config)['crosstalk'][0]
                if crossing:
                    self.assertEqual(pair['status'],'UNRESOLVED')
                    self.assertEqual(pair['coverage']['aggressor']['supported_overlap_mm'],0)
                else:
                    self.assertEqual(pair['status'],'REVIEW')
                    self.assertTrue(any('Multiple physical pads' in row['reason'] for row in pair['unresolved']))

    def test_saved_stripline_requires_real_planes_homogeneous_stackup_and_clear_corridor(self):
        from signal_integrity_advisor_plugin.study import run_study
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'stripline.kicad_pcb'
            board,config=self.make_board(path)
            board.SetCopperLayerCount(4)
            inner=pcbnew.LSET();inner.AddLayer(pcbnew.In1_Cu)
            for track in board.GetTracks():track.SetLayer(pcbnew.In1_Cu)
            for fp in board.GetFootprints():
                for pad in fp.Pads():pad.SetLayerSet(inner)
            board.Add(pcbnew.NETINFO_ITEM(board,'GND',3))
            for layer in (pcbnew.F_Cu,pcbnew.In2_Cu):
                poly=pcbnew.SHAPE_POLY_SET()
                contour=pcbnew.SHAPE_LINE_CHAIN()
                for x,y in ((0,0),(40,0),(40,20),(0,20)):contour.Append(pcbnew.FromMM(x),pcbnew.FromMM(y))
                contour.SetClosed(True);poly.AddOutline(contour)
                zone=pcbnew.ZONE(board);zone.SetLayer(layer);zone.SetNetCode(3)
                zone.Outline().Append(poly);zone.SetFilledPolysList(layer,poly);zone.SetIsFilled(True);board.Add(zone)
            pcbnew.SaveBoard(str(path),board)
            stack='(stackup (layer "F.Cu" (type "copper") (thickness 0.035)) (layer "dielectric 1" (type "core") (thickness 0.2) (epsilon_r 4)) (layer "In1.Cu" (type "copper") (thickness 0.035)) (layer "dielectric 2" (type "core") (thickness 0.2) (epsilon_r 4)) (layer "In2.Cu" (type "copper") (thickness 0.035)) (layer "dielectric 3" (type "core") (thickness 0.2) (epsilon_r 4)) (layer "B.Cu" (type "copper") (thickness 0.035)))'
            source=path.read_text().replace('(setup','(setup '+stack,1)
            path.write_text(source)
            config['crosstalk'][0]['reference']={'model':'saved-stripline','layer':'F.Cu','upper_layer':'In2.Cu'}
            def screen():
                return run_study(pcbnew.LoadBoard(str(path)),config)['crosstalk'][0]
            pair=screen()
            self.assertEqual(pair['status'],'REVIEW',pair)
            self.assertEqual(len(pair['sections']),1,pair)
            section=pair['sections'][0]
            self.assertEqual(section['status'],'LOCAL_REFERENCE_COVERED')
            self.assertAlmostEqual(section['reference_geometry']['height_mm'],.2175)
            self.assertGreater(section['next_peak_v'],0)
            self.assertGreater(pair['coverage']['aggressor']['unmodeled_length_mm'],0)
            path.write_text(source.replace('(epsilon_r 4)', '(epsilon_r 3)',1))
            rejected=screen()
            self.assertEqual(rejected['status'],'UNRESOLVED')
            self.assertTrue(any('Inhomogeneous' in r['reason'] for r in rejected['unresolved']))
            path.write_text(source.replace('(thickness 0.2) (epsilon_r 4)', '(thickness 0.2) (epsilon_r 4) addsublayer (thickness 0.1) (epsilon_r 3)',1))
            rejected=screen()
            self.assertTrue(any('sublayers' in r['reason'] for r in rejected['unresolved']))
            path.write_text(source)
            extra_board=pcbnew.LoadBoard(str(path))
            extra=pcbnew.PCB_TRACK(extra_board);extra.SetLayer(pcbnew.In1_Cu);extra.SetNetCode(1)
            extra.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(20),pcbnew.FromMM(10)))
            extra.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(20),pcbnew.FromMM(11)))
            extra.SetWidth(pcbnew.FromMM(.2));extra_board.Add(extra);pcbnew.SaveBoard(str(path),extra_board)
            rejected=screen()
            self.assertFalse(rejected['sections'])
            self.assertTrue(any('Additional same-layer copper' in r['reason'] for r in rejected['unresolved']))
            path.write_text(source)
            missing=pcbnew.LoadBoard(str(path));missing.Remove(list(missing.Zones())[0]);pcbnew.SaveBoard(str(path),missing)
            rejected=screen()
            self.assertFalse(rejected['sections'])
            self.assertTrue(any('Filled bounding reference' in r['reason'] for r in rejected['unresolved']))


if __name__=='__main__':
    unittest.main()
