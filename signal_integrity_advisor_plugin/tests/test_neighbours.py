"""Exact gap/overlap, bounded spatial work, unknowns and native source custody."""
import hashlib
import contextlib
from io import StringIO
import json
import math
from pathlib import Path
import tempfile
import unittest
from signal_integrity_advisor_plugin.neighbours import map_segments,map_board,settings_checked,attach_study
from signal_integrity_advisor_plugin.neighbour_report import html_report,colour


def segment(identifier,net='A',a=(0.,0.),b=(20.,0.),width=.2,layer='F.Cu'):
    return dict(id=identifier,net=net,start_mm=list(a),end_mm=list(b),width_mm=width,layer=layer)


class GeometryTests(unittest.TestCase):
    def pair(self,**settings):
        return map_segments([segment('a'),segment('b','B',(5.,.5),(25.,.5))],settings)

    def test_analytic_parallel_gap_and_overlap_without_fabricated_voltage(self):
        report=self.pair();self.assertEqual(len(report['pairs']),1);row=report['pairs'][0]
        self.assertAlmostEqual(row['gap_mm'],.3);self.assertAlmostEqual(row['parallel_length_mm'],15.)
        self.assertIsNone(row['next_peak_v']);self.assertEqual(row['coupling_status'],'UNKNOWN')
        self.assertEqual(report['coverage']['comparisons'],1)

    def test_selected_net_is_exact_and_neighbours_include_other_nets(self):
        self.assertEqual(len(self.pair(nets=['B'])['pairs']),1)
        self.assertFalse(self.pair(nets=['B*'])['pairs'])
        self.assertFalse(self.pair(layers=['B.Cu'])['pairs'])
        self.assertFalse(self.pair(radius_mm=.2)['pairs'])

    def test_crossing_contact_is_geometric_and_coupling_stays_unknown(self):
        rows=[segment('a'),segment('b','B',(10.,-2.),(10.,2.))]
        row=map_segments(rows)['pairs'][0]
        self.assertAlmostEqual(row['gap_mm'],-.2);self.assertEqual(row['parallel_length_mm'],0.)
        self.assertIsNone(row['next_peak_v']);self.assertEqual(row['closeness'],1.)

    def test_layer_and_same_net_do_not_form_pairs(self):
        rows=[segment('a'),segment('b','A',(0.,.3),(20.,.3)),segment('c','C',layer='B.Cu')]
        self.assertFalse(map_segments(rows)['pairs'])

    def test_model_uses_existing_modes_and_retains_unequal_unknowns(self):
        from signal_integrity_advisor_plugin.crosstalk import coupled_modes,matched_step,C_MM_NS
        model=dict(reference_layer='B.Cu',height_mm=.2,epsilon_r=4.,copper_mm=0.,rise_ns=.1,swing_v=1.)
        row=self.pair(model=model)['pairs'][0];modes=coupled_modes(.2,.3,.2,4.)
        expected=matched_step(modes['z_even_ohm'],modes['z_odd_ohm'],15*2/C_MM_NS,.1,1.)
        self.assertAlmostEqual(row['next_peak_v'],expected['next_peak_v']);self.assertEqual(row['coupling_status'],'ASSUMED_REFERENCE')
        row=map_segments([segment('a'),segment('b','B',(0.,.5),(20.,.5),width=.3)],{'model':model})['pairs'][0]
        self.assertIsNone(row['next_peak_v'])

    def test_no_whole_board_quadratic_join_for_sparse_ten_thousand_tracks(self):
        rows=[segment(str(i),str(i%5),(i*5.,0.),(i*5.+.5,0.)) for i in range(10000)]
        report=map_segments(rows,{'radius_mm':.2})
        self.assertTrue(report['coverage']['complete_search']);self.assertFalse(report['pairs'])
        self.assertLess(report['coverage']['comparisons'],20000)
        self.assertLess(report['coverage']['index_references'],100000)

    def test_dense_same_net_and_diagonal_index_are_bounded(self):
        report=map_segments([segment(str(i)) for i in range(200)],{'max_comparisons':20})
        self.assertEqual(report['status'],'INCOMPLETE');self.assertTrue(report['warnings'])
        report=map_segments([segment('a',a=(0.,0.),b=(1000.,1000.))],{'max_cells':30})
        self.assertEqual(report['status'],'INCOMPLETE');self.assertLessEqual(report['coverage']['index_references'],31)

    def test_output_budget_and_cancel_and_guard_are_not_passed_as_zero_risk(self):
        self.assertEqual(self.pair(max_pairs=1)['status'],'REVIEW')
        crowded=[segment('a'),segment('b','B',(0.,.5),(20.,.5)),segment('c','C',(0.,.7),(20.,.7))]
        self.assertEqual(map_segments(crowded,{'max_pairs':1})['status'],'INCOMPLETE')
        with self.assertRaises(InterruptedError):map_segments([],cancelled=lambda:True)
        calls=[]
        self.pair() # baseline
        map_segments([segment('a')],guard=lambda:calls.append(True));self.assertEqual(len(calls),2)
        for raw in ({'radius_mm':float('nan')},{'max_pairs':2001},{'model':{}},{'nets':'A'}):
            with self.subTest(raw=raw),self.assertRaises(ValueError):settings_checked(raw)

    def test_study_overlay_retains_section_extent_and_rejects_stale_hash(self):
        report=self.pair();report['source_fingerprints']={'board':'x'}
        study=dict(source_fingerprints={'board':'x'},crosstalk=[dict(id='ab',sections=[dict(aggressor_item_uuids=['a'],victim_item_uuids=['b'],length_mm=30.,next_peak_v=.012,status='LOCAL_REFERENCE_COVERED')])])
        attach_study(report,study);row=report['pairs'][0]
        self.assertIsNone(row['next_peak_v']);self.assertEqual(row['study_sections'][0]['section_length_mm'],30.)
        study['source_fingerprints']={'board':'changed'}
        with self.assertRaisesRegex(ValueError,'fingerprints'):attach_study(report,study)

    def test_report_contains_real_geometry_safe_names_and_separate_units(self):
        report=map_segments([segment('a','A<script>'),segment('b','B',(0.,.5),(20.,.5))])
        document=html_report(report)
        self.assertIn('<svg',document);self.assertIn('Edge gap mm',document);self.assertIn('Parallel overlap mm',document)
        self.assertIn('UNKNOWN',document);self.assertNotIn('A<script>',document)
        self.assertNotEqual(colour(0.),colour(1.))


try:import pcbnew
except ImportError:pcbnew=None


@unittest.skipIf(pcbnew is None,'Native KiCad Python required')
class NativeTests(unittest.TestCase):
    def test_native_worker_geometry_and_source_hash_are_read_only(self):
        from signal_integrity_advisor_plugin.service import execute,source_fingerprints
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'board.kicad_pcb';board=pcbnew.BOARD();board.SetFileName(str(path))
            for code,name,y in ((1,'DATA',0),(2,'CLOCK',.5)):
                net=pcbnew.NETINFO_ITEM(board,name,code);board.Add(net)
                track=pcbnew.PCB_TRACK(board);track.SetStart(pcbnew.VECTOR2I(0,pcbnew.FromMM(y)));track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(20),pcbnew.FromMM(y)))
                track.SetWidth(pcbnew.FromMM(.2));track.SetLayer(pcbnew.F_Cu);track.SetNet(net);board.Add(track)
            via=pcbnew.PCB_VIA(board);via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(10),0));via.SetWidth(pcbnew.FromMM(.6));via.SetDrill(pcbnew.FromMM(.3));board.Add(via)
            pcbnew.SaveBoard(str(path),board);before=path.read_bytes();fingerprints=source_fingerprints(path)
            request=dict(mode='neighbours',board_path=str(path),source_fingerprints=fingerprints,settings={'nets':['DATA']})
            result=execute(request)['neighbours'];row=result['pairs'][0]
            self.assertAlmostEqual(row['gap_mm'],.3);self.assertAlmostEqual(row['parallel_length_mm'],20.)
            self.assertEqual(result['coverage']['omitted_geometry']['PCB_VIA'],1);self.assertEqual(path.read_bytes(),before)
            from signal_integrity_advisor_plugin.cli import main
            output=Path(directory)/'neighbours.json';html=output.with_suffix('.html')
            with contextlib.redirect_stdout(StringIO()):
                status=main(['neighbours',str(path),'--net','DATA','--output',str(output),'--html',str(html)])
            self.assertEqual(status,3) # REVIEW is evidence, never signoff.
            self.assertEqual(json.loads(output.read_text())['schema'],'wayricad.si-neighbours/v1')
            self.assertIn('Geometric edge-gap heat map',html.read_text(encoding='utf-8'))
            self.assertEqual(path.read_bytes(),before)
            path.write_bytes(before+b'\n')
            with self.assertRaisesRegex(ValueError,'changed'):execute(request)


if __name__=='__main__':unittest.main()
