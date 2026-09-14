"""Component selection and coordinated operations: no native KiCad geometry claim."""
import json
from pathlib import Path
import tempfile
import unittest
from embed_3d_plugin import workspace as w
from embed_3d_plugin import symbols as sy
from embed_3d_plugin.core import embedded_entries, PREFIX, Planner
from embed_3d_plugin.paths import Resolver
from embed_3d_plugin.sexpr import parse, patch, quote
from embed_3d_plugin.codec import sha256
from embed_3d_plugin import board_package as bp
from embed_3d_plugin.unbundle import extract_pcb, relink_pcb
from test_board_package import board, placed, rename_snapshot, MODEL_SETTINGS
from test_symbols import schematic, instance, symbol, child


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.pcb=self.root/'circuit.kicad_pcb';self.sch=self.root/'circuit.kicad_sch'
        self.uid='11111111-1111-4111-8111-111111111111'
        self.uid2='22222222-2222-4222-8222-222222222222'
        self.model=self.root/'m.step';self.data=b'opaque test step\x00\xff';self.model.write_bytes(self.data)
        fp1=placed(self.uid,'R1','Lib:Part',self.model)
        fp2=placed(self.uid2,'R2','Lib:Part',self.model,pad_x='4')
        self.pcb.write_text(board([fp1,fp2]))
        self.sch.write_text(schematic(instances=[instance(self.uid,ref='R1'),instance(self.uid2,ref='R2')]))
        self.inv=w.scan_design(self.pcb,self.sch)
        self.opt=w.Options(self.root/'assets',self.root/'output')
        self.norm={}
        for fp in parse(self.pcb.read_text()).nodes(self.pcb.read_text(),'footprint'):
            raw=fp.raw(self.pcb.read_text());uid=bp.uuid_of(raw);name='FP_'+uid[:8]
            self.norm[uid]=(name,rename_snapshot(raw,name))
    def tearDown(self): self.tmp.cleanup()
    def prep(self,operation='embed',sel=None,**kw):
        return w.prepare_operation(self.inv,sel or self.inv.selection(),operation,self.opt,
                    normalized=self.norm,normalized_hash=sha256(self.pcb.read_bytes()),**kw)
    def fpmap(self,text):return {bp.uuid_of(text,n):n.raw(text) for n in parse(text).nodes(text,'footprint')}
    def test_inventory_combines_unique_refs_no_path(self):
        self.assertEqual(len(self.inv.rows),2)
        self.assertEqual(self.inv.selection().counts(),dict(symbols=2,footprints=2,models=2))
    def test_tri_state_and_independent_checks(self):
        self.inv.select_all(value=False);self.assertEqual(self.inv.state(),'none')
        self.inv.rows[0].checked['models']=True
        self.assertEqual(self.inv.state('models'),'mixed');self.assertEqual(self.inv.state('symbols'),'none')
        self.inv.select_all('models');self.assertEqual(self.inv.state('models'),'all')
        self.assertEqual(self.inv.selection().counts(),dict(symbols=0,footprints=0,models=2))
    def test_global_all_overrides_checks_explicitly_not_mutating_matrix(self):
        self.inv.select_all(value=False);self.assertEqual(self.inv.selection(True).counts()['footprints'],2)
        self.assertEqual(self.inv.state(),'none')
    def test_footprint_no_model_available_not_models(self):
        self.pcb.write_text(board([placed(self.uid,'J1','Lib:X',None)]));inv=w.scan_design(self.pcb)
        self.assertTrue(inv.rows[0].available('footprints'));self.assertFalse(inv.rows[0].available('models'))
    def test_schematic_only(self):
        inv=w.scan_design(schematic=self.sch);self.assertEqual(len(inv.rows),2)
        self.assertFalse(inv.selection().footprints);self.assertEqual(inv.selection().counts()['symbols'],2)
    def test_uuid_match_preferred_over_reference(self):
        text=self.pcb.read_text();fps=parse(text).nodes(text,'footprint');fp=fps[0]
        text=patch(text,[(fp.end-1,fp.end-1,'(path "/root/'+self.uid2+'")')]);self.pcb.write_text(text)
        inv=w.scan_design(self.pcb,self.sch)
        row=next(r for r in inv.rows if r.board_uuid==self.uid)
        self.assertEqual(row.symbol_instances[0][1],self.uid2)
    def test_mismatched_uuid_does_not_fallback_to_same_reference(self):
        text=self.pcb.read_text();fp=parse(text).nodes(text,'footprint')[0]
        self.pcb.write_text(patch(text,[(fp.end-1,fp.end-1,'(path "/wrong/not-a-symbol")')]))
        inv=w.scan_design(self.pcb,self.sch);row=next(r for r in inv.rows if r.board_uuid==self.uid)
        self.assertFalse(row.symbol_instances)
    def test_multi_unit_component_one_row(self):
        self.sch.write_text(schematic(instances=[instance(self.uid,ref='U1',unit=1),instance(self.uid2,ref='U1',unit=2)]))
        inv=w.scan_design(schematic=self.sch);self.assertEqual(len(inv.rows),1)
        self.assertEqual(len(inv.rows[0].symbol_instances),2)
    def test_duplicate_reference_unit_no_board_match(self):
        self.sch.write_text(schematic(instances=[instance(self.uid,ref='R1'),instance(self.uid2,ref='R1')]))
        inv=w.scan_design(self.pcb,self.sch);row=next(r for r in inv.rows if r.board_uuid==self.uid)
        self.assertFalse(row.symbol_instances)
    def test_scan_changed_source_blocks_preview(self):
        self.sch.write_text(self.sch.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'changed'):self.prep()
    def test_partial_embed_models_does_not_embed_other_model(self):
        sel=w.Selection(models={self.uid})
        plan=self.prep(sel=sel);self.assertFalse(self.opt.output.exists());plan.apply()
        fps=self.fpmap((self.opt.output/self.pcb.name).read_text())
        self.assertTrue(bp.model_refs(fps[self.uid])[0].startswith(PREFIX))
        self.assertEqual(bp.model_refs(fps[self.uid2]),[str(self.model)])
        self.assertNotIn(w.ARCHIVE,embedded_entries((self.opt.output/self.pcb.name).read_text()))
    def test_partial_footprints_does_not_embed_external_models(self):
        sel=w.Selection(footprints={self.uid});plan=self.prep(sel=sel);plan.apply()
        text=(self.opt.output/self.pcb.name).read_text();pool=embedded_entries(text)
        records=w.read_component_archive(text);self.assertEqual(set(records),{self.uid})
        fps=self.fpmap(text);self.assertEqual(bp.model_refs(fps[self.uid]),[str(self.model)])
        self.assertEqual(parse(fps[self.uid2]).arg().value(fps[self.uid2]),'Lib:Part')
        self.assertFalse(any(n.endswith('.step') for n in pool))
    def test_all_three_one_design_folder_and_originals(self):
        before_pcb=self.pcb.read_bytes();before_sch=self.sch.read_bytes()
        plan=self.prep();plan.apply();self.assertTrue((self.opt.output/'fp-lib-table').is_file())
        self.assertTrue((self.opt.output/'sym-lib-table').is_file())
        self.assertTrue((self.opt.output/self.sch.name).is_file())
        self.assertEqual(self.pcb.read_bytes(),before_pcb);self.assertEqual(self.sch.read_bytes(),before_sch)
        self.assertEqual((self.opt.output/'WayriCAD Embed3D-originals'/self.pcb.name).read_bytes(),before_pcb)
        self.assertEqual(len(list(self.opt.output.rglob('*.kicad_mod'))),2)
        sy.verify_symbol_preservation(before_sch.decode(),(self.opt.output/self.sch.name).read_text())
        self.assertEqual((self.opt.output/self.pcb.name).read_text().count(MODEL_SETTINGS),2)
    def test_embed_archived_definitions_recover(self):
        self.prep().apply();new=self.opt.output/self.pcb.name
        normalized,digest=w.archived_normalized(new,{self.uid})
        self.assertEqual(set(normalized),{self.uid});self.assertEqual(digest,sha256(new.read_bytes()))
        self.assertTrue(embedded_entries(normalized[self.uid][1]))
    def test_model_source_changes_after_preview_blocks(self):
        plan=self.prep();self.model.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Input changed'):plan.apply()
        self.assertFalse(self.opt.output.exists())
    def test_missing_unselected_model_does_not_block_embed(self):
        text=self.pcb.read_text();fp=parse(text).nodes(text,'footprint')[1];raw=fp.raw(text);n=parse(raw).nodes(raw,'model')[0]
        raw=patch(raw,[(n.arg().start,n.arg().end,quote('missing.step'))]);self.pcb.write_text(patch(text,[(fp.start,fp.end,raw)]))
        self.inv=w.scan_design(self.pcb,self.sch)
        self.prep(sel=w.Selection(models={self.uid})).apply()
    def test_missing_selected_model_has_actionable_error(self):
        self.model.unlink()
        with self.assertRaisesRegex(ValueError,'m.step'):self.prep(sel=w.Selection(models={self.uid}))
    def test_native_normalization_hash_mismatch_blocks(self):
        with self.assertRaisesRegex(ValueError,'changed after native'):w.prepare_operation(self.inv,self.inv.selection(),'embed',self.opt,normalized=self.norm,normalized_hash='0'*64)
    def test_symbol_per_component_shared_definition_keeps_unselected_id_cache(self):
        plan=self.prep(sel=w.Selection(symbols={self.sch.name:{self.uid}}));plan.apply()
        after=(self.opt.output/self.sch.name).read_text();placed=sy.placed_symbols(after)
        self.assertTrue(placed[0]['lib_id'].startswith('WayriCAD_Embed3D_Symbols:'))
        self.assertEqual(placed[1]['lib_id'],'Device:R');self.assertIn('Device:R',sy.cache_symbols(after))
        sy.verify_symbol_preservation(self.sch.read_text(),after)
    def test_unbundle_only_no_new_design(self):
        self.opt.include_external=True;plan=self.prep('unbundle');plan.apply()
        self.assertFalse(self.opt.output.exists());self.assertTrue((self.opt.assets/w.WORKSPACE_MANIFEST).is_file())
        self.assertEqual(len(list(self.opt.assets.rglob('*.step'))),1)
        self.assertTrue(list(self.opt.assets.rglob('*.kicad_sym')))
    def test_partial_unbundle_independent_types(self):
        self.opt.include_external=True
        sel=w.Selection(footprints={self.uid},models={self.uid2},symbols={self.sch.name:{self.uid}})
        plan=self.prep('unbundle',sel=sel);plan.apply()
        meta,_=w.load_extraction(self.opt.assets/'pcb',self.pcb)
        names=[i['name'] for i in meta['instances']];self.assertIsNotNone(names[0]);self.assertIsNone(names[1])
        self.assertEqual(len(list(self.opt.assets.rglob('*.kicad_mod'))),1)
        self.assertEqual(len(list(self.opt.assets.rglob('*.step'))),1)
    def test_unbundle_then_single_relink_both_domains(self):
        self.opt.include_external=True;self.prep('unbundle').apply()
        plan=self.prep('relink');self.assertFalse(self.opt.output.exists());plan.apply()
        self.assertTrue((self.opt.output/self.pcb.name).is_file());self.assertTrue((self.opt.output/self.sch.name).is_file())
        self.assertIn('${KIPRJMOD}/../assets/pcb/models/',(self.opt.output/self.pcb.name).read_text())
    def test_combined_extract_and_relink_one_plan(self):
        self.opt.include_external=True;plan=self.prep('unbundle-relink')
        self.assertFalse(self.opt.assets.exists());self.assertFalse(self.opt.output.exists())
        plan.apply();self.assertTrue((self.opt.output/self.pcb.name).is_file())
        self.assertTrue((self.opt.assets/w.WORKSPACE_MANIFEST).is_file())
    def test_changed_extracted_bytes_blocks_separate_relink(self):
        self.opt.include_external=True;self.prep('unbundle').apply()
        next(self.opt.assets.rglob('*.step')).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed, missing or corrupt'):self.prep('relink')
    def test_relink_only_subset_of_previously_extracted(self):
        self.opt.include_external=True;self.prep('unbundle').apply()
        sel=w.Selection(models={self.uid},symbols={self.sch.name:{self.uid}})
        plan=self.prep('relink',sel=sel);plan.apply()
        fps=self.fpmap((self.opt.output/self.pcb.name).read_text())
        self.assertIn('${KIPRJMOD}/../assets/',bp.model_refs(fps[self.uid])[0]);self.assertEqual(bp.model_refs(fps[self.uid2]),[str(self.model)])
        placements=sy.placed_symbols((self.opt.output/self.sch.name).read_text());self.assertEqual(placements[1]['lib_id'],'Device:R')
    def test_unextracted_selection_relink_blocks(self):
        sel=w.Selection(models={self.uid});self.opt.include_external=True;self.prep('unbundle',sel=sel).apply()
        with self.assertRaisesRegex(ValueError,'Footprints were not extracted'):self.prep('relink')
    def test_new_folder_required(self):
        self.opt.output.mkdir()
        with self.assertRaisesRegex(ValueError,'NEW'):self.prep()
    def test_validation_failure_keeps_originals_and_no_design(self):
        plan=self.prep();before=self.pcb.read_bytes()
        def fail(_):raise ValueError('native check failure')
        with self.assertRaisesRegex(ValueError,'native check failure'):plan.apply(validate=fail)
        self.assertEqual(self.pcb.read_bytes(),before);self.assertFalse(self.opt.output.exists())
    def test_combined_failure_leaves_extracted_assets_no_design(self):
        self.opt.include_external=True;plan=self.prep('unbundle-relink')
        def fail(_):raise ValueError('blocked')
        with self.assertRaises(ValueError):plan.apply(validate=fail)
        self.assertTrue(self.opt.assets.exists());self.assertFalse(self.opt.output.exists())
    def test_cancelled_apply_no_design(self):
        plan=self.prep()
        with self.assertRaises(InterruptedError):plan.apply(cancelled=lambda:True)
        self.assertFalse(self.opt.output.exists())
    def test_empty_selection_refused(self):
        with self.assertRaisesRegex(ValueError,'at least one'):w.prepare_operation(self.inv,w.Selection(),'embed',self.opt)
    def test_plan_cannot_run_twice(self):
        plan=self.prep();plan.apply()
        with self.assertRaisesRegex(ValueError,'already run'):plan.apply()
    def test_hierarchy_copied_when_only_pcb_models_selected(self):
        (self.root/'child.kicad_sch').write_text(schematic())
        self.sch.write_text(schematic(extra=child('child.kicad_sch')));self.inv=w.scan_design(self.pcb,self.sch)
        self.prep(sel=w.Selection(models={self.uid})).apply()
        self.assertTrue((self.opt.output/'child.kicad_sch').is_file())
    def test_absolute_path_mode_mixed_project_tables(self):
        self.opt.path_mode='absolute';self.opt.include_external=True
        (self.root/'fp-lib-table').write_text('(fp_lib_table (lib (name "Other") (type "KiCad") (uri "${KIPRJMOD}/Other.pretty") (options "") (descr "")))')
        plan=self.prep('unbundle-relink');plan.apply()
        text=(self.opt.output/'fp-lib-table').read_text();self.assertIn((self.root/'Other.pretty').as_posix(),text)
    def test_renamed_symbol_nickname_existing_entry_not_replaced(self):
        (self.root/'sym-lib-table').write_text('(sym_lib_table (lib (name "WayriCAD_Embed3D_Symbols") (type "KiCad") (uri "/original/a.kicad_sym") (options "") (descr "")))')
        self.prep().apply();text=(self.opt.output/'sym-lib-table').read_text()
        self.assertIn('WayriCAD_Embed3D_Symbols_2',text);self.assertIn('/original/a.kicad_sym',text)

    def test_duplicate_uuid_board_blocked(self):
        self.pcb.write_text(board([placed(self.uid,'R1','Lib:X',None),placed(self.uid,'R2','Lib:X',None)]))
        with self.assertRaisesRegex(ValueError,'Duplicate PCB footprint UUID'):w.scan_design(self.pcb)
    def test_duplicate_reference_symbols_independently_selectable(self):
        self.sch.write_text(schematic(instances=[instance(self.uid,ref='R1'),instance(self.uid2,ref='R1')]))
        inv=w.scan_design(schematic=self.sch);self.assertEqual(len(inv.rows),2)
        inv.select_all(value=False);inv.rows[0].checked['symbols']=True
        self.assertEqual(inv.selection().counts()['symbols'],1)
    def test_absolute_embed_with_project_relative_existing_tables(self):
        (self.root/'fp-lib-table').write_text('(fp_lib_table (lib (name "Other") (type "KiCad") (uri "${KIPRJMOD}/Other.pretty") (options "") (descr "")))')
        (self.root/'sym-lib-table').write_text('(sym_lib_table (lib (name "Other") (type "KiCad") (uri "${KIPRJMOD}/Other.kicad_sym") (options "") (descr "")))')
        self.opt.path_mode='absolute';self.prep().apply()
        self.assertIn((self.root/'Other.pretty').as_posix(),(self.opt.output/'fp-lib-table').read_text())
    def test_new_sidecar_after_preview_requires_refresh(self):
        plan=self.prep();(self.root/'sym-lib-table').write_text('(sym_lib_table)')
        with self.assertRaisesRegex(ValueError,'sidecar appeared'):plan.apply()
    def test_unknown_component_selection_rejected(self):
        with self.assertRaisesRegex(ValueError,'unavailable'):w.prepare_operation(self.inv,w.Selection(models={'fake'}),'embed',self.opt)
    def test_only_footprint_unbundle_keeps_internal_model_bytes(self):
        embedded=Planner(Resolver(self.root)).scan(placed(self.uid,'R1','Lib:Part',self.model)).build()
        self.pcb.write_text(board([embedded]));self.inv=w.scan_design(self.pcb,self.sch)
        self.norm={self.uid:('One',rename_snapshot(embedded,'One'))}
        sel=w.Selection(footprints={self.uid});plan=self.prep('unbundle',sel=sel);plan.apply()
        files=list(self.opt.assets.rglob('*.kicad_mod'));self.assertEqual(len(files),1)
        self.assertTrue(embedded_entries(files[0].read_text()));self.assertFalse(list(self.opt.assets.rglob('*.step')))
    def test_global_clear_preserves_unsupported_cells(self):
        self.pcb.write_text(board([placed(self.uid,'J1','Lib:X',None)]));inv=w.scan_design(self.pcb)
        inv.select_all('models');self.assertFalse(inv.rows[0].checked['models'])
    def test_alias_paths_in_unknown_unselected_resources_left_external(self):
        text=self.pcb.read_text();fp=parse(text).nodes(text,'footprint')[1];raw=fp.raw(text);model=parse(raw).nodes(raw,'model')[0]
        raw=patch(raw,[(model.arg().start,model.arg().end,quote('${MY_CUSTOM}/thing.step'))])
        self.pcb.write_text(patch(text,[(fp.start,fp.end,raw)]));self.inv=w.scan_design(self.pcb,self.sch)
        self.prep(sel=w.Selection(models={self.uid})).apply()
        self.assertIn('${MY_CUSTOM}/thing.step',(self.opt.output/self.pcb.name).read_text())
    def test_combined_assets_cannot_be_inside_new_design_folder(self):
        self.opt.assets=self.opt.output/'assets'
        with self.assertRaisesRegex(ValueError,'outside'):self.prep('unbundle-relink')
    def test_relink_legacy_single_pcb_extraction_folder(self):
        extract_pcb(self.pcb,self.opt.assets,footprints=False,include_external=True).publish(self.opt.assets)
        self.prep('relink',sel=w.Selection(models={self.uid})).apply()
        self.assertIn('${KIPRJMOD}/../assets/models/',(self.opt.output/self.pcb.name).read_text())
    def test_unselected_embedded_models_are_not_removed_by_partial_prune(self):
        self.prep().apply();self.pcb=self.opt.output/self.pcb.name;self.sch=self.opt.output/self.sch.name
        self.inv=w.scan_design(self.pcb,self.sch);self.norm,_=w.archived_normalized(self.pcb,{self.uid,self.uid2})
        self.opt=w.Options(self.root/'external-assets',self.root/'external-design',prune=True)
        self.prep('unbundle-relink',sel=w.Selection(footprints={self.uid},models={self.uid})).apply()
        text=(self.opt.output/self.pcb.name).read_text();records=w.read_component_archive(text)
        self.assertEqual(set(records),{self.uid2})
        fps=self.fpmap(text);self.assertTrue(bp.model_refs(fps[self.uid2])[0].startswith(PREFIX))
        self.assertIn(bp.model_refs(fps[self.uid2])[0][len(PREFIX):],embedded_entries(text))
    def test_all_selected_prune_removes_selective_archive(self):
        self.prep().apply();self.pcb=self.opt.output/self.pcb.name;self.sch=self.opt.output/self.sch.name
        self.inv=w.scan_design(self.pcb,self.sch);self.norm,_=w.archived_normalized(self.pcb,{self.uid,self.uid2})
        self.opt=w.Options(self.root/'external-assets',self.root/'external-design',prune=True,
                           footprint_nickname='ExternalFP',symbol_nickname='ExternalSymbols')
        self.prep('unbundle-relink').apply()
        text=(self.opt.output/self.pcb.name).read_text();pool=embedded_entries(text)
        self.assertNotIn(w.ARCHIVE,pool);self.assertFalse(any(k.endswith('.kicad_mod') for k in pool))
        self.assertFalse(any(k.endswith('.step') for k in pool))
    def test_partial_symbols_prune_keeps_shared_archive(self):
        sy.embed_symbols(self.sch,self.root/'sym-embedded',apply=True)
        self.sch=self.root/'sym-embedded'/self.sch.name;self.inv=w.scan_design(schematic=self.sch)
        self.opt=w.Options(self.root/'symbol-assets',self.root/'sym-external',prune=True)
        plan=w.prepare_operation(self.inv,w.Selection(symbols={self.sch.name:{self.uid}}),'unbundle-relink',self.opt)
        plan.apply();after=(self.opt.output/self.sch.name).read_text()
        self.assertIn(sy.SCH_ARCHIVE,embedded_entries(after));self.assertEqual(sy.placed_symbols(after)[1]['lib_id'],'Device:R')
    def test_no_relink_on_embed_option_keeps_both_ids(self):
        self.opt.local_links=False;self.prep().apply()
        after=(self.opt.output/self.pcb.name).read_text();fps=self.fpmap(after)
        self.assertEqual(parse(fps[self.uid]).arg().value(fps[self.uid]),'Lib:Part')
        after=(self.opt.output/self.sch.name).read_text();self.assertEqual(sy.placed_symbols(after)[0]['lib_id'],'Device:R')
    def test_asset_manifest_tampering_blocks(self):
        self.opt.include_external=True;self.prep('unbundle').apply()
        path=self.opt.assets/'pcb'/'WayriCAD Embed3D-extraction.json';path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'manifest changed'):self.prep('relink')
