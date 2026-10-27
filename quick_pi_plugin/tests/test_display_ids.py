"""Human PI labels are deterministic presentation, never new solver identities."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quick_pi_plugin.display_ids import DisplayIDs,display_label,display_result,prepare_display_ids
from quick_pi_plugin.report import inspection_record,write_report,interactive_fields
from quick_pi_plugin.inspector_tables import heating_rows,probe_rows
from quick_pi_plugin.tests.test_report import bundle


def vias():
    return {'geometry':{'vias':[{'id':'raw-b','x_mm':1,'y_mm':4},{'id':'raw-a','x_mm':2,'y_mm':1},
                                {'id':'raw-coincident','x_mm':2,'y_mm':1}]},
            'mesh':{'vias':[{'id':'raw-b:0-31','x_mm':1,'y_mm':4},
                            {'id':'raw-a:0-2','x_mm':2,'y_mm':1},
                            {'id':'raw-a:2-31','x_mm':2,'y_mm':1},
                            {'id':'raw-coincident:0-31','x_mm':2,'y_mm':1}]}}


class DisplayIDTests(unittest.TestCase):
    def test_physical_segments_order_stability_and_coincident_identity(self):
        original=vias();before=copy.deepcopy(original)
        labels=DisplayIDs(original)
        self.assertEqual(labels.label('via','raw-a:0-2'),'V1')
        self.assertEqual(labels.label('via','raw-a:2-31'),'V1')
        self.assertEqual(labels.label('via','raw-coincident:0-31'),'V2')
        self.assertEqual(labels.label('via','raw-b:0-31'),'V3')
        reordered=copy.deepcopy(original)
        reordered['geometry']['vias'].reverse();reordered['mesh']['vias'].reverse()
        self.assertEqual(labels.metadata(),DisplayIDs(reordered).metadata())
        self.assertEqual(original,before)

    def test_unlinked_barrels_do_not_guess_physical_identity(self):
        b=vias();b['geometry']['vias']=[]
        labels=DisplayIDs(b)
        self.assertNotEqual(labels.label('via','raw-a:0-2'),labels.label('via','raw-a:2-31'))
        self.assertEqual(labels.label('sheet',0),'C1')
        self.assertEqual(labels.label('sheet',27374),'C27375')

    def test_prepared_via_and_cell_labels_do_not_rebuild_inventory(self):
        b=vias();prepare_display_ids(b)
        with patch('quick_pi_plugin.display_ids.DisplayIDs',side_effect=AssertionError('Do not sort on hover')):
            self.assertEqual(display_label(b,'via','raw-a:0-2'),'V1')
            self.assertEqual(display_label(b,'sheet',3),'C4')

    def test_probe_tables_and_rows_keep_raw_targets(self):
        b=bundle();before=copy.deepcopy(b)
        row=inspection_record(b,'sheet',3)
        self.assertEqual(row['id'],3);self.assertEqual(row['display_id'],'C4')
        rows=probe_rows(b,row)
        self.assertEqual(next(r for r in rows if r['cells'][0]=='Display ID')['cells'][1],'C4')
        shown=display_result(b)
        for original,presented in zip(b['result']['analytics']['hotspots_by_heating_density'],heating_rows(shown)):
            self.assertEqual(presented['target']['id'],original['id'])
            self.assertIn('C'+str(original['id']+1),presented['cells'][0])
        self.assertIs(shown['potential_V'],b['result']['potential_V'])
        self.assertEqual(b,before)

    def test_html_and_json_have_same_via_mapping_with_original_ids(self):
        b=bundle();b['geometry']['layers'].append({'id':31,'name':'B.Cu','polygons':[]})
        b['geometry']['vias']=[{'id':'original-via-uuid','x_mm':5,'y_mm':.5}]
        b['mesh']['vias']=[{'id':'original-via-uuid:0-31','top_layer':0,'bottom_layer':31,'x_mm':5,'y_mm':.5}]
        b['result']['vias']=[{'id':'original-via-uuid:0-31','current_A':1,'current_density_A_mm2':100,'power_W':.001,'thermal':{}}]
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'report.html'
            with patch('quick_pi_plugin.report._report_snapshot',return_value=''):
                output=write_report(path,b)
            html=path.read_text(encoding='utf-8');data=json.loads(Path(output['json']).read_text(encoding='utf-8'))
            self.assertIn('V1 · F.Cu → B.Cu',html)
            self.assertEqual(data['display_identifiers']['via_labels']['original-via-uuid:0-31'],'V1')
            self.assertEqual(data['result']['vias'][0]['id'],'original-via-uuid:0-31')
            self.assertNotIn('display_identifiers',b)
        self.assertIn(' C1"',interactive_fields(b,0))


if __name__=='__main__':unittest.main()
