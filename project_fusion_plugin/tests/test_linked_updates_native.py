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
    def test_layout_only_inherits_source_board_and_preserves_target_schematic(self):
        with tempfile.TemporaryDirectory(prefix='fusion-native-link-board-only-') as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            imported=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            i.apply_import(i.preview_import(target.project,[imported],True,base/'inserted'))
            _,manifest=l._load(target.project);old=manifest['links'][0]
            target_board=Path(target.project).with_suffix('.kicad_pcb')
            old_board=sx.load(target_board)
            linked_fp=next(fp for fp in sx.children(old_board,'footprint')
                           if sx.value(fp,'uuid') in old['pcb_item_ids'])
            before_x=float(sx.child(linked_fp,'at')[1])
            target_child=next(Path(target.project).parent/name for name in old['sheet_files']
                              if sx.children(sx.load(Path(target.project).parent/name),'symbol'))
            child=sx.load(target_child);symbol=sx.children(child,'symbol')[0]
            sx.prop(symbol,'Value')[2]=sx.q('47k')
            symbol.append(sx.loads('(property "MPN" "LOCAL-47K" (at 20 22 0) (effects (font (size 1.27 1.27)) (hide yes)))'))
            sx.save(target_child,child)
            # Keep the starting destination electrically/field consistent,
            # as it would be after KiCad's Update PCB from Schematic.
            import pcbnew
            native_board=pcbnew.LoadBoard(str(target_board))
            for native_fp in native_board.GetFootprints():
                if native_fp.GetReference()==sx.propval(linked_fp,'Reference'):
                    native_fp.SetField('Value','47k')
                    native_fp.SetField('MPN','LOCAL-47K')
            pcbnew.SaveBoard(str(target_board),native_board)
            saved_sheets={str(path.relative_to(Path(target.project).parent)):path.read_bytes()
                          for path in l.project_files(Path(target.project).parent) if path.suffix=='.kicad_sch'}
            saved_project=Path(target.project).read_bytes()
            board_path=base/'source/board.kicad_pcb';source_board=sx.load(board_path)
            footprint=sx.children(source_board,'footprint')[0]
            source_child=next(path for path in l.project_files(base/'source') if path.suffix=='.kicad_sch'
                              and sx.children(sx.load(path),'symbol'))
            source_tree=sx.load(source_child)
            sx.prop(sx.children(source_tree,'symbol')[0],'Value')[2]=sx.q('22k')
            sx.save(source_child,source_tree)
            sx.prop(footprint,'Value')[2]=sx.q('22k')
            old_x=float(sx.child(footprint,'at')[1])
            sx.child(footprint,'at')[1]=str(old_x+0.2)
            segment=min(sx.children(source_board,'segment'),
                        key=lambda item:abs(float(sx.child(item,'start')[1])-old_x))
            sx.child(segment,'start')[1]=str(float(sx.child(segment,'start')[1])+0.2)
            sx.save(board_path,source_board)
            source_hash=l.fingerprint(base/'source')
            plan=l.preview_update(target.project,[old['id']],base/'board-only',acknowledge_major=True,
                                  layout_only=True)
            self.assertTrue(plan['report']['layout_only'])
            self.assertEqual(l.fingerprint(base/'source'),source_hash)
            i.apply_import(plan)
            for name,data in saved_sheets.items():
                self.assertEqual((Path(target.project).parent/name).read_bytes(),data)
            self.assertEqual(Path(target.project).read_bytes(),saved_project)
            updated=sx.load(target_board)
            footprint=next(fp for fp in sx.children(updated,'footprint')
                           if sx.value(fp,'uuid')==sx.value(linked_fp,'uuid'))
            self.assertAlmostEqual(float(sx.child(footprint,'at')[1])-before_x,0.2,places=4)
            self.assertEqual(sx.propval(footprint,'Value'),'47k')
            self.assertEqual(sx.propval(sx.children(sx.load(target_child),'symbol')[0],'MPN'),'LOCAL-47K')
            _,after=l._load(target.project)
            self.assertEqual(after['links'][0]['id'],old['id'])
            self.assertEqual(after['links'][0]['pcb_uuid_map'],old['pcb_uuid_map'])
            again=l.preview_update(target.project,[old['id']],base/'board-only-repeat',acknowledge_major=True,
                                   layout_only=True)
            self.assertTrue(again['report']['layout_only'])
            edited=sx.load(target_board)
            changed=next(fp for fp in sx.children(edited,'footprint')
                         if sx.value(fp,'uuid')==sx.value(linked_fp,'uuid'))
            sx.child(changed,'at')[1]=str(float(sx.child(changed,'at')[1])+0.1)
            sx.save(target_board,edited)
            with self.assertRaisesRegex(model.MergeError,'Destination conflict'):
                l.preview_update(target.project,[old['id']],base/'board-only-local-conflict',
                                 acknowledge_major=True,layout_only=True)

    @staticmethod
    def replace_source_resistor_footprint(folder, library_name='R_1206_3216Metric'):
        import copy
        import pcbnew
        resources=Path(pcbnew.__file__).parents[2]/'share/kicad'
        if not resources.is_dir():resources=Path('C:/Program Files/KiCad/10.0/share/kicad')
        template=sx.load(resources/'footprints/Resistor_SMD.pretty'/(library_name+'.kicad_mod'))
        pcb=folder/'board.kicad_pcb';board=sx.load(pcb);footprint=sx.children(board,'footprint')[0]
        footprint[1]=sx.q('Resistor_SMD:'+library_name)
        previous={str(pad[1]):pad for pad in sx.children(footprint,'pad')}
        physical={'pad','fp_line','fp_rect','fp_arc','fp_circle','fp_poly','model'}
        footprint[:]=[node for node in footprint if sx.tag(node) not in physical]
        for item in sx.children(template):
            if sx.tag(item) not in physical:continue
            item=copy.deepcopy(item)
            if sx.tag(item)=='pad':
                old=previous[str(item[1])]
                sx.put(item,'uuid',sx.q(sx.value(old,'uuid')))
                if sx.child(old,'net') is not None:item.append(copy.deepcopy(sx.child(old,'net')))
            footprint.append(item)
        sx.save(pcb,board)
        child=sx.load(folder/'child.kicad_sch')
        sx.prop(sx.children(child,'symbol')[0],'Footprint')[2]=sx.q('Resistor_SMD:'+library_name)
        sx.save(folder/'child.kicad_sch',child)
        return footprint

    def test_retain_mode_replaces_0805_with_1206_and_checks_copper(self):
        with tempfile.TemporaryDirectory(prefix='fusion-native-link-package-') as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            imported=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            i.apply_import(i.preview_import(target.project,[imported],True,base/'inserted'))
            _,manifest=l._load(target.project);old=manifest['links'][0]
            board_path=Path(target.project).with_suffix('.kicad_pcb')
            original=sx.load(board_path)
            source_fp=self.replace_source_resistor_footprint(base/'source')
            plan=l.preview_update(target.project,[old['id']],base/'updated',acknowledge_major=True,
                                  retain_destination_layout=True)
            self.assertIn(old['pcb_uuid_map'][sx.value(source_fp,'uuid')],
                          plan['report']['changed_footprint_ids'])
            self.assertGreaterEqual(plan['report']['adjusted_track_endpoints'],1)
            i.apply_import(plan)
            updated=sx.load(board_path)
            uid=old['pcb_uuid_map'][sx.value(source_fp,'uuid')]
            old_fp=next(fp for fp in sx.children(original,'footprint') if sx.value(fp,'uuid')==uid)
            new_fp=next(fp for fp in sx.children(updated,'footprint') if sx.value(fp,'uuid')==uid)
            self.assertEqual(sx.child(old_fp,'at'),sx.child(new_fp,'at'))
            self.assertEqual(str(new_fp[1]).split(':')[-1],'R_1206_3216Metric')
            self.assertEqual([sx.child(pad,'at')[1] for pad in sx.children(new_fp,'pad')],
                             [sx.child(pad,'at')[1] for pad in sx.children(source_fp,'pad')])
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'current')

    def test_retain_mode_rejects_changed_pad_number_without_publishing(self):
        with tempfile.TemporaryDirectory(prefix='fusion-native-link-bad-pad-') as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            imported=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            i.apply_import(i.preview_import(target.project,[imported],True,base/'inserted'))
            _,manifest=l._load(target.project);link=manifest['links'][0]
            self.replace_source_resistor_footprint(base/'source')
            board_path=base/'source/board.kicad_pcb';board=sx.load(board_path)
            second=next(pad for pad in sx.children(sx.children(board,'footprint')[0],'pad') if str(pad[1])=='2')
            second[1]=sx.q('3')
            sx.save(board_path,board)
            original_hash=l.fingerprint(Path(target.project).parent)
            candidate=base/'rejected'
            with self.assertRaisesRegex(model.MergeError,'pad numbers|pad net|PCB pad'):
                l.preview_update(target.project,[link['id']],candidate,acknowledge_major=True,
                                 retain_destination_layout=True)
            self.assertFalse(candidate.exists())
            self.assertEqual(l.fingerprint(Path(target.project).parent),original_hash)

    def test_retain_mode_rejects_pad_moved_away_from_routed_copper(self):
        with tempfile.TemporaryDirectory(prefix='fusion-native-link-open-pad-') as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            imported=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            i.apply_import(i.preview_import(target.project,[imported],True,base/'inserted'))
            _,manifest=l._load(target.project);link=manifest['links'][0]
            self.replace_source_resistor_footprint(base/'source')
            board_path=base/'source/board.kicad_pcb';board=sx.load(board_path)
            first=next(pad for pad in sx.children(sx.children(board,'footprint')[0],'pad') if str(pad[1])=='1')
            sx.child(first,'at')[1]='-5'
            sx.save(board_path,board)
            original_hash=l.fingerprint(Path(target.project).parent)
            candidate=base/'rejected'
            with self.assertRaisesRegex(model.MergeError,'too far|unconnected copper|copper safety|pad net'):
                l.preview_update(target.project,[link['id']],candidate,acknowledge_major=True,
                                 retain_destination_layout=True)
            self.assertFalse(candidate.exists())
            self.assertEqual(l.fingerprint(Path(target.project).parent),original_hash)

    def test_schematic_value_bom_and_footprint_inherit_with_stable_identity(self):
        with tempfile.TemporaryDirectory(prefix='fusion-native-link-fields-') as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            imported=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            source_hashes=l.fingerprint(base/'source')
            i.apply_import(i.preview_import(target.project,[imported],False,base/'inserted'))
            _,before=l._load(target.project);old=before['links'][0]
            child=sx.load(base/'source/child.kicad_sch');symbol=sx.children(child,'symbol')[0]
            sx.prop(symbol,'Value')[2]=sx.q('22k')
            sx.prop(symbol,'Footprint')[2]=sx.q('Resistor_SMD:R_0805_2012Metric')
            symbol.append(sx.loads('(property "MPN" "RC0805-22K" (at 20 22 0) (effects (font (size 1.27 1.27)) (hide yes)))'))
            sx.save(base/'source/child.kicad_sch',child)
            edited_hashes=l.fingerprint(base/'source')
            self.assertNotEqual(source_hashes,edited_hashes)
            scan=l.scan_links(target.project)['links'][0]
            self.assertEqual(scan['status'],'changed')
            self.assertIn('footprint',{change['category'] for change in scan['changes']})
            with self.assertRaisesRegex(model.MergeError,'major source changes'):
                l.preview_update(target.project,[old['id']],base/'without-review')
            plan=l.preview_update(target.project,[old['id']],base/'updated',acknowledge_major=True)
            self.assertEqual(l.fingerprint(base/'source'),edited_hashes)
            i.apply_import(plan)
            _,after=l._load(target.project);new=after['links'][0]
            self.assertEqual(new['wrapper_uuid'],old['wrapper_uuid'])
            self.assertEqual(new['symbol_refs'],old['symbol_refs'])
            self.assertEqual(new['schematic_ids'],old['schematic_ids'])
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'current')
            imported_symbols=[symbol for name in new['sheet_files']
                              for symbol in sx.children(sx.load(Path(target.project).parent/name),'symbol')]
            self.assertEqual(len(imported_symbols),1)
            imported_symbol=imported_symbols[0]
            self.assertEqual(str(sx.prop(imported_symbol,'Value')[2]),'22k')
            self.assertTrue(str(sx.prop(imported_symbol,'Footprint')[2]).endswith(':R_0805_2012Metric'))
            self.assertEqual(str(sx.prop(imported_symbol,'MPN')[2]),'RC0805-22K')

    def test_routed_source_placement_update_preserves_linked_footprint_uuid(self):
        with tempfile.TemporaryDirectory(prefix='fusion-native-link-placement-') as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            imported=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            i.apply_import(i.preview_import(target.project,[imported],True,base/'inserted'))
            _,manifest=l._load(target.project);old=manifest['links'][0]
            source_board=base/'source/board.kicad_pcb';board=sx.load(source_board)
            footprint=sx.children(board,'footprint')[0]
            source_uid=sx.value(footprint,'uuid');target_uid=old['pcb_uuid_map'][source_uid]
            before=next(item for item in sx.children(sx.load(Path(target.project).with_suffix('.kicad_pcb')),'footprint')
                        if sx.value(item,'uuid')==target_uid)
            before_x=float(sx.child(before,'at')[1])
            footprint_x=float(sx.child(footprint,'at')[1])
            sx.child(footprint,'at')[1]=str(footprint_x+0.2)
            # Keep the connected pad endpoint attached as the footprint moves.
            segment=min(sx.children(board,'segment'),
                        key=lambda item:abs(float(sx.child(item,'start')[1])-footprint_x))
            sx.child(segment,'start')[1]=str(float(sx.child(segment,'start')[1])+0.2)
            sx.save(source_board,board)
            hashes=l.fingerprint(base/'source')
            row=l.scan_links(target.project)['links'][0]
            self.assertTrue(any(change['category']=='layout' for change in row['changes']))
            plan=l.preview_update(target.project,[old['id']],base/'updated',acknowledge_major=True)
            self.assertEqual(l.fingerprint(base/'source'),hashes)
            i.apply_import(plan)
            _,manifest=l._load(target.project);new=manifest['links'][0]
            self.assertEqual(new['pcb_uuid_map'][source_uid],target_uid)
            after=next(item for item in sx.children(sx.load(Path(target.project).with_suffix('.kicad_pcb')),'footprint')
                       if sx.value(item,'uuid')==target_uid)
            self.assertAlmostEqual(float(sx.child(after,'at')[1])-before_x,0.2,places=4)
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'current')

    def test_retain_destination_layout_inherits_value_without_moving_placed_board(self):
        with tempfile.TemporaryDirectory(prefix='fusion-native-link-retain-') as folder:
            base=Path(folder).resolve();target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            imported=model.SourceSpec(source.project,'Unit1',variant='<Default>')
            i.apply_import(i.preview_import(target.project,[imported],True,base/'inserted'))
            _,manifest=l._load(target.project);old=manifest['links'][0]
            target_board=Path(target.project).with_suffix('.kicad_pcb')
            locally_edited=sx.load(target_board)
            placed=next(item for item in sx.children(locally_edited,'footprint')
                        if sx.value(item,'uuid') in old['pcb_item_ids'])
            target_x=float(sx.child(placed,'at')[1])
            sx.child(placed,'at')[1]=str(target_x+0.2)
            target_segment=min([item for item in sx.children(locally_edited,'segment')
                                if sx.value(item,'uuid') in old['pcb_item_ids']],
                               key=lambda item:abs(float(sx.child(item,'start')[1])-target_x))
            sx.child(target_segment,'start')[1]=str(float(sx.child(target_segment,'start')[1])+0.2)
            sx.save(target_board,locally_edited)
            before=sx.load(target_board)
            linked={uid:l._digest(l._normal(item)) for item in sx.children(before)
                    if (uid:=sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id')) in old['pcb_item_ids']
                    and sx.tag(item)!='footprint'}
            source_board=base/'source/board.kicad_pcb';board=sx.load(source_board)
            footprint=sx.children(board,'footprint')[0]
            sx.child(footprint,'at')[1]=str(float(sx.child(footprint,'at')[1])+0.2)
            segment=sx.children(board,'segment')[0]
            sx.child(segment,'start')[1]=str(float(sx.child(segment,'start')[1])+0.2)
            sx.save(source_board,board)
            child=sx.load(base/'source/child.kicad_sch');symbol=sx.children(child,'symbol')[0]
            sx.prop(symbol,'Value')[2]=sx.q('33k')
            symbol.append(sx.loads('(property "MPN" "R33K" (at 20 22 0) (effects (font (size 1.27 1.27)) (hide yes)))'))
            sx.save(base/'source/child.kicad_sch',child)
            hashes=l.fingerprint(base/'source')
            plan=l.preview_update(target.project,[old['id']],base/'updated',acknowledge_major=True,
                                  retain_destination_layout=True)
            self.assertTrue(plan['report']['retain_destination_layout'])
            self.assertEqual(l.fingerprint(base/'source'),hashes)
            i.apply_import(plan)
            after=sx.load(target_board)
            for item in sx.children(after):
                uid=sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id')
                if uid in linked:self.assertEqual(l._digest(l._normal(item)),linked[uid])
            source_uid=sx.value(footprint,'uuid');target_uid=old['pcb_uuid_map'][source_uid]
            old_fp=next(item for item in sx.children(before,'footprint') if sx.value(item,'uuid')==target_uid)
            new_fp=next(item for item in sx.children(after,'footprint') if sx.value(item,'uuid')==target_uid)
            self.assertEqual(sx.child(new_fp,'at'),sx.child(old_fp,'at'))
            self.assertEqual(sx.propval(new_fp,'Value'),'33k')
            self.assertEqual(l.scan_links(target.project)['links'][0]['status'],'current')

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
