"""Pure-format PCB unbundle/relink tests. Opaque model bytes are not STEP geometry."""
from pathlib import Path
import json
import tempfile
import unittest
from embed_3d_plugin import board_package as bp
from embed_3d_plugin.codec import Codec, sha256
from embed_3d_plugin.core import Planner, PREFIX, embedded_entries
from embed_3d_plugin.paths import Resolver
from embed_3d_plugin.sexpr import parse, patch, quote
from embed_3d_plugin.unbundle import extract_pcb, relink_pcb, prune_models, uri_references
from embed_3d_plugin.portability_io import load_extraction
from test_board_package import placed, board, rename_snapshot, MODEL_SETTINGS


class UnbundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'design.kicad_pcb';self.assets=self.root/'assets';self.out=self.root/'relinked'
        self.model=self.root/'R_0402.step';self.data=b'opaque source step data\x00\xff';self.model.write_bytes(self.data)
        self.uid='11111111-1111-4111-8111-111111111111';self.uid2='22222222-2222-4222-8222-222222222222'
    def tearDown(self):self.tmp.cleanup()
    def package(self,zero=False,second=False):
        raw=[placed(self.uid,'R1','Resistor_SMD:R_0402',None if zero else self.model)]
        if second:raw.append(placed(self.uid2,'R2','Resistor_SMD:R_0402',self.model,pad_x='9.8'))
        plans=[Planner(Resolver(self.root)).scan(t) for t in raw]
        defs=[bp.Definition(str(i),'AsPlaced_'+str(i),rename_snapshot(p.build(),'AsPlaced_'+str(i)),'Resistor_SMD:R_0402') for i,p in enumerate(plans)]
        inst=[bp.Instance(bp.uuid_of(t),p,d.key,d.key) for t,p,d in zip(raw,plans,defs)]
        note=bp.entry_for_bytes('keep.txt',b'unrelated',Codec())
        package=bp.compose(board(raw,'(embedded_files '+note.raw+')'),inst,defs,'Packaged')
        self.source.write_text(package.board_text);return package
    def extract(self,**kw):
        p=extract_pcb(self.source,self.assets,**kw);p.publish(self.assets);return p
    def test_extract_actual_bytes_and_fp_separate_no_source_change(self):
        original=self.package();self.model.unlink();p=self.extract()
        self.assertEqual(self.source.read_text(),original.board_text)
        models=[data for name,data in p.files.items() if name.startswith('models/')]
        self.assertEqual(models,[self.data]);fps=[v for k,v in p.files.items() if k.endswith('.kicad_mod')]
        self.assertEqual(len(fps),1);self.assertIn(MODEL_SETTINGS,fps[0].decode());self.assertNotIn(PREFIX,bp.model_refs(fps[0].decode())[0])
    def test_relink_is_separate_dry_run(self):
        self.package();self.extract();before=self.source.read_bytes()
        relink_pcb(self.source,self.assets,self.out)
        self.assertFalse(self.out.exists());self.assertEqual(self.source.read_bytes(),before)
    def test_apply_relative_ids_models_library_view_and_snapshots(self):
        orig=self.package(second=True);self.extract();report=relink_pcb(self.source,self.assets,self.out,apply=True)
        after=(self.out/self.source.name).read_text()
        self.assertEqual(bp._board_fingerprint(orig.board_text),bp._board_fingerprint(after))
        self.assertEqual(after.count(MODEL_SETTINGS),2)
        self.assertIn('(footprint "UnbundledFootprints:',after);self.assertIn('${KIPRJMOD}/../assets/models/',after)
        self.assertEqual((self.out/'WayriCAD Embed3D-originals'/self.source.name).read_text(),orig.board_text)
        self.assertIn('${KIPRJMOD}/../assets/linked/',(self.out/'fp-lib-table').read_text())
        for file in report['library_view_files']:
            text=(self.assets/file).read_text();self.assertIn('${KIPRJMOD}/../assets/models/',text)
            self.assertEqual(bp.model_settings(text),bp.model_settings(next(iter(orig.library_files.values())).decode()))
    def test_prune_removes_managed_archive_models_keeps_unrelated(self):
        self.package();self.extract();relink_pcb(self.source,self.assets,self.out,apply=True,prune=True)
        after=(self.out/self.source.name).read_text();pool=embedded_entries(after)
        self.assertNotIn(bp.MANIFEST,pool);self.assertEqual(set(pool),{'keep.txt'})
    def test_keep_is_default(self):
        self.package();self.extract();relink_pcb(self.source,self.assets,self.out,apply=True)
        self.assertIn(bp.MANIFEST,embedded_entries((self.out/self.source.name).read_text()))
    def test_model_only_prune_keeps_models_used_in_retained_archives(self):
        self.package();self.extract(footprints=False)
        relink_pcb(self.source,self.assets,self.out,apply=True,link_footprints=False,prune=True)
        after=(self.out/self.source.name).read_text();self.assertIn(bp.MANIFEST,embedded_entries(after))
        recovered=bp.recover(after);self.assertTrue(recovered.library_files)
    def test_footprint_only_retains_embedded_library_models(self):
        self.package();p=self.extract(models=False)
        self.assertFalse(any(k.startswith('models/') for k in p.files))
        for raw in p.files.values():self.assertTrue(embedded_entries(raw.decode()))
        relink_pcb(self.source,self.assets,self.out,apply=True,link_models=False)
        self.assertTrue(bp.model_refs(parse((self.out/self.source.name).read_text()).nodes((self.out/self.source.name).read_text(),'footprint')[0].raw((self.out/self.source.name).read_text()))[0].startswith(PREFIX))
    def test_zero_model_footprint_can_extract_and_relink(self):
        self.package(zero=True);p=self.extract();self.assertEqual(len(p.files),1)
        relink_pcb(self.source,self.assets,self.out,apply=True)
    def test_arbitrary_native_model_only_board_no_archive(self):
        fp=Planner(Resolver(self.root)).scan(placed(self.uid,'R1','Lib:Part',self.model)).build()
        self.source.write_text(board([fp]));p=self.extract(footprints=False)
        self.assertEqual(list(p.files.values()),[self.data])
    def test_plain_board_native_normalized_map_contract(self):
        fp=Planner(Resolver(self.root)).scan(placed(self.uid,'R1','Lib:Part',self.model)).build()
        self.source.write_text(board([fp]))
        # Synthetic normalized coordinate fixture is not the native integration test.
        p=self.extract(normalized={self.uid:('Part',rename_snapshot(fp,'Part'))},normalized_source_hash=sha256(self.source.read_bytes()))
        self.assertIn('UnbundledFootprints.pretty/Part.kicad_mod',p.files)
    def test_normalized_map_source_hash_guard(self):
        self.package()
        with self.assertRaises(ValueError):self.extract(normalized={},normalized_source_hash='0'*64)
    def test_external_copy_opt_in(self):
        self.source.write_text(board([placed(self.uid,'R1','Lib:Part',self.model)]))
        p=extract_pcb(self.source,self.assets,footprints=False)
        self.assertFalse(p.files);self.assertTrue(p.warnings)
        p=self.extract(footprints=False,include_external=True);self.assertEqual(list(p.files.values()),[self.data])
    def test_model_payload_missing_blocks(self):
        self.source.write_text(board([placed(self.uid,'R1','Lib:Part',PREFIX+'absent.step')]))
        with self.assertRaisesRegex(ValueError,'Missing embedded'):self.extract(footprints=False)
    def test_changed_design_blocks_relink(self):
        self.package();self.extract();self.source.write_text(self.source.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'Source changed'):relink_pcb(self.source,self.assets,self.out,apply=True)
        self.assertFalse(self.out.exists())
    def test_changed_extracted_file_blocks(self):
        self.package();self.extract();next(self.assets.rglob('*.step')).write_bytes(b'changed')
        with self.assertRaises(ValueError):relink_pcb(self.source,self.assets,self.out,apply=True)
    def test_absolute_links(self):
        self.package();self.extract();relink_pcb(self.source,self.assets,self.out,path_mode='absolute',apply=True)
        self.assertIn((self.assets/'models').as_posix(),(self.out/self.source.name).read_text())
    def test_duplicate_models_share_one_output(self):
        self.package(second=True);p=self.extract();self.assertEqual(len([n for n in p.files if n.startswith('models/')]),1)
    def test_payload_with_space_name_is_not_pruned_while_referenced(self):
        name='my model.step';entry=bp.entry_for_bytes(name,self.data,Codec(),'model')
        raw=bp.replace_entries(placed(self.uid,'R1','Lib:Part',PREFIX+name),{name:entry})
        self.assertIn(name,embedded_entries(prune_models(raw,{name})))
    def test_extraction_folder_change_requires_new_preview(self):
        self.package();plan=extract_pcb(self.source,self.assets)
        with self.assertRaisesRegex(ValueError,'Asset folder changed'):plan.publish(self.root/'moved-assets')
    def test_unconverted_project_model_target_rebased_in_new_copy(self):
        self.source.write_text(board([placed(self.uid,'R1','Lib:Part','${KIPRJMOD}/R_0402.step')]))
        self.extract(footprints=False)
        relink_pcb(self.source,self.assets,self.out,link_footprints=False,apply=True)
        self.assertIn('${KIPRJMOD}/../R_0402.step',(self.out/self.source.name).read_text())
