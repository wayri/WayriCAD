"""Native end-to-end universal schematic creation with source immutability."""
import importlib,os,sys,tempfile,unittest
from pathlib import Path
from types import ModuleType

ROOT=Path(__file__).resolve().parents[1]
package=ModuleType('_fusion_workspace_test');package.__path__=[str(ROOT)];sys.modules[package.__name__]=package
workspace=importlib.import_module(package.__name__+'.workspace')
repair=importlib.import_module(package.__name__+'.repair')
model=importlib.import_module(package.__name__+'.model')

@unittest.skipUnless(os.environ.get('FUSION_NATIVE_WORKSPACE')=='1','Opt-in native KiCad CLI workflow')
class WorkspaceTests(unittest.TestCase):
    def test_new_schematic_preview_publish_and_source_guard(self):
        sys.path.insert(0,str(ROOT/'tests'))
        try:
            from test_sections_native import make_fixture
            with tempfile.TemporaryDirectory(prefix='fusion-workspace-') as temporary:
                base=Path(temporary)
                fixture,_=make_fixture(base/'source')
                before=repair.fingerprint(base/'source')
                spec=model.SourceSpec(fixture.project,'PowerModule',variant='<Default>',sheet_position_mm=[110.0,120.0])
                prepared,originals=workspace.materialize_sources([spec],False,base)
                self.assertFalse(Path(prepared[0].project).with_suffix('.kicad_pcb').exists())
                plan=workspace.preview_new_schematic(prepared,base/'review','NewProject',copy_assets=False)
                plan['selection_originals']=originals
                self.assertFalse(plan['report']['copy_assets'])
                self.assertEqual(plan['report']['incoming_symbols'],1)
                sx=importlib.import_module(package.__name__+'.sexpr')
                root=sx.load(Path(plan['candidate_directory'])/'NewProject.kicad_sch')
                sheet=sx.children(root,'sheet')[0]
                self.assertEqual(list(map(float,sx.child(sheet,'at')[1:3])),[110.0,120.0])
                self.assertEqual(before,repair.fingerprint(base/'source'))
                result=workspace.publish_new_schematic(plan,base/'published','NewProject')
                self.assertTrue(Path(result['project']).is_file())
                self.assertTrue(Path(result['project']).with_suffix('.kicad_sch').is_file())
                self.assertFalse(Path(result['project']).with_suffix('.kicad_pcb').exists())
                self.assertTrue(result['native_netlist_verified'])
                (base/'source/changed.txt').write_text('changed after review')
                with self.assertRaisesRegex(model.MergeError,'Original source changed'):
                    workspace.publish_new_schematic(plan,base/'blocked','NewProject')
                self.assertFalse((base/'blocked').exists())
        finally:sys.path.remove(str(ROOT/'tests'))
