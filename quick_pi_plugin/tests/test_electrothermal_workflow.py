"""Source binding, saved geometry, reports, intake and real worker entrypoint."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from quick_pi_plugin.electrothermal_cli import parse_envelope, main as run_cli
from quick_pi_plugin.electrothermal_report import draw, write_report
from quick_pi_plugin.service import execute
from quick_pi_plugin.tests.test_electrothermal import request as steady


class ElectrothermalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)

    def test_uniform_temperature_display_does_not_amplify_roundoff(self):
        from matplotlib.figure import Figure
        bundle=execute({'action':'electrothermal','mode':'steady','study':steady()})
        figure=Figure(figsize=(11,7)); draw(figure,bundle)
        voltage,temperature=figure.axes[:2]
        self.assertFalse(voltage.yaxis.get_major_formatter().get_useOffset())
        self.assertIn('uniform',temperature.get_title())
        self.assertGreaterEqual(temperature.collections[0].norm.vmax-temperature.collections[0].norm.vmin,1.)

    def test_source_immutability_stale_request_and_export(self):
        board=self.root/'source.kicad_pcb'; board.write_bytes(b'(kicad_pcb (version 20250101))')
        sha=hashlib.sha256(board.read_bytes()).hexdigest()
        bundle=execute({'action':'electrothermal','mode':'steady','study':steady(),
                        'board_path':str(board),'source_sha256':sha})
        self.assertEqual(bundle['source_sha256'],sha)
        self.assertEqual(bundle['board_binding'],'provenance_only')
        self.assertEqual(hashlib.sha256(board.read_bytes()).hexdigest(),sha)
        with self.assertRaisesRegex(ValueError,'overwrite'):write_report(board.with_suffix('.html'),{**bundle,'study_input_path':str(board.with_suffix('.json'))})
        write_report(self.root/'result.html',bundle)
        self.assertIn('Raw results', (self.root/'result.html').read_text(encoding='utf-8'))
        self.assertTrue(json.loads((self.root/'result.json').read_text())['electrothermal']['converged'])
        altered=copy.deepcopy(bundle); altered['study']['source_voltage_V']=9
        with self.assertRaisesRegex(ValueError,'settings changed'):write_report(self.root/'changed.html',altered)
        board.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):write_report(self.root/'stale.html',bundle)
        with self.assertRaisesRegex(ValueError,'changed'):execute({'action':'electrothermal','mode':'steady','study':steady(),'board_path':str(board),'source_sha256':sha})

    def test_nested_model_hash_cannot_claim_another_saved_board(self):
        board=self.root/'source.kicad_pcb'; board.write_bytes(b'saved board bytes')
        for field in ('mesh','thermal_geometry'):
            study=steady(); study[field]['source_sha256']='0'*64
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'different saved PCB'):
                execute({'action':'electrothermal','mode':'steady','study':study,'board_path':str(board)})

    def test_pair_publication_failure_restores_prior_report(self):
        bundle=execute({'action':'electrothermal','mode':'steady','study':steady()})
        html=self.root/'report.html'; data=html.with_suffix('.json')
        html.write_bytes(b'OLD_HTML'); data.write_bytes(b'OLD_JSON')
        real_replace=os.replace; calls=[]
        def fail_second(source,target):
            calls.append(target)
            if len(calls)==2: raise OSError('injected second publication failure')
            return real_replace(source,target)
        with patch('quick_pi_plugin.electrothermal_report.os.replace',side_effect=fail_second):
            with self.assertRaisesRegex(OSError,'second publication'):write_report(html,bundle)
        self.assertEqual(html.read_bytes(),b'OLD_HTML'); self.assertEqual(data.read_bytes(),b'OLD_JSON')
        self.assertEqual(set(self.root.iterdir()),{html,data})

    def test_strict_intake_and_cli_path_guards(self):
        for text in ('{"mode":"steady","study":{},"study":{}}',
                     '{"mode":"steady","study":{"power":NaN}}',
                     '{"mode":"other","study":{}}',
                     '{"mode":"steady","study":{},"command":"x"}'):
            with self.subTest(text=text),self.assertRaises(ValueError):parse_envelope(text.encode())
        from argparse import Namespace
        source=self.root/'study.json'; source.write_text(json.dumps({'mode':'steady','study':steady()}))
        args=Namespace(electrothermal=source,board=None,output=source,html=None,timeout=3.)
        with self.assertRaisesRegex(ValueError,'overwrite'):run_cli(args,lambda *a,**k:None)
        args.output=None; args.html=source.with_suffix('.html')
        with self.assertRaisesRegex(ValueError,'overwrite'):run_cli(args,lambda *a,**k:None)
        args.html=None
        with self.assertRaisesRegex(ValueError,'unrelated'):run_cli(args,lambda *a,**k:None,forbidden=True)

    def test_real_isolated_worker_produces_coupled_report(self):
        source=self.root/'request.json'; target=self.root/'response.json'
        source.write_text(json.dumps({'action':'electrothermal','mode':'steady','study':steady(),
                                     'html_output':str(self.root/'worker.html')}),encoding='utf-8')
        script=Path(__file__).resolve().parents[1]/'quickmain.py'
        done=subprocess.run([sys.executable,'-I','-B',str(script),'--worker',str(source),str(target)],
                            capture_output=True,text=True,timeout=60)
        self.assertEqual(done.returncode,0,done.stderr)
        output=json.loads(target.read_text(encoding='utf-8'))
        self.assertTrue(output['electrothermal']['converged'])
        self.assertTrue((self.root/'worker.html').is_file())

    def test_cli_distinguishes_nonconvergence_and_limits(self):
        from argparse import Namespace
        source=self.root/'study.json'; source.write_text(json.dumps({'mode':'steady','study':steady()}))
        args=Namespace(electrothermal=source,board=None,output=None,html=None,timeout=3.)
        bundle=execute({'action':'electrothermal','mode':'steady','study':steady()})
        with patch('builtins.print'):
            self.assertEqual(run_cli(args,lambda *a,**k:bundle),0)
            stopped=copy.deepcopy(bundle); stopped['electrothermal']['converged']=False
            self.assertEqual(run_cli(args,lambda *a,**k:stopped),3)
            violated=copy.deepcopy(bundle); violated['electrothermal']['limits']['operating_point_valid']=False
            self.assertEqual(run_cli(args,lambda *a,**k:violated),4)

    def test_saved_board_extracts_identical_layer_geometry_without_sibling(self):
        try:import pcbnew as p
        except ImportError:self.skipTest('Saved-board extraction requires native KiCad pcbnew')
        board=p.BOARD(); net=p.NETINFO_ITEM(board,'RAIL'); board.Add(net)
        point=lambda x,y:p.VECTOR2I(p.FromMM(x),p.FromMM(y))
        track=p.PCB_TRACK(board); track.SetStart(point(2,5)); track.SetEnd(point(8,5))
        track.SetWidth(p.FromMM(2)); track.SetLayer(p.F_Cu); track.SetNet(net); board.Add(track)
        for ref,x in (('J1',2),('J2',8)):
            fp=p.FOOTPRINT(board); fp.SetReference(ref); board.Add(fp)
            pad=p.PAD(fp); pad.SetNumber('1'); pad.SetPosition(point(x,5)); pad.SetSize(point(.5,2))
            pad.SetShape(p.PAD_SHAPE_RECT); pad.SetAttribute(p.PAD_ATTRIB_SMD)
            layers=p.LSET(); layers.AddLayer(p.F_Cu); pad.SetLayerSet(layers); pad.SetNet(net); fp.Add(pad)
        for a,b in (((0,0),(10,0)),((10,0),(10,10)),((10,10),(0,10)),((0,10),(0,0))):
            line=p.PCB_SHAPE(); line.SetShape(p.SHAPE_T_SEGMENT); line.SetLayer(p.Edge_Cuts)
            line.SetStart(point(*a)); line.SetEnd(point(*b)); line.SetWidth(p.FromMM(.05)); board.Add(line)
        path=self.root/'coupled.kicad_pcb'; p.SaveBoard(str(path),board)
        stackup='(stackup (layer "F.Cu" (type "copper") (thickness .035)) (layer "core" (type "core") (thickness 1.53)) (layer "B.Cu" (type "copper") (thickness .035)))'
        path.write_text(path.read_text(encoding='utf-8').replace('(setup\n','(setup\n'+stackup+'\n',1),encoding='utf-8')
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        study={'electrical':{'net':'RAIL','source_terminal':'J1.1','sink_terminal':'J2.1',
                             'sink_current':1.,'source_voltage':3.3,'edge_mm':.8},
               'thermal_settings':{'ambient_c':20.,'dielectric_k_w_mk':.3,'via_plating_mm':.025,
                                   'grid_cells_long_axis':24,'board_h_w_m2k':10.,'board_emissivity':0.},
               'coupling':{'material_temperature_range_c':[-40.,150.],'temperature_cap_c':105.}}
        bundle=execute({'action':'electrothermal','mode':'steady','study':study,'board_path':str(path),'source_sha256':sha})
        self.assertTrue(bundle['electrothermal']['converged'])
        self.assertEqual(bundle['electrothermal']['bindings']['source_sha256'],sha)
        self.assertEqual(bundle['board_binding'],'extracted_geometry')
        self.assertGreater(bundle['electrothermal']['hot']['voltage_drop_V'],bundle['electrothermal']['cold']['voltage_drop_V'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),sha)


if __name__=='__main__':unittest.main()
