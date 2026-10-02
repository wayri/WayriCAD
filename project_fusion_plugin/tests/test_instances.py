"""Instance capacity, copy isolation, section provenance and setup compatibility."""
import importlib,json,sys,tempfile,unittest
from pathlib import Path
from types import ModuleType
ROOT=Path(__file__).resolve().parents[1];PACKAGE='_fusion_instances_test';pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
m=importlib.import_module(PACKAGE+'.model')
class InstanceTests(unittest.TestCase):
 def options(self,sources):return m.Options(sources,'C:/Projects/Combined',saved_sources_confirmed=True,acknowledge_outline_change=True,columns=10)
 def test_100_mixed_instances_roundtrip(self):
  origin={'project':'C:/Projects/Original/board.kicad_pro','sheet_path':'/root/child','region_mm':[0,0,20,20]}
  source=m.SourceSpec('C:/Projects/Section/board.kicad_pro','Part',variant='<Default>',section_origin=origin)
  full=m.SourceSpec('C:/Projects/Board/board.kicad_pro','Full',variant='<Default>')
  specs=m.duplicate_sources([full,source],[0,1],49);options=self.options(specs);options.validate()
  self.assertEqual(len(specs),100);self.assertEqual(sum(s.kind=='section' for s in specs),50)
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'setup.json';path.write_text(json.dumps(options.to_dict()));loaded=m.Options.from_json(path);loaded.validate();self.assertEqual(loaded.to_dict(),options.to_dict())
 def test_capacity_rejection_is_nonmutating(self):
  specs=[m.SourceSpec('board.kicad_pro','A')];before=json.dumps([m.asdict(s) for s in specs])
  with self.assertRaises(m.MergeError):m.duplicate_sources(specs,[0],100)
  self.assertEqual(before,json.dumps([m.asdict(s) for s in specs]))
  with self.assertRaises(m.MergeError):self.options([m.SourceSpec('board.kicad_pro',f'A{i}') for i in range(101)]).validate()
 def test_unique_long_aliases_and_deep_copy(self):
  original=m.SourceSpec('board.kicad_pro','ABCDEFGHIJKLMNOPQRSTUVWX',1.,2.,'<Default>',{'P':'old'},section_origin={'project':'parent.kicad_pro','sheet_path':'/a/b','region_mm':[0,0,10,10]})
  result=m.duplicate_sources([original],[0],99)
  self.assertEqual(len({s.alias.casefold() for s in result}),100);self.assertTrue(all(len(s.alias)<=24 for s in result))
  self.assertTrue(all(s.x_mm is None and s.y_mm is None for s in result[1:]));self.assertEqual(result[0].x_mm,1.)
  result[1].path_variables['P']='new';result[1].section_origin['region_mm'][0]=-1
  self.assertEqual(original.path_variables['P'],'old');self.assertEqual(result[2].section_origin['region_mm'][0],0)
 def test_legacy_setup_defaults_to_project(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'old.json';data=self.options([m.SourceSpec('board.kicad_pro','A')]).to_dict();data['sources'][0].pop('section_origin');p.write_text(json.dumps(data));self.assertEqual(m.Options.from_json(p).sources[0].kind,'project')
 def test_invalid_provenance_and_columns_refused(self):
  for origin in [[],{'project':'p'}, {'project':'p','sheet_path':'/a','region_mm':[1,0,0,1]}, {'project':'p','sheet_path':'/a','region_mm':[0,0,float('inf'),1]}]:
   with self.assertRaises(m.MergeError):self.options([m.SourceSpec('b.kicad_pro','A',section_origin=origin)]).validate()
  for columns in [0,101,True,2.5]:
   option=self.options([m.SourceSpec('b.kicad_pro','A')]);option.columns=columns
   with self.assertRaises(m.MergeError):option.validate()
if __name__=='__main__':unittest.main()
