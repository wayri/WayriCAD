"""Analytical geometry and integration checks; all observations are synthetic."""
import math
import unittest
from decimal import Decimal as D
from bomstudio.component_analytics import courtyard_area, pad_areas, histogram, board_geometry
from bomstudio.sexpr import parse, quote
from bomstudio import analytics as a, analytics_exports as ex
from bomstudio.native import BASE
from test_core import Fixture


class GeometryTests(unittest.TestCase):
    def fp(self, body):
        return parse('(footprint "test" '+body+')')

    def test_closed_courtyard_rectangle_and_polygon(self):
        for shape in ('(fp_rect (start -2 -1) (end 2 1) (layer "F.CrtYd"))',
                      '(fp_poly (pts (xy -2 -1) (xy 2 -1) (xy 2 1) (xy -2 1)) (layer "F.CrtYd"))'):
            self.assertEqual(courtyard_area(self.fp(shape),'F.CrtYd'),D(8))

    def test_unordered_line_loop(self):
        body=''.join('(fp_line (start %s) (end %s) (layer "B.CrtYd"))'%(a,b) for a,b in [('0 0','2 0'),('0 1','0 0'),('2 1','0 1'),('2 0','2 1')])
        self.assertEqual(courtyard_area(self.fp(body),'B.CrtYd'),D(2))

    def test_bad_courtyard_unknown(self):
        for body in ('', '(fp_line (start 0 0) (end 2 0) (layer "F.CrtYd"))',
                     '(fp_poly (pts (xy 0 0) (xy 2 2) (xy 0 2) (xy 2 0)) (layer "F.CrtYd"))',
                     '(fp_circle (center 0 0) (end 1 0) (layer "F.CrtYd"))'):
            with self.subTest(body=body),self.assertRaises(ValueError):courtyard_area(self.fp(body),'F.CrtYd')

    def test_pad_shapes_analytic_areas(self):
        for shape,size,extra,expected in [('rect','2 1','',2),('circle','2 2','',math.pi),
            ('oval','3 2','',2+math.pi),('roundrect','2 1','(roundrect_rratio .25)',2-(4-math.pi)*.25**2)]:
            fp=self.fp('(pad "1" smd %s (at 0 0 47) (size %s) (layers "F.Cu") %s)'%(shape,size,extra))
            self.assertAlmostEqual(float(pad_areas(fp,'F.Cu')),expected,places=12)

    def test_hole_subtraction_and_side_filtering(self):
        fp=self.fp('(pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu")) (pad "2" smd rect (at 10 0) (size 2 2) (layers "B.Cu")) (pad "" np_thru_hole circle (at 20 0) (size 4 4) (drill 4) (layers "*.Cu"))')
        self.assertAlmostEqual(float(pad_areas(fp,'F.Cu')),math.pi*.75,places=12)
        self.assertAlmostEqual(float(pad_areas(fp,'B.Cu')),math.pi*.75+4,places=12)

    def test_unsupported_and_overlapping_are_not_summed(self):
        for body in ('(pad "1" smd custom (at 0 0) (size 2 2) (layers "F.Cu"))',
                     '(pad "1" smd rect (at 0 0) (size 2 2) (layers "F.Cu")) (pad "2" smd rect (at 1 0) (size 2 2) (layers "F.Cu"))',
                     '(pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1 (offset .1 0)) (layers "*.Cu"))'):
            with self.subTest(body=body),self.assertRaises(ValueError):pad_areas(self.fp(body),'F.Cu')

    def test_histogram_conserves_counts_and_endpoints(self):
        values=[D(i)/10 for i in range(101)]
        bins=histogram(values)
        self.assertEqual(sum(b['count'] for b in bins),101)
        self.assertEqual((bins[0]['lower'],bins[-1]['upper']),(D(0),D(10)))
        self.assertEqual(histogram([D(2)]*3)[0]['count'],3)
        self.assertEqual(histogram([]),[])


class ComponentIntegrationTests(Fixture):
    def setUp(self):
        super().setUp()
        for ref in ('R1','R2'):
            self.edit(ref,{'CustomCost':'2','CustomMass':'100mg','CustomLoss':'250mW','CustomType':'Resistor'})
        self.config={'query':'Reference=R1 OR Reference=R2','price_field':'CustomCost','mass_field':'CustomMass','power_field':'CustomLoss','type_field':'CustomType','quote_date_field':''}

    def report(self):return a.run(self.ws,BASE,self.config)

    def group(self,r,level='family',label='Passives'):
        return next(g for g in r['component_analysis']['groups'] if g['level']==level and g['label']==label)

    def write_board(self, mismatch=False, missing=False):
        fps=[]
        for ref in ('R1','R2'):
            row=self.row(ref)
            path='/wrong' if mismatch else row['id']
            courtyard='' if missing and ref=='R2' else '(fp_rect (start -2 -1) (end 2 1) (layer "F.CrtYd"))'
            fps.append('(footprint %s (layer "F.Cu") (property "Reference" %s) (path %s) %s (pad "1" smd rect (at 0 0) (size 2 1) (layers "F.Cu")))'%(quote(row['fields']['Footprint']),quote(ref),quote(path),courtyard))
        self.path.with_suffix('.kicad_pcb').write_text('(kicad_pcb '+''.join(fps)+')',encoding='utf-8')

    def test_custom_mapping_and_totals_without_native_changes(self):
        before=dict(self.ws.project.hashes)
        a.configure(self.ws,self.config)
        self.assertEqual(a.defaults(self.ws)['power_field'],'CustomLoss')
        r=self.report();g=self.group(r)
        self.assertEqual((g['mass']['known_total'],g['power']['known_total']),('0.2','0.5'))
        self.assertEqual(g['costs']['INR']['known_total'],'4')
        self.assertEqual(self.group(r,'rollup','RLC combined')['power']['known_total'],'0.5')
        self.assertEqual(before,self.ws.project.hashes);self.ws.project.check_unchanged()

    def test_area_denominator_uses_only_matching_known_power(self):
        self.write_board(missing=True)
        self.edit('R2',{'CustomLoss':'10W'})
        g=self.group(self.report())
        self.assertEqual(g['power']['known_total'],'10.25')
        self.assertEqual(g['footprint_area_mm2']['paired_W_per_mm2'],'0.03125')
        self.assertEqual(g['footprint_area_mm2']['paired_components'],1)
        self.edit('R1',{'CustomLoss':''})
        self.assertIsNone(self.group(self.report())['footprint_area_mm2']['paired_W_per_mm2'])

    def test_geometry_identity_and_saved_hash(self):
        self.write_board();r=self.report()
        self.assertEqual(self.group(r)['pad_area_mm2']['known_total'],'4')
        self.write_board(mismatch=True);other=self.report()
        self.assertIsNone(self.group(other)['pad_area_mm2']['known_total'])
        self.assertNotEqual(r['fingerprint'],other['fingerprint'])

    def test_missing_board_keeps_costs_and_area_unknown(self):
        path=self.path.with_suffix('.kicad_pcb')
        if path.exists():path.unlink()
        r=self.report()
        self.assertEqual(r['component_analysis']['geometry_source']['status'],'unavailable')
        self.assertIsNone(self.group(r)['pad_area_mm2']['known_total'])
        self.assertEqual(self.group(r)['costs']['INR']['known_total'],'4')

    def test_dnp_and_bom_excluded_scope(self):
        self.edit('R1',{'in_bom':False})
        g=self.group(self.report())
        self.assertEqual((g['pricing_components'],g['physical_components']),(1,2))
        self.ws.set_population([self.row('R2')['id']],BASE,'DNI')
        g=self.group(self.report())
        self.assertEqual((g['pricing_components'],g['physical_components']),(0,1))

    def test_currency_separation_and_active_classification(self):
        self.edit('R2',{'Currency':'USD','CustomType':'IC'})
        r=self.report()
        self.assertEqual(self.group(r)['costs']['INR']['known_total'],'2')
        self.assertEqual(self.group(r,label='Actives')['costs']['USD']['known_total'],'2')

    def test_disabled_metrics_safe(self):
        self.config['metrics']=['mass']
        g=self.group(self.report())
        self.assertEqual(g['costs'],{})
        self.assertIsNone(g['power']['known_total'])

    def test_export_charts_and_family_table(self):
        self.write_board();r=self.report()
        self.assertIn('families',ex.tables(r))
        raw,_,_=ex.render(r,'html')
        self.assertIn(b'<svg',raw);self.assertIn(b'Passives',raw)
        raw,_,_=ex.render(r,'csv','families')
        self.assertIn(b'Paired pad power W',raw)
        r['component_analysis']['groups'][0]['label']='<script>alert(1)</script>'
        raw,_,_=ex.render(r,'html')
        self.assertNotIn(b'<script>alert(1)</script>',raw)


if __name__=='__main__':unittest.main()
