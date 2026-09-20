"""Safety and layout regressions for integrated test point editing."""
import unittest
from signal_integrity_advisor_plugin.testpoint_labels import make_plan,table_layout

class TestPointPlans(unittest.TestCase):
    def record(self,**changes):
        row=dict(id='id',reference='TP1',value='TestPoint',nets=['/Power/VDD'],x_mm=2,y_mm=3,locked=False);row.update(changes);return row
    def test_only_testpoints_selected(self):
        rows=make_plan([self.record(),self.record(id='ic',reference='U1')]);self.assertEqual([r['reference'] for r in rows],['TP1']);self.assertEqual(rows[0]['proposed'],'/Power/VDD')
    def test_locked_and_multinet_excluded(self):
        for row in (self.record(locked=True),self.record(nets=['VCC','GND']),self.record(nets=[''])):
            self.assertTrue(make_plan([row])[0]['reason'])
    def test_repeated_same_net_is_unambiguous(self):self.assertFalse(make_plan([self.record(nets=['VDD','VDD'])])[0]['reason'])
    def test_edit_overrides_template(self):self.assertEqual(make_plan([self.record()],overrides={'id':'RAIL'})[0]['proposed'],'RAIL')
    def test_reference_and_net_template(self):self.assertEqual(make_plan([self.record()],template='{ref}: {net}')[0]['proposed'],'TP1: /Power/VDD')
    def test_invalid_template_rejected(self):
        with self.assertRaises(ValueError):make_plan([self.record()],template='{missing}')
    def test_control_character_and_empty_values_excluded(self):
        for value in ('','bad\nname','x'*161):self.assertTrue(make_plan([self.record()],overrides={'id':value})[0]['reason'])
    def test_table_uses_reviewed_valid_rows_and_coordinates(self):
        rows=make_plan([self.record(),self.record(id='2',reference='TP2',locked=True)])
        cells=table_layout(rows,10,20);self.assertEqual(len(cells),4);self.assertEqual(cells[0]['x_mm'],10);self.assertEqual(cells[2]['y_mm'],21.8)
    def test_table_rejects_bad_size_and_coordinates(self):
        for xyz in ((0,0,0),(float('nan'),0,1),(0,float('inf'),1),(0,0,11)):
            with self.assertRaises(ValueError):table_layout(make_plan([self.record()]),*xyz)
    def test_no_empty_table(self):
        with self.assertRaises(ValueError):table_layout([],0,0)

if __name__=='__main__':unittest.main()
