"""Native source/sink recommendations feed the grouped electrical contract."""
import unittest
from unittest.mock import patch

from quick_pi_plugin.tests import test_live_ui as live_tests
from quick_pi_plugin.tests.test_pin_units import terminals


@unittest.skipIf(live_tests.wx is None,'Native KiCad wx runtime required')
class PinRecommendationUITests(unittest.TestCase):
    setUp=live_tests.LiveUITests.setUp
    tearDown=live_tests.LiveUITests.tearDown
    until=live_tests.LiveUITests.until

    def setup_pins(self):
        frame=self.frame
        frame.inventory={'terminals':terminals(),'nets':['VCC','GND']}
        frame.net.Set(['VCC','GND']);frame.net.SetValue('VCC');frame._set_terminals()
        source=next(i for i,row in enumerate(frame._terminals) if row['id']=='a')
        sink=next(i for i,row in enumerate(frame._terminals) if row['id']=='s')
        frame.source.SetSelection(source);frame.sink.SetSelection(sink)
        frame._sync_pin_recommendations()
        return frame

    def test_checkboxes_appear_only_for_real_peers_and_preserve_one_total_load(self):
        frame=self.setup_pins()
        self.assertTrue(frame.source_pins.IsShown());self.assertTrue(frame.sink_pins.IsShown())
        self.assertFalse(frame.source_pins.GetValue());self.assertFalse(frame.sink_pins.GetValue())
        frame.source_pins.SetValue(True);frame.sink_pins.SetValue(True)
        frame._invalidate()
        request=frame._request('solve')
        self.assertEqual(request['source_terminals'],['a','b','c'])
        self.assertNotIn('source_terminal',request)
        self.assertEqual(request['sinks'][0]['terminals'],['s','t'])
        self.assertEqual(request['sinks'][0]['current_A'],float(frame.current.GetValue()))
        self.assertNotIn('terminal',request['sinks'][0])
        self.assertEqual(frame.bundle['request']['source_terminals'],['a','b','c'])
        frame.source_pins.SetValue(False);frame.sink_pins.SetValue(False);frame._invalidate()
        self.assertNotIn('source_terminals',frame.bundle['request'])
        self.assertEqual(frame._request('solve')['sinks'][0]['terminal'],'s')

    def test_alone_selection_net_and_unsupported_modes_clear_stale_groups(self):
        frame=self.setup_pins();frame.source_pins.SetValue(True);frame._invalidate()
        index=next(i for i,row in enumerate(frame._terminals) if row['id']=='alone')
        frame.source.SetSelection(index);frame._sync_pin_recommendations()
        self.assertFalse(frame.source_pins.IsShown());self.assertFalse(frame.source_pins.GetValue())
        frame.model_dimension.SetSelection(1);frame._sync_pin_recommendations()
        self.assertFalse(frame.sink_pins.IsShown());self.assertFalse(frame.sink_pins.GetValue())
        frame.model_dimension.SetSelection(0);frame.net.SetValue('GND');frame._set_terminals()
        self.assertFalse(frame.source_pins.IsShown());self.assertFalse(frame.sink_pins.IsShown())

    def test_additional_sink_group_reserves_all_its_pins(self):
        frame=self.setup_pins()
        frame._extra_sinks=[{'id':'b','terminals':['b','c'],'current_A':.5}]
        frame._sync_pin_recommendations()
        self.assertFalse(frame.source_pins.IsShown())
        request=frame._request('solve')
        self.assertEqual(request['sinks'][1]['terminals'],['b','c'])
        self.assertEqual(request['sinks'][1]['current_A'],.5)

    def test_power_and_current_sinks_keep_their_units_and_groups(self):
        frame=self.setup_pins();frame.load_mode.SetSelection(2);frame.current.ChangeValue('2.5')
        frame.source_pins.SetValue(True);frame.sink_pins.SetValue(True)
        frame._extra_sinks=[{'terminal':'alone','current_A':.4}]
        frame._invalidate();request=frame._request('solve')
        self.assertEqual(request['source_terminals'],['a','b','c'])
        self.assertEqual(request['sinks'][0]['terminals'],['s','t'])
        self.assertEqual(request['sinks'][0]['power_W'],2.5)
        self.assertNotIn('current_A',request['sinks'][0])
        self.assertEqual(request['sinks'][1],{'terminal':'alone','current_A':.4})
        self.assertNotIn('load_power_W',request)

    def test_additional_sink_dialog_recommends_and_saves_a_group(self):
        frame=self.setup_pins();wx=live_tests.wx
        # Primary load uses R1.1, leaving U1's same-net pads for another sink.
        frame.sink.SetSelection(next(i for i,row in enumerate(frame._terminals) if row['id']=='alone'))
        frame._sync_pin_recommendations()
        def interact(dialog):
            from wayricad_runtime.readable_choice import ReadableChoice
            choice=next(child for child in dialog.GetChildren() if isinstance(child,ReadableChoice))
            choice.SetSelection(next(i for i,row in enumerate(frame._terminals) if row['id']=='s'))
            event=wx.CommandEvent(wx.EVT_CHOICE.typeId,choice.GetId());event.SetEventObject(choice)
            choice.GetEventHandler().ProcessEvent(event)
            checkbox=next(child for child in dialog.GetChildren() if isinstance(child,wx.CheckBox))
            self.assertTrue(checkbox.IsShown());checkbox.SetValue(True)
            button=next(child for child in dialog.GetChildren() if isinstance(child,wx.Button) and child.GetLabel()=='Add sink')
            click=wx.CommandEvent(wx.EVT_BUTTON.typeId,button.GetId());click.SetEventObject(button)
            button.GetEventHandler().ProcessEvent(click)
            return wx.ID_OK
        with patch.object(wx.Dialog,'ShowModal',interact):frame.on_loads()
        self.assertEqual(frame._extra_sinks[0]['terminals'],['s','t'])
        self.assertEqual(frame._extra_sinks[0]['current_A'],1.)


if __name__=='__main__':unittest.main()
