import copy
import importlib
import sys
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];PACKAGE='_fusion_linked_unit_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
l=importlib.import_module(PACKAGE+'.linked_updates');m=importlib.import_module(PACKAGE+'.model');sx=importlib.import_module(PACKAGE+'.sexpr')

class LinkedUnitTests(unittest.TestCase):
    def test_link_reextraction_retains_root_and_depth_selection(self):
        from dataclasses import asdict
        sections=importlib.import_module(PACKAGE+'.sections')
        original=m.SourceSpec('C:/Projects/Example/board.kicad_pro','Source')
        for region in (None,[0,0,20,20]):
            spec=m.SourceSpec('C:/Projects/Example/copy.kicad_pro','Source',section_origin={
                'project':original.project,'sheet_path':'/root','region_mm':region,'max_depth':0})
            link={'source_spec':asdict(spec),'origin_spec':asdict(original),'source_root_uuid':'root',
                  'alias':'Imported','include_layout':region is not None}
            with patch.object(l,'_snapshot',return_value={'root_uuid':'root','hashes':{},'variant':'<Default>'}), \
                 patch.object(l,'_section_snapshot',return_value={}), \
                 patch.object(sections,'preview_schematic_sections',return_value={}) as schematic_preview, \
                 patch.object(sections,'apply_schematic_sections',return_value=[spec]), \
                 patch.object(sections,'preview_section',return_value={}) as board_preview, \
                 patch.object(sections,'apply_section',return_value=spec):
                l._live_source(link,Path('.'),'',{})
                preview=schematic_preview if region is None else board_preview
                self.assertEqual(preview.call_args.kwargs['max_depth'],0)
                if region is None:self.assertTrue(preview.call_args.kwargs['allow_root'])

    def test_snapshot_cache_separates_layout_and_alias_does_not_duplicate_export(self):
        spec=m.SourceSpec('C:/Projects/Example/board.kicad_pro','Unit1',variant='<Default>');cache={}
        with patch.object(l,'snapshot_source',return_value={'symbols':{}}) as snapshot:
            l._snapshot(spec,'',cache,False);other=copy.deepcopy(spec);other.alias='Unit2'
            l._snapshot(other,'',cache,False);l._snapshot(spec,'',cache,True)
            self.assertEqual(snapshot.call_count,2)
            self.assertFalse(snapshot.call_args_list[0].kwargs['include_layout'])
            self.assertTrue(snapshot.call_args_list[1].kwargs['include_layout'])

    def test_reference_rebase_preserves_prose_and_rewrites_explicit_field_links(self):
        tree=sx.loads('(kicad_sch (symbol (property "Reference" "R2") (property "Value" "R2 value") (instances (reference "R2"))) (text "${R2:Value}"))')
        l._rewrite_refs(tree,{'R2':'R8'})
        self.assertEqual(sx.prop(sx.children(tree,'symbol')[0],'Reference')[2],'R8')
        self.assertEqual(sx.prop(sx.children(tree,'symbol')[0],'Value')[2],'R2 value')
        self.assertEqual(sx.children(tree,'text')[0][1],'${R8:Value}')

    def test_approved_identity_bindings_must_be_one_to_one(self):
        with self.assertRaisesRegex(m.MergeError,'one-to-one'):
            l._stable_maps({}, {}, {'old1':'new','old2':'new'})

    def test_manual_binding_does_not_replace_routed_footprint_identity(self):
        old={'include_layout':True,'source_baseline':{'symbols':{'/root/a':{}},'board_items':{'fp-old':{'kind':'footprint','symbol':'/root/a'}}}}
        fresh={'source_baseline':{'symbols':{'/root/b':{}},'board_items':{'fp-new':{'kind':'footprint','symbol':'/root/b'}}}}
        with self.assertRaisesRegex(m.MergeError,'routed footprint UUID'):
            l._stable_maps(old,fresh,{'/root/a':'/root/b'})

    def test_stable_occurrence_references_and_item_uuids(self):
        old={'source_baseline':{'symbols':{}},'schematic_ids':{'/root':{'symbol':'target-symbol'}},'wrapper_uuid':'old-wrapper','pcb_uuid_map':{'track':'old-track'},'symbol_refs':{'/root/symbol':'R9'},'reference_map':{'R1':'R9'}}
        fresh={'source_baseline':{'symbols':{}},'schematic_ids':{'/root':{'symbol':'fresh-symbol'}},'wrapper_uuid':'fresh-wrapper','pcb_uuid_map':{'track':'fresh-track'},'symbol_refs':{'/root/symbol':'R2'},'reference_map':{'R1':'R2'}}
        ids,refs=l._stable_maps(old,fresh,{})
        self.assertEqual(ids,{'fresh-symbol':'target-symbol','fresh-wrapper':'old-wrapper','fresh-track':'old-track'})
        self.assertEqual(refs,{'R2':'R9'})

    def test_break_missing_source_undo_verified_and_stale_refused(self):
        import tempfile,json
        insertion=importlib.import_module(PACKAGE+'.insertion')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'target';root.mkdir();project=root/'board.kicad_pro';project.write_text('{}')
            sx.save(project.with_suffix('.kicad_sch'),sx.loads('(kicad_sch (uuid "root"))'))
            (root/'board.kicad_pcb').write_text('saved layout bytes')
            l._write(root,{'schema':1,'target_root_uuid':'root','links':[{'id':'link','source_spec':{'project':'C:/Missing/source.kicad_pro'}}]})
            original=l.fingerprint(root)
            plan=l.preview_break_links(project,['link'],Path(folder)/'broken')
            self.assertEqual(l.fingerprint(root),original);self.assertEqual(plan['report']['sources_accessed'],False)
            result=insertion.apply_import(plan);self.assertEqual(l._load(project)[1]['links'],[])
            self.assertTrue(l.list_transactions(project)[0]['eligible'])
            undo=l.preview_undo(project,result['backup_directory'],Path(folder)/'undo')
            insertion.apply_import(json.loads(json.dumps(undo)));self.assertEqual(l.fingerprint(root),original)
            (root/'board.kicad_pcb').write_text('local edit')
            with self.assertRaisesRegex(m.MergeError,'local edits'):l.preview_undo(project,result['backup_directory'],Path(folder)/'stale')

    def test_undo_removes_only_transaction_created_files_and_preserves_redo_backup(self):
        import tempfile
        insertion=importlib.import_module(PACKAGE+'.insertion')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'target';root.mkdir();project=root/'board.kicad_pro';project.write_text('{}');(root/'empty').mkdir()
            original=l.fingerprint(root);candidate=Path(folder)/'candidate';l.copy_project(root,candidate);(candidate/'created').mkdir();(candidate/'created/new.txt').write_text('new import asset')
            result=insertion.apply_import({'target_project':str(project),'target_hashes':original,'source_hashes':[],'candidate_directory':str(candidate),'candidate_hashes':l.fingerprint(candidate),'report':{}})
            plan=l.preview_undo(project,result['backup_directory'],Path(folder)/'undo');redo=insertion.apply_import(plan)
            self.assertEqual(l.fingerprint(root),original);self.assertTrue((root/'empty').is_dir());self.assertFalse((root/'created/new.txt').exists())
            self.assertTrue((Path(redo['backup_directory'])/'project/created/new.txt').is_file())

    def test_failed_undo_removal_rolls_back_all_transaction_files(self):
        import tempfile
        insertion=importlib.import_module(PACKAGE+'.insertion')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'target';root.mkdir();project=root/'board.kicad_pro';project.write_text('{}')
            original=l.fingerprint(root);candidate=Path(folder)/'candidate';l.copy_project(root,candidate)
            for name in ('a.txt','b.txt'):(candidate/name).write_text(name)
            result=insertion.apply_import({'target_project':str(project),'target_hashes':original,'source_hashes':[],'candidate_directory':str(candidate),'candidate_hashes':l.fingerprint(candidate),'report':{}})
            before=l.fingerprint(root);plan=l.preview_undo(project,result['backup_directory'],Path(folder)/'undo')
            native_unlink=Path.unlink
            def fail_second(path,*args,**kwargs):
                if path==root/'b.txt':raise OSError('injected undo removal failure')
                return native_unlink(path,*args,**kwargs)
            with patch.object(Path,'unlink',fail_second):
                with self.assertRaisesRegex(OSError,'injected undo'):insertion.apply_import(plan)
            self.assertEqual(l.fingerprint(root),before)

    def test_unowned_footprint_pad_linked_net_is_destination_conflict(self):
        from types import SimpleNamespace
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            project=Path(folder)/'board.kicad_pro';project.write_text('{}')
            sx.save(project.with_suffix('.kicad_pcb'),sx.loads('(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (net 1 "Linked/net") (footprint (uuid "unrelated") (pad "1" smd rect (uuid "pad") (net 1 "Linked/net"))))'))
            link={'target_baseline':{},'reference_map':{'R1':'R2'},'pcb_item_ids':[],'net_names':['Linked/net']}
            with patch.object(l,'_scope',return_value={}):
                conflicts=l._conflicts(project,link,SimpleNamespace(nets={}))
            self.assertEqual(conflicts[0]['category'],'external_copper');self.assertEqual(conflicts[0]['pads'],['1'])

    def test_crossblock_unconnected_routes_same_layer_touch_but_other_layer_safe(self):
        board=sx.loads('(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (segment (uuid "owned") (start 0 0) (end 10 0) (width 0.2) (layer "F.Cu")) (segment (uuid "foreign") (start 5 -1) (end 5 1) (width 0.2) (layer "F.Cu")))')
        self.assertEqual(l._route_collisions(board,{'owned'})[0]['outside_uuid'],'foreign')
        sx.child(sx.children(board,'segment')[1],'layer')[1]=sx.q('B.Cu')
        self.assertEqual(l._route_collisions(board,{'owned'}),[])
        board.append(sx.loads('(via (uuid "foreign-via") (at 5 0) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu"))'))
        self.assertEqual(l._route_collisions(board,{'owned'})[0]['outside_uuid'],'foreign-via')

    def test_complex_copper_envelope_crossblock_is_conservative_refusal(self):
        board=sx.loads('(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (segment (uuid "owned") (start 0 0) (end 10 0) (width 0.2) (layer "F.Cu")) (zone (uuid "outside-zone") (layer "F.Cu") (polygon (pts (xy 4 -1) (xy 6 -1) (xy 6 1) (xy 4 1)))))')
        self.assertIn('cannot be proven',l._route_collisions(board,{'owned'})[0]['message'])
        sx.child(sx.children(board,'zone')[0],'layer')[1]=sx.q('B.Cu')
        self.assertEqual(l._route_collisions(board,{'owned'}),[])
        board.append(sx.loads('(arc (uuid "outside-arc") (start 4 0) (mid 5 1) (end 6 0) (width 0.2) (layer "F.Cu"))'))
        self.assertEqual(l._route_collisions(board,{'owned'})[0]['outside_uuid'],'outside-arc')
