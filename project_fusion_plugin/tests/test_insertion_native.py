"""Opt-in native saved-target insertion and transaction workflows."""
import importlib
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='_fusion_insertion_native_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
i=importlib.import_module(PACKAGE+'.insertion')
sx=importlib.import_module(PACKAGE+'.sexpr')
model=importlib.import_module(PACKAGE+'.model')
from test_sections_native import make_fixture

def fixture_directory(mode):
    retained=os.environ.get('FUSION_NATIVE_INSERTION_OUTPUT')
    if not retained:return tempfile.TemporaryDirectory(prefix='fusion-native-insertion-')
    path=Path(retained)/mode;path.mkdir(parents=True,exist_ok=False)
    return nullcontext(str(path))

@unittest.skipUnless(os.environ.get('FUSION_NATIVE_INSERTION')=='1','Opt-in KiCad native insertion')
class NativeInsertionTests(unittest.TestCase):
    def test_routed_multiple_instances_preserve_existing_target_and_apply(self):
        with fixture_directory('routed') as folder:
            base=Path(folder);target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            (base/'target/pre-existing-empty').mkdir()
            original=i.fingerprint(base/'target');incoming_original=i.fingerprint(base/'source')
            first=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            second=model.SourceSpec(source.project,'Unit2',variant='<Default>')
            plan=i.preview_import(target.project,[first,second],True,base/'candidate')
            self.assertEqual(plan['report']['incoming_footprints'],2)
            self.assertEqual(plan['report']['incoming_designs'],2)
            candidate=sx.load(base/'candidate/board.kicad_pcb')
            self.assertEqual(len(sx.children(candidate,'footprint')),3)
            self.assertEqual(len(sx.children(candidate,'segment')),6)
            self.assertEqual(len(sx.children(candidate,'via')),3)
            self.assertEqual(len(sx.children(candidate,'zone')),3)
            self.assertEqual(i.fingerprint(base/'target'),original)
            self.assertEqual(i.fingerprint(base/'source'),incoming_original)
            loaded=json.loads(json.dumps(plan));result=i.apply_import(loaded)
            self.assertTrue(Path(result['backup_directory']).is_dir())
            self.assertEqual(i.fingerprint(base/'target'),plan['candidate_hashes'])
            self.assertEqual(i.fingerprint(base/'source'),incoming_original)
            self.assertTrue((base/'target/pre-existing-empty').is_dir())
            (base/'reviewed-import-plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
            (base/'native-validation.json').write_text(json.dumps({'mode':'routed','report':plan['report'],
                'applied':result,'original_target_preserved_during_preview':True,'source_unchanged':True,
                'existing_empty_directory_preserved':True,'target_matches_reviewed_candidate_after_apply':True},indent=2),encoding='utf-8')

    def test_schematic_only_without_board_preserves_original_target_pcb_bytes(self):
        with fixture_directory('schematic-only') as folder:
            base=Path(folder);target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            (base/'source/board.kicad_pcb').unlink()
            original_board=(base/'target/board.kicad_pcb').read_bytes()
            source=model.SourceSpec(source.project,'Schematic',variant='<Default>')
            plan=i.preview_import(target.project,[source],False,base/'candidate')
            self.assertEqual(plan['report']['incoming_footprints'],0)
            self.assertEqual(plan['report']['expected_new_unplaced_components'],1)
            self.assertEqual((base/'candidate/board.kicad_pcb').read_bytes(),original_board)
            self.assertEqual(plan['report']['target_root_uuid'],sx.value(sx.load(base/'target/board.kicad_sch'),'uuid'))
            result=i.apply_import(plan)
            self.assertEqual((base/'target/board.kicad_pcb').read_bytes(),original_board)
            (base/'reviewed-import-plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
            (base/'native-validation.json').write_text(json.dumps({'mode':'schematic-only','report':plan['report'],
                'applied':result,'source_has_no_pcb':True,'target_pcb_bytes_unchanged_after_apply':True},indent=2),encoding='utf-8')

if __name__=='__main__':unittest.main()
