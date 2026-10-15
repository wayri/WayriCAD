"""Retain a whole reviewed PCB selection, with explicit additive navigation."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
try:
    from quick_pi_plugin import ui
except ImportError:
    ui=None


@unittest.skipIf(ui is None,'Native wxPython required')
class SelectionBatchTests(unittest.TestCase):
    def test_reverse_selection_keeps_all_ids_and_component_pad_context(self):
        chosen=[];messages=[]
        frame=NS(board_path='C:/Projects/Example/board.kicad_pcb',bundle={},
                 _board_scene={'primitives':[dict(uuid='pad',parent_uuid='fp',role='pad',layer=0),
                                              dict(uuid='track',role='track',layer=0)]},
                 metric=NS(GetSelection=lambda:0),status=NS(SetLabel=messages.append),
                 _origin_sha=lambda:None,_choose_inspection=lambda row,**kwargs:chosen.append(row),
                 _object_inspection=lambda row:dict(location_mm=[0,0],source_ids=[row['uuid']]),
                 _task=lambda operation,finish,message:finish(operation()))
        with patch('quick_pi_plugin.origin_selection.selected_origin_ids',return_value=['fp','track']),patch.object(ui,'probe_result',return_value=None):
            ui.QuickPIFrame._read_editor_selection(frame)
        self.assertEqual(chosen[0]['source_ids'],['fp','pad','track'])
        self.assertIn('primary hit',messages[-1])

    def test_additive_and_hash_options_are_captured_before_background_navigation(self):
        jobs=[];hashes=iter(['reviewed','changed'])
        frame=NS(board_path='C:/Projects/Example/board.kicad_pcb',_snapshot_current=lambda:True,
                 _origin_sha=lambda:next(hashes),inspector_add=NS(GetValue=lambda:True),
                 _task=lambda operation,*args:jobs.append(operation))
        with patch('quick_pi_plugin.origin_selection.select_origin',return_value=2) as navigate:
            ui.QuickPIFrame._select_ids(frame,['pad','track'])
            self.assertEqual(jobs[0](),2)
            self.assertEqual(navigate.call_args.kwargs,dict(expected_sha256='reviewed',focus=True,additive=True))
