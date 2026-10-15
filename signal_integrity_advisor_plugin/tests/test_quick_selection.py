"""Quick SI explicit IPC navigation and conservative reverse-input mapping."""
import unittest
from types import SimpleNamespace as NS
try:
 import wx
except ImportError:
 wx=None

@unittest.skipIf(wx is None,'Native wx is required')
class SelectionPlanningTests(unittest.TestCase):
 def test_current_net_preferred_over_selected_returns(self):
  from signal_integrity_advisor_plugin.quick_ui import reverse_selection_plan
  plan,message=reverse_selection_plan('DATA',{'DATA':['U1.1','J1.1'],'GND':['U1.2']},'U1.1','OLD.1')
  self.assertEqual(plan['net'],'DATA');self.assertEqual(plan['roles'],{'start':'U1.1','end':'J1.1'})
 def test_two_unrelated_nets_do_not_pick_arbitrary_signal(self):
  from signal_integrity_advisor_plugin.quick_ui import reverse_selection_plan
  plan,message=reverse_selection_plan('OTHER',{'DATA':['U1.1'],'GND':['U1.2']},'','')
  self.assertIsNone(plan);self.assertIn('multiple nets',message)
 def test_new_signal_or_unoriented_pads_leave_direction_unknown(self):
  from signal_integrity_advisor_plugin.quick_ui import reverse_selection_plan
  plan,message=reverse_selection_plan('OTHER',{'DATA':['U1.1','J1.1']},'OLD.1','OLD.2')
  self.assertEqual(plan['net'],'DATA');self.assertEqual(plan['roles'],{})
  self.assertIn('direction is unresolved',message)
 def test_no_selected_terminal_never_infers_direction_from_track(self):
  from signal_integrity_advisor_plugin.quick_ui import reverse_selection_plan
  plan,message=reverse_selection_plan('DATA',{'DATA':[]},'U1.1','J1.1');self.assertEqual(plan['roles'],{})
 def test_item_pick_captures_uuid_on_caller_thread(self):
  from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
  calls=[];panel=NS(_navigate=lambda *args,**kwargs:calls.append((args,kwargs)))
  QuickSIPanel._pick_route_item(panel,('DATA',NS(m_Uuid=NS(AsString=lambda:'uuid'))))
  self.assertEqual(calls,[(('select',),{'identifiers':['uuid']})])
 def test_stale_navigation_does_not_apply_inputs(self):
  from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
  calls=[];panel=NS(_closed=False,_navigation_serial=1,_navigation_busy=True,_generation=4,_navigation_buttons=lambda:calls.append('buttons'))
  QuickSIPanel._navigation_finished(panel,1,3,'read',['uuid'],None)
  self.assertFalse(panel._navigation_busy);self.assertEqual(calls,['buttons'])
if __name__=='__main__':unittest.main()
