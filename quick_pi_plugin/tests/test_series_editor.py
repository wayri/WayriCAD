import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quick_pi_plugin.console import parse_command
from quick_pi_plugin.series_editor import build_command,compatible_components,selected_component_references


INVENTORY={'nets':['VIN','MID','LOAD'],'terminals':[
    {'id':'source','label':'J1.1','net':'VIN'},
    {'id':'d1a','label':'D1.1','net':'VIN'},
    {'id':'d1b','label':'D1.2','net':'MID'},
    {'id':'r1a','label':'R1.1','net':'MID'},
    {'id':'r1b','label':'R1.2','net':'LOAD'},
    {'id':'sink','label':'U1.1','net':'LOAD'}]}


class SeriesEditorModelTests(unittest.TestCase):
    def test_compatible_parts_follow_actual_net_chain(self):
        self.assertEqual(compatible_components(INVENTORY,'VIN'),[('D1','MID')])
        self.assertEqual(compatible_components(INVENTORY,'MID',{'D1'}),[('R1','LOAD')])

    def test_editor_builds_same_request_as_console(self):
        command=build_command('J1.1','U1.1',[{'reference':'D1','model':'1V'},
                                             {'reference':'R1','model':'5m'}])
        request=parse_command(command,INVENTORY)
        self.assertEqual([row['id'] for row in request['series']],['D1','R1'])
        self.assertEqual(request['series'][0]['fixed_drop_v'],1.)
        self.assertEqual(request['series'][1]['resistance_ohm'],.005)

    def test_reordered_broken_path_is_rejected(self):
        command=build_command('J1.1','U1.1',[{'reference':'R1','model':'5m'},
                                             {'reference':'D1','model':'1V'}])
        with self.assertRaisesRegex(ValueError,'direction|disconnected'):
            parse_command(command,INVENTORY)

    def test_selected_footprints_are_available_to_editor(self):
        footprint=SimpleNamespace(reference_field=SimpleNamespace(text=SimpleNamespace(value='D1')))
        with patch('quick_pi_plugin.series_editor._editor_selection',return_value=[footprint,footprint]):
            self.assertEqual(selected_component_references('board.kicad_pcb'),['D1'])


if __name__=='__main__':unittest.main()
