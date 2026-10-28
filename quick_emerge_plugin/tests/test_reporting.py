import base64
from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from quick_emerge_plugin.model import validate_config,config_digest,source_identity
from quick_emerge_plugin.reporting import (build_html_report,export_html,export_pdf,
                                          result_digest,validate_report_result)


class _AssetInspector(HTMLParser):
    def __init__(self):super().__init__();self.images=[];self.scripts=[];self.downloads=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='img':self.images.append(a['src'])
        if tag=='script':self.scripts.append(a)
        if tag=='a' and 'download' in a:self.downloads.append(a['href'])


def fixture(board):
    c=validate_config({'mode':'pcb_line','points':3})
    f=[c['f_start_hz'],(c['f_start_hz']+c['f_stop_hz'])/2,c['f_stop_hz']]
    return {'schema':1,'config':c,'config_sha256':config_digest(c),'port_count':2,
            'source':source_identity(board),'backend':{'backend':'EMerge','version':'3.0.0b9'},
            'model_scope':'parametric-template','frequencies_hz':f,
            's_parameters':{'S11':[[0,0]]*3,'S12':[[.8,-.1]]*3,'S21':[[.79,-.09]]*3,'S22':[[.1,0]]*3},
            'field':{'x_mm':[-1,0,1],'y_mm':[-1,0,1],'z_mm':2,'frequency_hz':f[1],
                     'norm_e_v_m':[[0,1,None],[3,4,5],[6,7,8]]},
            'assumptions':['PEC conductors','No convergence qualification','Template geometry; originating PCB is context only']}


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        self.board=self.root/'board.kicad_pcb';self.board.write_text('(kicad_pcb)')
        self.result=fixture(self.board)
    def tearDown(self):self.directory.cleanup()

    def test_escape_custody_complete_inline_evidence_and_no_remote_assets(self):
        result=deepcopy(self.result);result['assumptions'].append('<script>alert(1)</script>')
        document=build_html_report(result,include_figures=False,title='<img src=x onerror=boom>',
                                   probes=[{'x_mm':1,'y_mm':-1,'label':'<b>Unknown</b>'}],
                                   line_profile={'start':[-1,-1],'end':[1,-1],'count':3})
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',document)
        self.assertNotIn('<script>',document);self.assertNotIn('<img src=x',document)
        self.assertIn(result_digest(result),document)
        self.assertIn('Unknown / unavailable',document)
        self.assertIn('Current bytes checked',document)
        self.assertIn('Nearest original grid samples',document)
        parsed=_AssetInspector();parsed.feed(document)
        self.assertFalse(parsed.scripts)
        evidence=json.loads(base64.b64decode(parsed.downloads[0].split(',',1)[1]))
        self.assertEqual(evidence['result'],result)
        self.assertTrue(evidence['source_verified_at_export'])
        self.assertIsNone(evidence['report_selections']['probes'][0]['value_v_m'])
        self.assertEqual(evidence['report_selections']['line_profile'][1]['value_v_m'],1)

    def test_reject_stale_setup_source_and_invalid_raw_data(self):
        with self.assertRaisesRegex(ValueError,'stale'):
            build_html_report(self.result,expected_config={**self.result['config'],'er':4},include_figures=False)
        self.board.write_text('(kicad_pcb changed)')
        with self.assertRaisesRegex(ValueError,'stale'):
            build_html_report(self.result,include_figures=False)
        archival=build_html_report(self.result,verify_source=False,include_figures=False)
        self.assertIn('ARCHIVAL EXPORT',archival)
        for mutation in [lambda r:r.update(config_sha256='bad'),lambda r:r['s_parameters']['S11'].__setitem__(0,[float('nan'),0]),
                         lambda r:r.update(source={'path':'x','sha256':'bad'}),lambda r:r.update(model_scope='unknown'),
                         lambda r:r['field'].update(frequency_hz=1),lambda r:r['field']['norm_e_v_m'][0].__setitem__(0,-1)]:
            r=deepcopy(self.result);mutation(r)
            with self.subTest(result=r),self.assertRaises(ValueError):
                build_html_report(r,verify_source=False,include_figures=False)

    def test_all_figures_embedded_and_result_is_unmodified(self):
        original=deepcopy(self.result)
        document=build_html_report(self.result,probes=[{'x_mm':0,'y_mm':0}],line_profile={'start':[-1,0],'end':[1,0],'count':3})
        parsed=_AssetInspector();parsed.feed(document)
        self.assertGreaterEqual(len(parsed.images),6)
        for src in parsed.images:
            self.assertTrue(src.startswith('data:image/png;base64,'))
            self.assertEqual(base64.b64decode(src.split(',',1)[1])[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(self.result,original)

    def test_export_protects_source_and_failed_export_preserves_previous_file(self):
        destination=self.root/'study.html'
        export_html(destination,self.result,include_figures=False)
        self.assertIn('Complete result JSON',destination.read_text(encoding='utf-8'))
        destination.write_text('previous')
        with self.assertRaises(ValueError):
            export_html(destination,self.result,expected_source={'path':'bad'},include_figures=False)
        self.assertEqual(destination.read_text(encoding='utf-8'),'previous')
        with self.assertRaises(ValueError):
            export_html(self.board,self.result,include_figures=False)
        alias=self.root/'alias.html'
        try:alias.hardlink_to(self.board)
        except OSError:return
        with self.assertRaisesRegex(ValueError,'overwrite'):
            export_html(alias,self.result,include_figures=False)
        self.assertEqual(self.board.read_text(),'(kicad_pcb)')

    def test_source_changes_during_render_are_rejected(self):
        from quick_emerge_plugin import reporting
        original=reporting._charts
        def changed(*args):
            self.board.write_text('(changed while rendering)')
            return original(*args)
        with patch.object(reporting,'_charts',changed),self.assertRaisesRegex(ValueError,'stale'):
            build_html_report(self.result)

    def test_radiation_validation_zero_pattern_and_known_pattern(self):
        r=deepcopy(self.result)
        r['radiation']={'theta_rad':[0,1,2,3.141592653589793],'phi_rad':[-3.141592653589793,0,3.141592653589793],
                        'norm_e':[[0,0,0]]*4,'frequency_hz':r['frequencies_hz'][1]}
        document=build_html_report(r,include_figures=True)
        self.assertIn('All recorded far-field magnitudes are zero',document)
        r['radiation']['norm_e']=[[1,1,1]]*4
        document=build_html_report(r,include_figures=True)
        parsed=_AssetInspector();parsed.feed(document)
        self.assertGreaterEqual(len(parsed.images),6)
        r['radiation']['norm_e']=[[1]]
        with self.assertRaises(ValueError):validate_report_result(r)


    def test_real_thermal_contract_without_fictitious_rf(self):
        r=deepcopy(self.result)
        r['config']=validate_config({**r['config'],'advanced':{'study':'thermal'}})
        r['config_sha256']=config_digest(r['config'])
        r.update(model_scope='substrate-thermal-template',port_count=0,s_parameters={},frequencies_hz=[])
        r.pop('field')
        r['thermal']={'temperature_k':[[293.15,300,None],[293.15,301,302]],'x_mm':[-1,0,1],'y_mm':[-1,1],
                      'z_mm':-.000001,'peak_k':302,'reference_peak_k':303,'time_s':0,'heat_source_w_m3':1000,
                      'reference_scope':'1D steady slab'}
        self.assertIsNone(validate_report_result(r))
        document=build_html_report(r,probes=[{'x_mm':1,'y_mm':-1}],line_profile={'start':[-1,1],'end':[1,1],'count':3})
        self.assertIn('Peak sampled temperature [K]',document)
        self.assertNotIn('Complete sampled S matrix',document)
        self.assertNotIn('20 log10 |S|',document)
        parsed=_AssetInspector();parsed.feed(document)
        evidence=json.loads(base64.b64decode(parsed.downloads[0].split(',',1)[1]))
        self.assertIn('value_k',evidence['report_selections']['probes'][0])
        self.assertNotIn('frequency_hz',evidence['report_selections']['probes'][0])
        self.assertGreaterEqual(len(parsed.images),3)
        invalid=deepcopy(r);invalid['thermal']['peak_k']=999
        with self.assertRaises(ValueError):validate_report_result(invalid)
        invalid=deepcopy(r);invalid['thermal']['temperature_k'][0][0]=float('nan')
        with self.assertRaises(ValueError):validate_report_result(invalid)

    def test_scattering_contract_rcs_and_step_custody(self):
        r=deepcopy(self.result)
        r['config']=validate_config({**r['config'],'advanced':{'study':'scattering'}})
        r['config_sha256']=config_digest(r['config'])
        r.update(model_scope='pec-sphere-scattering',port_count=0,s_parameters={})
        r['scattering']={'frequency_hz':r['frequencies_hz'][1],'theta_rad':[0,1,3.141592653589793],
                         'phi_rad':[-3.141592653589793,0,3.141592653589793],
                         'rcs_m2':[[0,.1,.2],[.3,.4,.5],[.6,.7,.8]],'incident_power_w_m2':1}
        self.assertIsNone(validate_report_result(r))
        document=build_html_report(r)
        self.assertIn('Maximum sampled bistatic RCS [m²]',document)
        self.assertNotIn('Complete sampled S matrix',document)
        invalid=deepcopy(r);invalid['scattering']['rcs_m2'][0][0]=-1
        with self.assertRaises(ValueError):validate_report_result(invalid)
        step=self.root/'shape.step';step.write_text('STEP')
        import hashlib
        r['import_source']={'path':str(step),'sha256':hashlib.sha256(step.read_bytes()).hexdigest(),'coordinate_scale_m':.001}
        validate_report_result(r)
        step.write_text('STEP changed')
        with self.assertRaisesRegex(ValueError,'stale'):validate_report_result(r)

    def test_periodic_uses_actual_reference_and_optimization_best_geometry(self):
        r=deepcopy(self.result)
        r['config']=validate_config({**r['config'],'advanced':{'study':'periodic'}})
        r['config_sha256']=config_digest(r['config'])
        r.update(model_scope='periodic-patch-template',reference_impedance_ohm=376.730313668)
        network=validate_report_result(r)
        self.assertAlmostEqual(network.z0_ohm[0],376.730313668)
        document=build_html_report(r)
        self.assertIn('376.7303',document)
        self.assertIn('Periodic unit-cell geometry',document)
        r=deepcopy(self.result)
        best=deepcopy(r['config']);best['line_width_mm']=2.1
        r['config']=validate_config({**r['config'],'advanced':{'study':'optimization'}})
        r['config_sha256']=config_digest(r['config'])
        r['optimization']={'best_config':best,'best_dimension_mm':2.1,'samples':[],'objective':'minimize worst sampled |S11|²'}
        document=build_html_report(r)
        self.assertIn('best recorded driven configuration',document)
        self.assertIn('2.1',document)

    def test_selection_recomputed_quantities_and_volume(self):
        r=deepcopy(self.result); field=r['field']
        field['norm_h_a_m']=[[2,3,4],[5,6,7],[8,9,10]]
        field['poynting_w_m2']=[[[3]*3 for _ in range(3)],[[4]*3 for _ in range(3)],[[0]*3 for _ in range(3)]]
        field['volume']={'x_mm':[-1,0,1],'y_mm':[-1,0,1],'z_mm':[1,2],
                         'norm_e_v_m':[[[10]*3 for _ in range(3)],[[20]*3 for _ in range(3)]],
                         'h_real_a_m':[[[[1]*3 for _ in range(3)],[[3]*3 for _ in range(3)]]]+[[[[0]*3 for _ in range(3)] for _ in range(2)] for _ in range(2)],
                         'h_imag_a_m':[[[[0]*3 for _ in range(3)] for _ in range(2)] for _ in range(3)]}
        field['volume']['poynting_w_m2']=[[[[v]*3 for _ in range(3)] for _ in range(2)] for v in (3,4,0)]
        probes=[{'kind':'field','x_mm':0,'y_mm':0,'quantity':'H magnitude','iz':1,'value_a_m':999},
                {'kind':'field','x_mm':0,'y_mm':0,'quantity':'Power-flow magnitude','value_w_m2':999},
                {'kind':'radiation'},{'kind':'network'}]
        doc=build_html_report(r,probes=probes,include_figures=False)
        parsed=_AssetInspector();parsed.feed(doc);e=json.loads(base64.b64decode(parsed.downloads[0].split(',',1)[1]))
        values=e['report_selections']['probes'];self.assertEqual(len(values),2)
        self.assertEqual((values[0]['value_a_m'],values[0]['z_mm'],values[0]['iz']),(3,2,1))
        self.assertEqual(values[1]['value_w_m2'],5)
        self.assertIn('A/m',doc);self.assertIn('W/m2',doc)

    def test_coupled_thermal_and_derived_custody(self):
        from quick_emerge_plugin.network import from_result
        from quick_emerge_plugin.network_extensions import serialize_network
        import hashlib
        r=deepcopy(self.result)
        r['thermal']={'x_mm':[-1,0,1],'y_mm':[-1,1],'z_mm':-.01,'temperature_k':[[300,301,None],[302,303,304]],'peak_k':304,'time_s':0,'coupling':'dielectric RF loss','rf_frequency_hz':r['frequencies_hz'][1],'rf_input_power_w':1,'reference_scope':'Nonuniform dielectric RF losses; uniform-slab analytic reference does not apply'}
        saved=self.root/'result.json';saved.write_text(json.dumps(r),encoding='utf-8')
        network=from_result(r)
        derived={'schema':1,'kind':'derived-network','source_result':{'path':str(saved),'sha256':hashlib.sha256(saved.read_bytes()).hexdigest()},'source_board':r['source'],'original_network_sha256':network.digest(),'derived_network':serialize_network(network),'operation':{'type':'test'},'diagnostics':{},'fit':None,'limits':['No convergence claim']}
        doc=build_html_report(r,derived_network=derived,probes=[{'kind':'field','x_mm':0,'y_mm':1,'quantity':'Temperature','temperature_k':999}],include_figures=True)
        self.assertIn('dielectric RF heating only',doc);self.assertIn('temperature [K]',doc);self.assertIn('Derived network postprocessing',doc)
        parsed=_AssetInspector();parsed.feed(doc);self.assertEqual(len(parsed.downloads),2)
        payloads=[json.loads(base64.b64decode(link.split(',',1)[1])) for link in parsed.downloads]
        e=next(item for item in payloads if 'report_selections' in item);self.assertEqual(e['report_selections']['probes'][0]['temperature_k'],303)
        self.assertIn(derived,payloads)
        saved.write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'): build_html_report(r,derived_network=derived,include_figures=False)

    def test_charted_pdf_offscreen(self):
        try: import reportlab
        except ImportError: self.skipTest('ReportLab unavailable')
        path=self.root/'chart.pdf'; export_pdf(path,self.result,include_figures=True)
        self.assertTrue(path.read_bytes().startswith(b'%PDF-'))
        self.assertGreater(path.stat().st_size,10000)

    def test_pdf_export_uses_shared_engine_and_is_parseable(self):
        try:
            import reportlab
            import pypdf
        except ImportError:
            self.skipTest('Optional ReportLab/pypdf unavailable')
        path=self.root/'study.pdf'
        export_pdf(path,self.result,include_figures=False)
        self.assertEqual(path.read_bytes()[:5],b'%PDF-')
        reader=pypdf.PdfReader(path)
        text='\n'.join(page.extract_text() for page in reader.pages)
        self.assertIn('Geometry and model scope',text)
        self.assertIn('No convergence qualification',text)
        self.assertIn(self.result['config_sha256'],text.replace('\n',''))


if __name__=='__main__':unittest.main()
