import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import ModuleType,SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='_fusion_insertion_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
i=importlib.import_module(PACKAGE+'.insertion')
sx=importlib.import_module(PACKAGE+'.sexpr')
model=importlib.import_module(PACKAGE+'.model')
layers=importlib.import_module(PACKAGE+'.layers')

class InsertionTests(unittest.TestCase):
    def test_import_rejects_non_through_vias_and_larger_source_stack(self):
        source=SimpleNamespace(alias='Source',copper_layers=['F.Cu','In1.Cu','In2.Cu','B.Cu'],
                               target_copper_layers=['F.Cu','In1.Cu','In2.Cu','B.Cu'],
                               layer_map={name:name for name in ('F.Cu','In1.Cu','In2.Cu','B.Cu')},
                               layer_notes=[],through_vias_only=True)
        for via in ('(via blind (layers "F.Cu" "In1.Cu"))',
                    '(via micro (layers "F.Cu" "In1.Cu"))',
                    '(via (layers "F.Cu" "In1.Cu"))'):
            with self.subTest(via=via),self.assertRaisesRegex(model.MergeError,'only native F.Cu-to-B.Cu through vias'):
                layers.remap_item(sx.loads(via),source)
        source.board=sx.loads('(kicad_pcb (layers (0 "F.Cu" signal) (1 "In1.Cu" signal) '
                              '(2 "In2.Cu" signal) (31 "B.Cu" signal)))')
        with self.assertRaisesRegex(model.MergeError,'more copper layers'):
            layers.plan_layers([source],True,target_layers=['F.Cu','B.Cu'],
                               preserve_outer=True,through_vias_only=True)

    def transaction(self,base):
        root=base/'target';root.mkdir();(root/'board.kicad_pro').write_text('{}');(root/'a.txt').write_text('old')
        (root/'existing-empty').mkdir()
        source=base/'source';source.mkdir();(source/'source.txt').write_text('stable')
        candidate=base/'candidate';i.copy_project(root,candidate)
        (candidate/'a.txt').write_text('new');(candidate/'new').mkdir();(candidate/'new/b.txt').write_text('added')
        (candidate/'zz.fail').write_text('last')
        return {'target_project':str(root/'board.kicad_pro'),'target_hashes':i.fingerprint(root),
                'source_hashes':[{'root':str(source),'hashes':i.fingerprint(source)}],
                'candidate_directory':str(candidate),'candidate_hashes':i.fingerprint(candidate),'report':{}},root,source,candidate

    def test_assets_prefix_is_idempotent(self):
        tree=sx.loads('(lib (uri "${KIPRJMOD}/assets/A/model.step"))')
        i._prefix_assets(tree,'fusion_imports/batch');first=sx.dumps(tree)
        i._prefix_assets(tree,'fusion_imports/batch');self.assertEqual(sx.dumps(tree),first)
        self.assertEqual(sx.value(tree,'uri'),'${KIPRJMOD}/fusion_imports/batch/assets/A/model.step')

    def test_reference_allocation_preserves_target_and_separates_many_instances(self):
        target=SimpleNamespace(symbols=[SimpleNamespace(old_ref='R1'),SimpleNamespace(old_ref='R100')],board=None)
        incoming=[SimpleNamespace(symbols=[SimpleNamespace(old_ref='R1',new_ref='')],ref_map={},board_ref_map={}) for _ in range(100)]
        i._reference_maps(target,incoming,False)
        self.assertEqual(target.ref_map,{'R1':'R1','R100':'R100'})
        self.assertEqual(incoming[0].ref_map['R1'],'R101');self.assertEqual(incoming[-1].ref_map['R1'],'R200')

    def test_stale_target_source_and_candidate_refused(self):
        for changed in ('target','source','candidate'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as folder:
                plan,root,source,candidate=self.transaction(Path(folder))
                {'target':root,'source':source,'candidate':candidate}[changed].joinpath('change').write_text('changed')
                with self.assertRaises(model.MergeError):i.apply_import(plan)
                self.assertEqual((root/'a.txt').read_text(),'old')

    def test_editor_lock_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            plan,root,_,_=self.transaction(Path(folder));(root/'board.kicad_pcb.lck').write_text('locked')
            with self.assertRaisesRegex(model.MergeError,'lock files'):i.apply_import(plan)
            self.assertEqual((root/'a.txt').read_text(),'old')

    def test_success_json_loaded_plan_and_verified_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            plan,root,_,_=self.transaction(Path(folder));result=i.apply_import(json.loads(json.dumps(plan)))
            backup=Path(result['backup_directory'])/'project'
            self.assertEqual(i.fingerprint(backup),plan['target_hashes'])
            self.assertEqual(i.fingerprint(root),plan['candidate_hashes'])
            self.assertTrue((root/'existing-empty').is_dir())

    def test_failure_rolls_back_files_and_only_new_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            plan,root,_,_=self.transaction(Path(folder));real_replace=i.os.replace
            def fail_last(source,destination):
                if Path(destination).name=='zz.fail':raise OSError('Injected write failure')
                return real_replace(source,destination)
            with mock.patch.object(i.os,'replace',side_effect=fail_last):
                with self.assertRaisesRegex(OSError,'Injected'):i.apply_import(plan)
            self.assertEqual(i.fingerprint(root),plan['target_hashes'])
            self.assertTrue((root/'existing-empty').is_dir());self.assertFalse((root/'new').exists())

    def test_corrupt_backup_refused_before_any_target_write(self):
        with tempfile.TemporaryDirectory() as folder:
            plan,root,_,_=self.transaction(Path(folder));real_copy=i.copy_project
            def corrupt(source,destination):
                real_copy(source,destination);Path(destination,'a.txt').write_text('truncated')
            with mock.patch.object(i,'copy_project',side_effect=corrupt):
                with self.assertRaisesRegex(model.MergeError,'Backup verification'):i.apply_import(plan)
            self.assertEqual(i.fingerprint(root),plan['target_hashes'])

    def test_external_dependency_stale_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);plan,root,_,_=self.transaction(base)
            dependency=base/'external.step';dependency.write_text('old')
            plan['source_file_hashes']=[{'original_path':str(dependency),'sha256':i.sha256(dependency)}]
            dependency.write_text('changed')
            with self.assertRaisesRegex(model.MergeError,'dependency changed'):i.apply_import(plan)
            self.assertEqual(i.fingerprint(root),plan['target_hashes'])

    def test_rollback_io_failure_names_recoverable_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            plan,root,_,_=self.transaction(Path(folder));real_replace=i.os.replace;real_copy=i.shutil.copy2
            def fail_last(source,destination):
                if Path(destination).name=='zz.fail':raise OSError('Injected write failure')
                return real_replace(source,destination)
            def fail_restore(source,destination):
                if Path(source).parent.name=='project' and Path(source).name=='a.txt':raise OSError('Injected restore failure')
                return real_copy(source,destination)
            with mock.patch.object(i.os,'replace',side_effect=fail_last),mock.patch.object(i.shutil,'copy2',side_effect=fail_restore):
                with self.assertRaisesRegex(model.MergeError,'recover from .*FusionBackup'):i.apply_import(plan)
            backups=list(root.parent.glob('target-FusionBackup-*'))
            self.assertEqual(len(backups),1);self.assertEqual((backups[0]/'project/a.txt').read_text(),'old')
            self.assertTrue((root/'existing-empty').is_dir())

if __name__=='__main__':unittest.main()
