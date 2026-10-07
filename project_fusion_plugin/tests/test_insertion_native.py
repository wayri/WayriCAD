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
engine=importlib.import_module(PACKAGE+'.engine')
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
    def test_two_layer_bottom_component_imports_to_four_layer_bottom_with_through_via(self):
        import pcbnew

        with fixture_directory('mixed-bottom') as folder:
            base=Path(folder);target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            target_pcb=Path(target.project).with_suffix('.kicad_pcb')
            source_pcb=Path(source.project).with_suffix('.kicad_pcb')
            target_board=pcbnew.LoadBoard(str(target_pcb))
            target_board.SetCopperLayerCount(4)
            pcbnew.SaveBoard(str(target_pcb),target_board)
            source_board=pcbnew.LoadBoard(str(source_pcb))
            footprint=next(iter(source_board.GetFootprints()))
            footprint.Flip(footprint.GetPosition(),False)
            for track in source_board.GetTracks():
                if not isinstance(track,pcbnew.PCB_VIA):
                    track.SetLayer(pcbnew.B_Cu)
            pcbnew.SaveBoard(str(source_pcb),source_board)
            source_before=i.fingerprint(base/'source');target_before=i.fingerprint(base/'target')

            incoming=model.SourceSpec(source.project,'BottomModule',variant='<Default>')
            plan=i.preview_import(target.project,[incoming],True,base/'candidate')
            self.assertEqual(plan['report']['sources'][0]['layer_map'],{'F.Cu':'F.Cu','B.Cu':'B.Cu'})
            candidate=base/'candidate/board.kicad_pcb'
            tree=sx.load(candidate)
            imported_ref=plan['report']['sources'][0]['reference_map']['R1']
            imported_footprint=next(fp for fp in sx.children(tree,'footprint')
                                    if sx.propval(fp,'Reference')==imported_ref)
            self.assertEqual(sx.value(imported_footprint,'layer'),'B.Cu')
            self.assertEqual([str(x) for x in sx.child(sx.children(tree,'via')[-1],'layers')[1:]],
                             ['F.Cu','B.Cu'])
            native=pcbnew.LoadBoard(str(candidate))
            self.assertEqual(native.GetCopperLayerCount(),4)
            native_fp=next(fp for fp in native.GetFootprints() if fp.GetReference()==imported_ref)
            self.assertEqual(native_fp.GetLayer(),pcbnew.B_Cu)
            self.assertTrue(all(via.GetViaType()==pcbnew.VIATYPE_THROUGH and
                                via.TopLayer()==pcbnew.F_Cu and via.BottomLayer()==pcbnew.B_Cu
                                for via in native.GetTracks() if isinstance(via,pcbnew.PCB_VIA)))
            donor=model.SourceSpec(target.project,'Donor',variant='<Default>')
            merged=engine.merge(model.Options([incoming,donor],str(base/'merged'),
                name='Combined',acknowledge_outline_change=True,
                accept_primary_settings=True,saved_sources_confirmed=True,
                acknowledge_layer_remap=True))
            self.assertEqual(merged['report']['summary']['sources'][0]['unused_planar_layers'],
                             ['In1.Cu','In2.Cu'])
            merged_native=pcbnew.LoadBoard(str(Path(merged['project']).with_suffix('.kicad_pcb')))
            self.assertEqual(merged_native.GetCopperLayerCount(),4)
            self.assertEqual(sum(fp.GetLayer()==pcbnew.B_Cu for fp in merged_native.GetFootprints()),1)
            self.assertTrue(all(via.GetViaType()==pcbnew.VIATYPE_THROUGH and
                                via.TopLayer()==pcbnew.F_Cu and via.BottomLayer()==pcbnew.B_Cu
                                for via in merged_native.GetTracks() if isinstance(via,pcbnew.PCB_VIA)))
            self.assertEqual(i.fingerprint(base/'source'),source_before)
            self.assertEqual(i.fingerprint(base/'target'),target_before)

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
