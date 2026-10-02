import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from contextlib import nullcontext

ROOT=Path(__file__).resolve().parents[1];PACKAGE='_fusion_linked_native_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
i=importlib.import_module(PACKAGE+'.insertion');l=importlib.import_module(PACKAGE+'.linked_updates')
sx=importlib.import_module(PACKAGE+'.sexpr');model=importlib.import_module(PACKAGE+'.model')
from test_sections_native import make_fixture

@unittest.skipUnless(os.environ.get('FUSION_NATIVE_LINKED')=='1','Opt-in native linked update')
class NativeLinkedTests(unittest.TestCase):
    def test_two_successive_schematic_updates_stable_ids_and_major_rewire(self):
        retained=os.environ.get('FUSION_NATIVE_LINKED_OUTPUT')
        if retained:Path(retained).mkdir(parents=True,exist_ok=False)
        context=nullcontext(retained) if retained else tempfile.TemporaryDirectory(prefix='fusion-native-linked-')
        with context as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            source=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            insertion=i.preview_import(target.project,[source],False,base/'inserted');i.apply_import(insertion)
            rows=l.scan_links(target.project)['links'];self.assertEqual(rows[0]['status'],'current')
            link_id=rows[0]['id'];_,old=l._load(target.project);original=old['links'][0]
            child=sx.load(base/'source/child.kicad_sch');sx.prop(sx.children(child,'symbol')[0],'Value')[2]=sx.q('22k');sx.save(base/'source/child.kicad_sch',child)
            row=l.scan_links(target.project)['links'][0];self.assertEqual(row['status'],'changed');self.assertEqual(row['major_changes'],0)
            update=l.preview_update(target.project,[link_id],base/'minor');i.apply_import(json.loads(json.dumps(update)))
            _,after=l._load(target.project);current=after['links'][0]
            self.assertEqual(original['wrapper_uuid'],current['wrapper_uuid']);self.assertEqual(original['symbol_refs'],current['symbol_refs'])
            self.assertEqual(original['schematic_ids'],current['schematic_ids'])
            child=sx.load(base/'source/child.kicad_sch')
            for start,end in (((20,16.19),(15,16.19)),((15,16.19),(15,23.81)),((15,23.81),(20,23.81))):
                child.append(['wire',['pts',['xy',str(start[0]),str(start[1])],['xy',str(end[0]),str(end[1])]],['stroke',['width','0'],['type','default']],['uuid',sx.q(l.new_uuid())]])
            sx.save(base/'source/child.kicad_sch',child)
            row=l.scan_links(target.project)['links'][0];self.assertGreater(row['major_changes'],0)
            self.assertTrue(any(change['category']=='pin_connection' for change in row['changes']))
            with self.assertRaisesRegex(model.MergeError,'major source changes'):l.preview_update(target.project,[link_id],base/'no-ack')
            major=l.preview_update(target.project,[link_id],base/'major',acknowledge_major=True);i.apply_import(major)
            _,after=l._load(target.project);final=after['links'][0]
            self.assertEqual(original['wrapper_uuid'],final['wrapper_uuid']);self.assertEqual(original['symbol_refs'],final['symbol_refs'])
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'current')
            (base/'source/board.kicad_pcb').write_text('invalid PCB ignored by schematic-only links')
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'current')


    def test_routed_update_stable_geometry_and_destination_conflict(self):
        retained=os.environ.get('FUSION_NATIVE_LINKED_ROUTED_OUTPUT')
        if retained:Path(retained).mkdir(parents=True,exist_ok=False)
        context=nullcontext(retained) if retained else tempfile.TemporaryDirectory(prefix='fusion-native-linked-routing-')
        with context as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            source=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            i.apply_import(i.preview_import(target.project,[source],True,base/'inserted'))
            _,manifest=l._load(target.project);old=manifest['links'][0];link_id=old['id']
            child=sx.load(base/'source/child.kicad_sch');sx.prop(sx.children(child,'symbol')[0],'Value')[2]=sx.q('22k');sx.save(base/'source/child.kicad_sch',child)
            scanned=l.scan_links(target.project)['links'][0]
            self.assertEqual(scanned['major_changes'],0,json.dumps(scanned['changes'],indent=2))
            plan=l.preview_update(target.project,[link_id],base/'minor');i.apply_import(plan)
            _,manifest=l._load(target.project);new=manifest['links'][0]
            self.assertEqual(old['pcb_uuid_map'],new['pcb_uuid_map']);self.assertEqual(old['symbol_refs'],new['symbol_refs'])
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'current')
            import copy
            board=sx.load(Path(target.project).with_suffix('.kicad_pcb'));saved=copy.deepcopy(board)
            item=next(n for n in sx.children(board,'segment') if sx.value(n,'uuid') in new['pcb_item_ids'])
            foreign=copy.deepcopy(item);sx.child(foreign,'uuid')[1]=sx.q(l.new_uuid())
            unrelated=next(fp for fp in sx.children(board,'footprint') if sx.value(fp,'uuid') not in new['pcb_item_ids'])
            foreign_net=copy.deepcopy(sx.child(sx.children(unrelated,'pad')[0],'net'));foreign[:]=[n for n in foreign if sx.tag(n)!='net'];foreign.append(foreign_net)
            board.append(foreign);sx.save(Path(target.project).with_suffix('.kicad_pcb'),board)
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'conflict')
            with self.assertRaisesRegex(model.MergeError,'Destination conflict'):l.preview_update(target.project,[link_id],base/'crossblock-conflict')
            sx.save(Path(target.project).with_suffix('.kicad_pcb'),saved);board=saved
            item=next(n for n in sx.children(board,'segment') if sx.value(n,'uuid') in new['pcb_item_ids'])
            sx.child(item,'width')[1]='0.333';sx.save(Path(target.project).with_suffix('.kicad_pcb'),board)
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'conflict')
            with self.assertRaisesRegex(model.MergeError,'Destination conflict'):l.preview_update(target.project,[link_id],base/'conflict')

    def test_schematic_structural_add_delete_preserves_survivor_reference(self):
        import copy
        with tempfile.TemporaryDirectory(prefix='fusion-native-linked-structure-') as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            child=sx.load(base/'source/child.kicad_sch');second=copy.deepcopy(sx.children(child,'symbol')[0]);second_uid=l.new_uuid()
            sx.child(second,'uuid')[1]=sx.q(second_uid);sx.prop(second,'Reference')[2]=sx.q('R2')
            for node in sx.walk(second):
                if sx.tag(node)=='reference':node[1]=sx.q('R2')
                if sx.tag(node)=='at' and len(node)>2:node[1]=str(float(node[1])+20)
            child.append(second);sx.save(base/'source/child.kicad_sch',child)
            source=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            i.apply_import(i.preview_import(target.project,[source],False,base/'inserted'))
            _,manifest=l._load(target.project);old=manifest['links'][0];survivor=next(k for k in old['symbol_refs'] if k.endswith('/'+second_uid));old_ref=old['symbol_refs'][survivor]
            child=sx.load(base/'source/child.kicad_sch');child.remove(sx.children(child,'symbol')[0]);third=copy.deepcopy(sx.children(child,'symbol')[0]);third_uid=l.new_uuid()
            sx.child(third,'uuid')[1]=sx.q(third_uid);sx.prop(third,'Reference')[2]=sx.q('R3')
            for node in sx.walk(third):
                if sx.tag(node)=='reference':node[1]=sx.q('R3')
                if sx.tag(node)=='at' and len(node)>2:node[1]=str(float(node[1])+20)
            child.append(third);sx.save(base/'source/child.kicad_sch',child)
            plan=l.preview_update(target.project,[old['id']],base/'structural',acknowledge_major=True);i.apply_import(plan)
            _,manifest=l._load(target.project);new=manifest['links'][0]
            self.assertEqual(new['symbol_refs'][survivor],old_ref)
            self.assertEqual(len(set(new['symbol_refs'].values())),2)
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'current')

    def test_section_link_follows_original_project_after_materialization_removed(self):
        sections=importlib.import_module(PACKAGE+'.sections')
        with tempfile.TemporaryDirectory(prefix='fusion-native-linked-section-') as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');original,sheet_path=make_fixture(base/'original')
            materialized=sections.apply_schematic_sections(sections.preview_schematic_sections(original,[sheet_path]),base/'materialized')[0]
            i.apply_import(i.preview_import(target.project,[materialized],False,base/'inserted'))
            import shutil
            shutil.rmtree(base/'materialized')
            child=sx.load(base/'original/child.kicad_sch');sx.prop(sx.children(child,'symbol')[0],'Value')[2]=sx.q('33k');sx.save(base/'original/child.kicad_sch',child)
            row=l.scan_links(target.project)['links'][0];self.assertEqual(row['status'],'changed')
            plan=l.preview_update(target.project,[row['id']],base/'section-update');i.apply_import(json.loads(json.dumps(plan)))
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'current')
            _,manifest=l._load(target.project)
            self.assertEqual(manifest['links'][0]['source_spec']['project'],original.project)
            self.assertFalse(any('fusion-linked-update-' in item['original_path'] for item in plan['source_file_hashes']))

            local_before=l.fingerprint(Path(target.project).parent)
            shutil.rmtree(base/'original')
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'missing_source')
            break_plan=l.preview_break_links(target.project,[row['id']],base/'break-links');broken=i.apply_import(break_plan)
            self.assertEqual(l.list_links(target.project),[])
            undo=l.preview_undo(target.project,broken['backup_directory'],base/'undo-break');i.apply_import(undo)
            self.assertEqual(l.fingerprint(Path(target.project).parent),local_before)
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'missing_source')

    def test_new_combined_project_links_and_updates_source_value(self):
        engine=importlib.import_module(PACKAGE+'.engine')
        with tempfile.TemporaryDirectory(prefix='fusion-native-linked-combined-') as folder:
            base=Path(folder).resolve();first,_=make_fixture(base/'first');second,_=make_fixture(base/'second')
            first=model.SourceSpec(first.project,'Unit1',variant='<Default>');second=model.SourceSpec(second.project,'Unit2',variant='<Default>')
            result=engine.merge(model.Options([first,second],str(base/'combined'),name='Combined',acknowledge_outline_change=True,accept_primary_settings=True,saved_sources_confirmed=True))
            project=Path(result['project']);rows=l.scan_links(project)['links']
            self.assertEqual(len(rows),2);self.assertTrue(all(row['status']=='current' for row in rows))
            row=next(row for row in rows if row['alias']=='Unit1');_,manifest=l._load(project);old=next(link for link in manifest['links'] if link['id']==row['id'])
            child=sx.load(base/'first/child.kicad_sch');sx.prop(sx.children(child,'symbol')[0],'Value')[2]=sx.q('47k');sx.save(base/'first/child.kicad_sch',child)
            plan=l.preview_update(project,[row['id']],base/'updated');i.apply_import(plan)
            _,manifest=l._load(project);new=next(link for link in manifest['links'] if link['id']==row['id'])
            self.assertEqual(old['symbol_refs'],new['symbol_refs']);self.assertEqual(old['pcb_uuid_map'],new['pcb_uuid_map'])
            self.assertTrue(all(row['status']=='current' for row in l.scan_links(project)['links']))
