import unittest
from wayricad_runtime.net_filter import matching_nets, filter_combo
from signal_integrity_advisor_plugin.plot_probe import sample_at
class InteractionTests(unittest.TestCase):
 def test_filter_keeps_identity_even_when_query_hides_it(self):
  class Combo:
   def __init__(self):self.value='CAN_P';self.names=[]
   def GetValue(self):return self.value
   def Set(self,names):self.names=names;self.value=''
   def SetValue(self,value):self.value=value
   def SetSelection(self,index):self.value=self.names[index] if index >= 0 else ''
  combo=Combo()
  filter_combo(combo,['CAN_P','CAN_N'],'can')
  self.assertEqual(combo.value,'CAN_P')
  filter_combo(combo,['CAN_P','CAN_N'],'missing')
  self.assertEqual(combo.value,'CAN_P')
  self.assertEqual(combo.names,['CAN_P'])
  self.assertNotIn('missing',combo.names)

 def test_net_search_literals_globs_and_opt_in_fuzzy(self):
  names=['DATA[0]','DATA[1]','CLOCK_P','POWER']
  self.assertEqual(matching_nets(names,'data[0]'),['DATA[0]'])
  self.assertEqual(matching_nets(names,'DATA[*]'),['DATA[0]','DATA[1]'])
  self.assertEqual(matching_nets(names,'CLK'),[])
  self.assertEqual(matching_nets(names,'~CLOK'),['CLOCK_P'])
  self.assertEqual(matching_nets(names,'CLOK',mode='fuzzy'),['CLOCK_P'])
 def test_net_filter(self):
  self.assertEqual(matching_nets(['CAN_P','can_N','VCC'],'can'),['CAN_P','can_N'])
  self.assertEqual(matching_nets(['CAN_P'],'missing'),[])
 def test_probe_existing_samples(self):
  self.assertEqual(sample_at([0,1,2],[[0,2,4],[0,3,6]],1.2,2.9),dict(sample=1,trace=1,x=1,voltage_v=3))
  self.assertIsNone(sample_at([],[],0,0))
  self.assertIsNone(sample_at([0],[[None]],0,0))
  self.assertEqual(sample_at([0,1],[[2,4]],.5,3)['sample'],0)
if __name__=='__main__':unittest.main()
