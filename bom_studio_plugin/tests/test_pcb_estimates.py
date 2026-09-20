from copy import deepcopy
from decimal import Decimal as D
import json
from pathlib import Path
import unittest
from test_core import Fixture, BASE
from bomstudio import analytics, analytics_exports
from bomstudio.pcb_estimates import estimate, validate
import test_http as base_http


class ProjectExportHttp(unittest.TestCase):
    setUpClass=classmethod(base_http.HTTPTests.setUpClass.__func__)
    tearDownClass=classmethod(base_http.HTTPTests.tearDownClass.__func__)
    request=base_http.HTTPTests.request

    def test_export_requires_auth(self):
        self.assertEqual(self.request('/api/analytics/save-project','POST',{},auth=False)[0],401)

    def test_export_uses_originating_project_not_client_destination(self):
        status,raw,_=self.request('/api/analytics/save-project','POST',{'config':{'pcb':{'mass_g':30}},'destination':'outside-project'})
        self.assertEqual(status,200)
        result=json.loads(raw)
        self.assertTrue(Path(result['folder']).is_relative_to(self.app.workspace.project.pro_path.parent))
        self.assertEqual(len(result['files']),4)


class PcbArithmetic(unittest.TestCase):
    def test_declared_layer_mass_and_setup_allocation(self):
        c=dict(area_mm2=10000,dielectric_mm=1.53,dielectric_density_g_cm3=1.85,
               copper_total_mm=.07,copper_coverage_percent=50,copper_density_g_cm3=8.96,
               unit_cost=2,setup_cost=30,quote_quantity=10,currency='USD')
        r=estimate(c,100,dict(status='complete',known_per_board=D('5')),
                   dict(eligible_components=1,missing_or_invalid_components=0,currencies={'USD':{'known_cost_per_board':D('4')}}))
        self.assertEqual(r['mass_g'],D('31.441'))
        self.assertEqual(r['assembly_mass_g'],D('36.441'))
        self.assertEqual(r['expected_unit_cost'],D('5'))
        self.assertEqual(r['expected_batch_cost'],D('50'))
        self.assertEqual(r['assembly_cost_per_board'],D('9'))

    def test_missing_coverage_and_currency_never_complete(self):
        r=estimate(dict(mass_g=10,unit_cost=2,setup_cost=0,currency='USD'),3,
                   dict(status='partial',known_per_board=D('5')),
                   dict(eligible_components=2,missing_or_invalid_components=0,currencies={'USD':{},'EUR':{}}))
        self.assertIsNone(r['assembly_mass_g']);self.assertIsNone(r['assembly_cost_per_board'])
        self.assertIn('Currency mismatch',r['warnings'][0])
        r=estimate({},1,dict(status='unknown'),dict(currencies={}))
        self.assertIsNone(r['mass_g']);self.assertIsNone(r['expected_unit_cost'])

    def test_bad_inputs(self):
        for config in ({'mass_g':True},{'unit_cost':'NaN'},{'area_mm2':-1},{'quote_quantity':1.5},
                       {'copper_coverage_percent':101},{'currency':'usd'},{'unknown':0}):
            with self.subTest(config=config),self.assertRaises(ValueError):validate(config)


class ProjectEstimates(Fixture):
    def test_staged_fields_coverage_dnp_and_project_exports(self):
        for row in self.ws.rows(BASE):self.ws.edit([row['id']],BASE,{'Mass':'2 g','UnitPrice':'3','Currency':'USD'})
        before=deepcopy(self.ws.state)
        report=analytics.run(self.ws,BASE,{'metrics':['pricing','mass'],'physical_include_bom_excluded':False,
                                        'boards':4,'pcb':{'mass_g':10,'unit_cost':5,'setup_cost':4,'currency':'USD'}})
        self.assertEqual(report['mass']['known_components'],report['mass']['eligible_components'])
        self.assertGreater(report['scope']['not_fitted_components'],0)
        self.assertEqual(D(report['pcb']['expected_unit_cost']),6)
        self.assertEqual(D(report['pcb']['assembly_mass_g']),D(report['mass']['known_per_board'])+10)
        result=analytics_exports.save_project_report(self.ws,report)
        self.assertTrue(Path(result['folder']).is_relative_to(self.dir/'reports'/'wayricad-bom'))
        self.assertEqual(len(result['files']),4)
        loaded=json.loads(Path(result['folder'],'analysis.json').read_text(encoding='utf-8'))
        self.assertEqual(loaded['pcb']['expected_unit_cost'],'6')
        self.assertIn('Quoted PCB',Path(result['folder'],'summary.csv').read_text(encoding='utf-8-sig'))
        self.assertEqual(before,self.ws.state)
        second=analytics_exports.save_project_report(self.ws,report)
        self.assertNotEqual(second['folder'],result['folder'])

    def test_stale_saved_project_blocks_report_write(self):
        report=analytics.run(self.ws)
        self.path.write_text('{}',encoding='utf-8')
        with self.assertRaises(Exception):analytics_exports.save_project_report(self.ws,report)
