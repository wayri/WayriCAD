"""Explicit arbitrary pad memberships on a shared connector and net."""
import unittest
from unittest.mock import patch

from quick_pi_plugin.sink_groups import ordered_pads, reserved_pads


def inventory():
    return [{'id':key, 'label':'J1.'+str(index+1), 'net':'VCC', 'footprint_uuid':'connector'}
            for index,key in enumerate(('src','a','b','c','d','e','f'))]


class MembershipTests(unittest.TestCase):
    def test_anchor_and_conflicting_groups(self):
        rows=inventory()
        extras=[{'id':'step-load','terminals':['b','c'],'current_A':1.5}]
        occupied=reserved_pads(['src'], ['a','d'], extras)
        self.assertEqual(ordered_pads(['f','e'],'e',rows,occupied), ['e','f'])
        for candidate in (['src','f'],['a','f'],['b','f'],['f','f'],['gone']):
            with self.assertRaises(ValueError):
                ordered_pads(candidate,'f',rows,occupied)
        self.assertEqual(reserved_pads(['src'], ['a','d'], extras,editing=0), {'src','a','d'})

    def test_filtered_picker_excludes_reserved_ids_and_cancel_keeps_input(self):
        try:
            from quick_pi_plugin.sink_groups import choose_pads
            from quick_pi_plugin import pi_return_setup
        except ImportError as exc:
            self.skipTest(str(exc))
        rows=inventory()
        checked=['c','b']
        with patch.object(pi_return_setup,'choose_pad_unit',return_value=None) as picker:
            self.assertIsNone(choose_pads(None,rows,checked,{'src','a'},'c'))
        _, available, net, passed=picker.call_args.args
        self.assertEqual({row['id'] for row in available['terminals']},{'b','c','d','e','f'})
        self.assertEqual(passed,checked)
        self.assertEqual(net,'VCC')


class NativeGroupEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import wx
            from quick_pi_plugin.ui import QuickPIFrame
        except ImportError as exc:
            raise unittest.SkipTest(str(exc))
        cls.wx=wx
        cls.frame_class=QuickPIFrame
        cls.app=wx.App.Get() or wx.App(False)

    def test_same_connector_subset_edits_apply_and_cancel(self):
        wx=self.wx
        f=wx.Frame(None)
        f._busy=False;f._series_request=None
        f._extra_sinks=[{'id':'dynamic','label':'DSP','terminals':['c','d'],'current_A':.25}]
        f._terminals=inventory()
        labels=[r['label'] for r in f._terminals]
        f.source=wx.Choice(f,choices=labels);f.source.SetSelection(0)
        f.sink=wx.Choice(f,choices=labels);f.sink.SetSelection(1)
        f.model_dimension=wx.Choice(f,choices=['2.5D']);f.model_dimension.SetSelection(0)
        f.load_mode=wx.Choice(f,choices=['Current']);f.load_mode.SetSelection(0)
        f.loads_button=wx.Button(f)
        changes=[]
        f._invalidate=lambda:None
        f._set_primary_sink_pads=changes.append

        def drive(dialog, outcome):
            controls=dialog.GetChildren()
            table=next(w for w in controls if isinstance(w,wx.ListCtrl))
            current=next(w for w in controls if isinstance(w,wx.TextCtrl))
            def press(label):
                b=next(w for w in controls if isinstance(w,wx.Button) and w.GetLabel()==label)
                ev=wx.CommandEvent(wx.EVT_BUTTON.typeId,b.GetId());ev.SetEventObject(b)
                b.GetEventHandler().ProcessEvent(ev)
            table.Select(0)
            ev=wx.ListEvent(wx.EVT_LIST_ITEM_SELECTED.typeId, table.GetId());ev.SetIndex(0);ev.SetEventObject(table)
            table.GetEventHandler().ProcessEvent(ev)
            current.ChangeValue('.5')
            press('Update selected')
            # Editing current alone must retain the original subset.
            self.assertEqual(table.GetItemText(0), 'J1.4, J1.5')
            with patch('quick_pi_plugin.pi_return_setup.choose_pad_unit', return_value=['b','a']):
                press('Primary sink pads…')
            with patch('quick_pi_plugin.pi_return_setup.choose_pad_unit', return_value=['e','f']):
                press('Choose pads…')
            current.ChangeValue('.75')
            press('Add sink')
            self.assertEqual(table.GetItemCount(),2)
            return outcome
        try:
            for outcome in (wx.ID_CANCEL,wx.ID_OK):
                with patch.object(wx.Dialog,'ShowModal',lambda dialog:drive(dialog,outcome)):
                    self.frame_class.on_loads(f)
                if outcome==wx.ID_CANCEL:
                    self.assertEqual(changes,[])
                    self.assertEqual(len(f._extra_sinks),1)
                    self.assertEqual(f._extra_sinks[0]['current_A'],.25)
            self.assertEqual(changes,[['a','b']])
            self.assertEqual(f._extra_sinks,[
                {'current_A':.5,'id':'dynamic','label':'DSP','terminals':['c','d']},
                {'current_A':.75,'id':'e','terminals':['e','f']}])
        finally:
            f.Destroy()
