import tempfile,types,sys,importlib,unittest
from pathlib import Path
from types import SimpleNamespace
root=Path(__file__).resolve().parents[1]; pkg=types.ModuleType('_fusion_selector_test');pkg.__path__=[str(root)];sys.modules[pkg.__name__]=pkg
s=importlib.import_module(pkg.__name__+'.schematic');sx=importlib.import_module(pkg.__name__+'.sexpr');model=importlib.import_module(pkg.__name__+'.model');board=importlib.import_module(pkg.__name__+'.board');engine=importlib.import_module(pkg.__name__+'.engine');netlist=importlib.import_module(pkg.__name__+'.netlist')
class SelectorTests(unittest.TestCase):
 def source(self,selector='Alternate'):
  base=['symbol',sx.q('Lib:Base'),['property',sx.q('Value'),sx.q('base')]]
  alternate=['symbol',sx.q('Alternate'),['property',sx.q('Value'),sx.q('selected')]]
  node=['symbol',['lib_id',sx.q('Lib:Base')],['lib_name',sx.q(selector)],['property',sx.q('Reference'),sx.q('R1')]]
  record=SimpleNamespace(node=node,lib_id='Lib:Base')
  source=SimpleNamespace(alias='A',sheets=[SimpleNamespace(tree=['kicad_sch',['lib_symbols',base,alternate]],symbols=[record])],symbols=[record],libraries={},lib_map={},power_names=set())
  return source,record
 def test_selected_instance_cache_is_frozen(self):
  source,record=self.source();s.gather_libraries(source)
  self.assertEqual(record.lib_id,'Alternate')
  self.assertEqual(sx.propval(source.libraries[record.lib_id],'Value'),'selected')
 def test_missing_selector_refused(self):
  source,record=self.source('Missing')
  with self.assertRaises(model.MergeError):s.gather_libraries(source)
class EmbeddedBoardTests(unittest.TestCase):
 def source(self,data=True):
  entry=['file',['name',sx.q('model.step')],['type','model'],['checksum',sx.q('same')]]
  if data:entry.append(['data','opaque'])
  stub=['file',['name',sx.q('model.step')],['type','model'],['checksum',sx.q('same')]]
  fp=['footprint','Lib:R',['embedded_files',stub],['model',sx.q('kicad-embed://model.step')]]
  return SimpleNamespace(alias='A',board=['kicad_pcb',['embedded_files',entry],fp]),fp
 def test_native_checksum_manifest_inherits_board_payload(self):
  embedded=importlib.import_module(pkg.__name__+'.embedded');source,fp=self.source()
  embedded.namespace_board(source)
  self.assertIsNone(sx.child(fp,'embedded_files'))
  self.assertEqual(fp[-1][1],'kicad-embed://'+source.board_embedded_map['model.step'])
  embedded.validate_scopes(source.board)
 def test_checksum_only_reference_is_not_payload(self):
  embedded=importlib.import_module(pkg.__name__+'.embedded');source,fp=self.source(False)
  with self.assertRaises(model.MergeError):embedded.validate_scopes(source.board)
class CompatibilityTests(unittest.TestCase):
 def test_selected_variant_export_uses_copy_and_base_state(self):
  from test_bom_fields import FieldsTests
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp);source=FieldsTests().fixture(folder)
   original=source.schematic_file.read_bytes()
   class CLI:
    def export_netlist(self,path,destination):
     self.path=Path(path);self.tree=sx.load(self.path)
     return 'native-view'
   cli=CLI()
   self.assertEqual(engine.export_selected_netlist(source,cli,folder/'net.xml'),'native-view')
   node=sx.children(cli.tree,'symbol')[0]
   self.assertEqual(sx.propval(node,'Value'),'22k')
   self.assertNotEqual(cli.path,source.schematic_file)
   self.assertFalse(cli.path.exists())
   self.assertEqual(source.schematic_file.read_bytes(),original)

 def test_normal_pth_policy_retains_full_stack(self):
  layers=importlib.import_module(pkg.__name__+'.layers')
  source=SimpleNamespace(alias='A',copper_layers=['F.Cu','B.Cu'],target_copper_layers=['F.Cu','In1.Cu','In2.Cu','B.Cu'],layer_map={'F.Cu':'F.Cu','B.Cu':'In1.Cu'},layer_notes=[])
  item=['footprint','Lib:J',['layer',sx.q('F.Cu')],['pad','1','thru_hole','circle',['layers',sx.q('*.Cu'),sx.q('*.Mask')],['drill','0.5']]]
  layers.remap_item(item,source)
  self.assertEqual(sx.child(item[3],'layers')[1:],['*.Cu','*.Mask'])
  self.assertIn('full-stack',source.layer_notes[0])
 def test_automatic_pin_name_escaping_preserves_hierarchy(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'net.xml';p.write_text('<export><components/><nets><net name="/A/Net-(U1-TRACK/SS)"><node ref="U1" pin="1"/></net></nets></export>')
   self.assertEqual(netlist.Netlist.read(p).pins[('U1','1')],'/A/Net-(U1-TRACK{slash}SS)')
 def test_layer_mapping_preserves_knockout_token(self):
  layers=importlib.import_module(pkg.__name__+'.layers')
  source=SimpleNamespace(alias='A',copper_layers=['F.Cu','B.Cu'],target_copper_layers=['F.Cu','In1.Cu','In2.Cu','B.Cu'],layer_map={'F.Cu':'F.Cu','B.Cu':'In1.Cu'},layer_notes=[])
  item=['gr_text',sx.q('VIN'),['layer',sx.q('F.SilkS'),'knockout']]
  layers.remap_item(item,source)
  self.assertNotIsInstance(item[2][2],sx.Quoted)
  self.assertIsInstance(item[2][1],sx.Quoted)

 def test_native_xml_preserves_exported_association_path(self):
  root='11111111-1111-4111-8111-111111111111'; sheet='22222222-2222-4222-8222-222222222222'; symbol='33333333-3333-4333-8333-333333333333'
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'net.xml'
   for stamps in ('/'+sheet+'/', '/'+root+'/'+sheet+'/'):
    path.write_text(f'<export><components><comp ref="R1"><sheetpath tstamps="{stamps}"/><tstamps>{symbol}</tstamps></comp></components><nets/></export>')
    parsed=netlist.Netlist.read(path,root_uuid=root)
    self.assertEqual(parsed.components['R1']['paths'],{s.canonical_path(stamps+'/'+symbol)})
   with self.assertRaises(model.MergeError):netlist.Netlist.read(path,root_uuid='invalid')

 def test_null_netclass_metadata_uses_default(self):
  project={'net_settings':{'classes':[{'name':'Default'}],'netclass_assignments':None,'net_colors':None},'board':{},'schematic':{}}
  source=SimpleNamespace(portable_project=None,project=project,alias='A',project_file=Path('board.kicad_pro'),selected_variant='<Default>',class_map={'Default':'A_Default'},net_map={'GND':'A__GND'})
  result=engine.build_project([source],'Combined')
  self.assertEqual(result['net_settings']['netclass_assignments']['A__GND'],['A_Default'])
 def source(self,unnumbered='GND',numbered='GND'):
  tree=['kicad_pcb',['footprint','Lib:U',['property','Reference','U1'],['pad','1','smd','rect',['net',sx.q(numbered)]],['pad','','smd','rect',['net',sx.q(unnumbered)]]]]
  xml=netlist.Netlist(pins={('U1','1'):'GND'},nets={'GND':{('U1','1')}})
  return SimpleNamespace(alias='A',board=tree,board_ref_map={},ref_map={'U1':'U2'},xml=xml,net_map={'GND':'A__GND'})
 def test_unnumbered_pad_retains_proven_partition(self):
  merged=netlist.Netlist(pins={('U2','1'):'A__GND'})
  self.assertEqual(board.map_board_nets(self.source(),merged)['GND'],'A__GND')
 def test_orphan_unnumbered_net_refused(self):
  merged=netlist.Netlist(pins={('U2','1'):'A__GND'})
  with self.assertRaises(model.MergeError):board.map_board_nets(self.source('ORPHAN'),merged)
if __name__=='__main__':unittest.main()
