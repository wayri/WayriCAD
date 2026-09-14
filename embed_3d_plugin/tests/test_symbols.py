"""Schematic format preservation tests. These do not execute KiCad's parser."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch as mock_patch
from embed_3d_plugin.symbols import *
from embed_3d_plugin.board_package import entry_for_bytes, replace_entries, PayloadReader
from embed_3d_plugin.codec import Codec
from embed_3d_plugin.core import embedded_entries
from embed_3d_plugin.sexpr import semantic


def symbol(key='Device:R', width='1.0'):
    leaf=key.rsplit(':',1)[-1]
    return '''(symbol %s (pin_names (offset 0)) (in_bom yes) (on_board yes)
 (property "Reference" "R" (at 0 1.5 0) (effects (font (size 1.27 1.27))))
 (property "Value" "R" (at 0 -1.5 0) (effects (font (size 1.27 1.27))))
 (property "Footprint" "Resistor_SMD:R_0402_1005Metric" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
 (symbol "%s_0_1" (rectangle (start -%s -1) (end %s 1) (stroke (width 0) (type default)) (fill (type none))))
 (symbol "%s_1_1"
  (pin passive line (at -2.54 0 0) (length 1.27) (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
  (pin passive line (at 2.54 0 180) (length 1.27) (name "~" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27))))))
)''' % (quote(key),leaf,width,width,leaf)


def instance(uid='11111111-1111-4111-8111-111111111111',key='Device:R',override=None,ref='R1',unit=1):
    ov='(lib_name '+quote(override)+')' if override else ''
    return '''(symbol (lib_id %s) %s (at 50.8 50.8 90) (unit %d) (in_bom yes) (on_board yes) (dnp no)
 (uuid %s)
 (property "Reference" %s (at 52.7 49.5 90) (effects (font (size 1.27 1.27))))
 (property "Value" "10k" (at 52.7 52 90) (effects (font (size 1.27 1.27))))
 (property "Footprint" "Resistor_SMD:R_0402_1005Metric" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
 (property "Sim.Device" "R" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
 (pin "1" (uuid "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))
 (pin "2" (uuid "cccccccc-cccc-4ccc-8ccc-cccccccccccc"))
 (instances (project "circuit" (path "/00000000-0000-4000-8000-000000000000" (reference %s) (unit %d))))
)''' % (quote(key),ov,unit,quote(uid),quote(ref),quote(ref),unit)


def child(link):
    return '(sheet (at 100 100) (size 30 20) (uuid "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa") (property "Sheetname" "Child") (property "Sheetfile" '+quote(link)+'))'


def schematic(defs=None, instances=None, extra=''):
    defs=[symbol()] if defs is None else defs
    instances=[instance()] if instances is None else instances
    return '''(kicad_sch (version 20260306) (generator "eeschema") (generator_version "10.0")
 (uuid "00000000-0000-4000-8000-000000000000") (paper "A4")
 (lib_symbols\n%s\n)
 (wire (pts (xy 48.26 50.8) (xy 43.18 50.8)) (stroke (width 0) (type default)) (uuid "dddddddd-dddd-4ddd-8ddd-dddddddddddd"))
 (label "Signal" (at 43.18 50.8 0) (effects (font (size 1.27 1.27))) (uuid "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"))
%s\n%s\n)''' % ('\n'.join(defs),'\n'.join(instances),extra)


class SymbolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'circuit.kicad_sch';self.source.write_text(schematic())
        self.assets=self.root/'assets';self.out=self.root/'external'
    def tearDown(self):self.tmp.cleanup()
    def test_path_alias_retains_root_and_child_output_locations(self):
        actual = self.root.resolve()
        alias = actual/'short-path-alias'
        directory = actual/'sheets';directory.mkdir()
        (directory/'child.kicad_sch').write_text(schematic(),encoding='utf-8')
        self.source.write_text(schematic(extra=child('sheets/child.kicad_sch')),encoding='utf-8')
        resolve = Path.resolve
        def resolve_alias(path, *args, **kwargs):
            try:path = actual/path.relative_to(alias)
            except ValueError:pass
            return resolve(path,*args,**kwargs)
        with mock_patch.object(Path,'resolve',resolve_alias):
            sheets = load_hierarchy(alias/self.source.name)
        self.assertEqual([s.output for s in sheets],['circuit.kicad_sch','sheets/child.kicad_sch'])
        self.assertEqual([s.relative for s in sheets],['circuit.kicad_sch','sheets/child.kicad_sch'])
    def extract(self,**kw):
        plan=extract_symbols(self.source,**kw);plan.publish(self.assets);return plan
    def test_native_cache_extracted_without_changing_source(self):
        before=self.source.read_bytes();p=self.extract()
        self.assertEqual(self.source.read_bytes(),before);self.assertEqual(p.meta['symbol_count'],1)
        lib=p.files['UnbundledSymbols.kicad_sym'].decode();root=parse(lib)
        self.assertEqual(root.head(lib),'kicad_symbol_lib');self.assertEqual(len(root.nodes(lib,'symbol')),1)
        self.assertIn('"R__',lib);self.assertIn('_0_1',lib);self.assertIn('Resistor_SMD:R_0402_1005Metric',lib)
    def test_separate_relink_dry_run_writes_nothing(self):
        self.extract();relink_symbols(self.source,self.assets,self.out)
        self.assertFalse(self.out.exists());self.assertEqual(self.source.read_text(),schematic())
    def test_relink_preserves_geometry_fields_pin_wiring_and_cache(self):
        before=self.source.read_text();self.extract();relink_symbols(self.source,self.assets,self.out,apply=True)
        after=(self.out/self.source.name).read_text();verify_symbol_preservation(before,after)
        self.assertIn('(lib_symbols',after);self.assertIn('(lib_id "UnbundledSymbols:',after)
        self.assertIn('Resistor_SMD:R_0402_1005Metric',after);self.assertIn('"Sim.Device" "R"',after)
        self.assertIn('${KIPRJMOD}/../assets/UnbundledSymbols.kicad_sym',(self.out/'sym-lib-table').read_text())
    def test_custom_lib_name_uses_as_drawn_cache_not_original_library(self):
        old=schematic([symbol('CustomCachedR',width='9')],[instance(override='CustomCachedR')])
        self.source.write_text(old);self.extract();relink_symbols(self.source,self.assets,self.out,apply=True)
        after=(self.out/self.source.name).read_text();verify_symbol_preservation(old,after)
        self.assertNotIn('(lib_name ',after);self.assertIn('(start -9 -1)',after)
    def test_two_instances_same_definition_deduplicated(self):
        self.source.write_text(schematic(instances=[instance(),instance('22222222-2222-4222-8222-222222222222',ref='R2')]))
        self.assertEqual(self.extract().meta['symbol_count'],1)
    def test_unused_cache_optional(self):
        self.source.write_text(schematic([symbol(),symbol('Device:Spare')]))
        self.assertEqual(extract_symbols(self.source).meta['symbol_count'],1)
        self.assertEqual(extract_symbols(self.source,include_unused=True).meta['symbol_count'],2)
    def test_missing_cache_blocks(self):
        self.source.write_text(schematic([]))
        with self.assertRaisesRegex(ValueError,'Missing native symbol cache'):self.extract()
    def test_unflattened_cache_refused(self):
        self.source.write_text(schematic(['(symbol "Device:R" (extends "Other"))']))
        with self.assertRaisesRegex(ValueError,'Unflattened'):self.extract()
    def test_unknown_unit_name_blocks(self):
        self.source.write_text(schematic([symbol().replace('R_0_1','strange_unit')]))
        with self.assertRaisesRegex(ValueError,'unit name'):self.extract()
    def test_multiple_units_renamed_and_retained(self):
        raw=symbol();node=parse(raw)
        raw=patch(raw,[(node.end-1,node.end-1,'(symbol "R_2_1" (circle (center 0 0) (radius 1) (stroke (width 0) (type default)) (fill (type none))))')])
        self.source.write_text(schematic([raw],[instance(),instance('22222222-2222-4222-8222-222222222222',ref='R1',unit=2)]))
        p=self.extract();self.assertIn('_2_1',p.files['UnbundledSymbols.kicad_sym'].decode())
        relink_symbols(self.source,self.assets,self.out,apply=True);verify_symbol_preservation(self.source.read_text(),(self.out/self.source.name).read_text())
    def test_follow_hierarchy_and_reused_child(self):
        c=self.root/'sheets/child.kicad_sch';c.parent.mkdir();c.write_text(schematic())
        self.source.write_text(schematic(extra=child('sheets/child.kicad_sch')+child('sheets/child.kicad_sch')))
        p=self.extract();self.assertEqual(len(p.meta['records']),2)
        relink_symbols(self.source,self.assets,self.out,apply=True)
        self.assertTrue((self.out/'sheets/child.kicad_sch').is_file())
    def test_same_id_different_sheet_geometry_gets_distinct_definitions(self):
        c=self.root/'child.kicad_sch';c.write_text(schematic([symbol(width='7')]))
        self.source.write_text(schematic(extra=child('child.kicad_sch')))
        p=self.extract();self.assertEqual(p.meta['symbol_count'],2)
        self.assertNotEqual(p.meta['records'][0]['mapping']['Device:R'],p.meta['records'][1]['mapping']['Device:R'])
    def test_external_child_is_copied_and_sheet_path_rebased(self):
        sub=self.root/'source';sub.mkdir();self.source=sub/'circuit.kicad_sch'
        c=self.root/'external child.kicad_sch';c.write_text(schematic())
        self.source.write_text(schematic(extra=child('../external child.kicad_sch')))
        self.extract();relink_symbols(self.source,self.assets,self.out,apply=True)
        after=(self.out/'circuit.kicad_sch').read_text()
        self.assertIn('external-sheets/',after);self.assertEqual(len(list((self.out/'external-sheets').glob('*.kicad_sch'))),1)
    def test_hierarchy_cycle_refused(self):
        self.source.write_text(schematic(extra=child(self.source.name)))
        with self.assertRaisesRegex(ValueError,'Cyclic'):self.extract()
    def test_missing_child_refused(self):
        self.source.write_text(schematic(extra=child('absent.kicad_sch')))
        with self.assertRaises(ValueError):self.extract()
    def test_single_sheet_does_not_need_unavailable_child(self):
        self.source.write_text(schematic(extra=child('absent.kicad_sch')))
        p=self.extract(follow=False);self.assertEqual(len(p.meta['records']),1);self.assertTrue(any('Only the selected' in w for w in p.warnings))
    def test_archive_contains_actual_symbol_library_bytes(self):
        before=self.source.read_bytes();report=embed_symbols(self.source,self.out,apply=True)
        self.assertEqual(self.source.read_bytes(),before);self.assertEqual(report['libraries_archived'],1)
        after=(self.out/self.source.name).read_text();pool=embedded_entries(after);reader=PayloadReader()
        self.assertIn(SCH_ARCHIVE,pool);meta=json.loads(reader.read(pool[SCH_ARCHIVE]))
        entry=meta['libraries'][0];data=reader.read(pool[entry['embedded_file']])
        self.assertEqual(sha256(data),entry['sha256']);self.assertEqual(parse(data.decode()).head(data.decode()),'kicad_symbol_lib')
        verify_symbol_preservation(before.decode(),after)
    def test_supplied_libraries_verbatim_not_substituted(self):
        supplied=self.root/'supplied.kicad_sym';data=library_text(['(symbol "User" (extends "Parent"))',symbol('Parent',width='99')]).encode()
        supplied.write_bytes(data);embed_symbols(self.source,self.out,supplied=[supplied],apply=True)
        after=(self.out/self.source.name).read_text();pool=embedded_entries(after);reader=PayloadReader()
        self.assertIn(data,[reader.read(v) for k,v in pool.items() if k.endswith('.kicad_sym')]);self.assertIn('(start -1.0 -1)',after)
    def test_embed_local_links_and_editable_library(self):
        embed_symbols(self.source,self.out,local_links=True,apply=True)
        self.assertTrue((self.out/'EmbeddedSymbols.kicad_sym').is_file())
        after=(self.out/self.source.name).read_text();self.assertIn('(lib_id "EmbeddedSymbols:',after)
        verify_symbol_preservation(self.source.read_text(),after)
    def test_embed_extract_relink_prune_cycle_keeps_cache(self):
        bundle=self.root/'bundle';embed_symbols(self.source,bundle,apply=True)
        bundled=bundle/self.source.name;plan=extract_symbols(bundled);plan.publish(self.assets)
        self.assertTrue(any(k.startswith('archives/') for k in plan.files))
        relink_symbols(bundled,self.assets,self.out,prune=True,apply=True)
        after=(self.out/self.source.name).read_text();self.assertNotIn(SCH_ARCHIVE,embedded_entries(after));self.assertTrue(cache_symbols(after))
    def test_resources_embedded_inside_exported_symbols(self):
        entry=entry_for_bytes('notes.txt',b'actual note',Codec())
        raw=symbol().replace('"R" (at 0 -1.5','"kicad-embed://notes.txt" (at 0 -1.5')
        self.source.write_text(replace_entries(schematic([raw]),{'notes.txt':entry}))
        p=self.extract();lib=p.files['UnbundledSymbols.kicad_sym'].decode();defn=parse(lib).nodes(lib,'symbol')[0].raw(lib)
        self.assertEqual(PayloadReader().read(embedded_entries(defn)['notes.txt']),b'actual note')
    def test_changed_child_invalidates_extraction(self):
        c=self.root/'child.kicad_sch';c.write_text(schematic());self.source.write_text(schematic(extra=child(c.name)))
        self.extract();c.write_text(c.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'Source changed'):relink_symbols(self.source,self.assets,self.out,apply=True)
    def test_later_asset_edits_block_relink(self):
        self.extract();file=self.assets/'UnbundledSymbols.kicad_sym';file.write_text(file.read_text()+'\n')
        with self.assertRaises(ValueError):relink_symbols(self.source,self.assets,self.out,apply=True)
    def test_old_schematic_archive_requires_save_in_10(self):
        self.source.write_text(schematic().replace('20260306','20231120'))
        with self.assertRaisesRegex(ValueError,'save this schematic'):embed_symbols(self.source,self.out,apply=True)
    def test_snapshots_of_all_sheets_and_table(self):
        (self.root/'sym-lib-table').write_text('(sym_lib_table)')
        self.extract();relink_symbols(self.source,self.assets,self.out,apply=True)
        self.assertEqual((self.out/'WayriCAD Embed3D-originals'/self.source.name).read_bytes(),self.source.read_bytes())
        self.assertEqual((self.out/'WayriCAD Embed3D-originals/sym-lib-table').read_text(),'(sym_lib_table)')
    def test_unrelated_native_attachments_survive_prune(self):
        entry=entry_for_bytes('license.txt',b'keep me',Codec());self.source.write_text(replace_entries(self.source.read_text(),{'license.txt':entry}))
        self.extract();relink_symbols(self.source,self.assets,self.out,prune=True,apply=True)
        self.assertIn('license.txt',embedded_entries((self.out/self.source.name).read_text()))
    def test_copy_native_reject_stops_publication(self):
        self.extract()
        def reject(_):raise ValueError('native rejected')
        with self.assertRaises(ValueError):relink_symbols(self.source,self.assets,self.out,apply=True,validate=reject)
        self.assertFalse(self.out.exists())
    def test_absolute_symbol_library_path(self):
        self.extract();relink_symbols(self.source,self.assets,self.out,path_mode='absolute',apply=True)
        self.assertIn((self.assets/'UnbundledSymbols.kicad_sym').as_posix(),(self.out/'sym-lib-table').read_text())
    def test_saved_project_sheet_variables(self):
        c=self.root/'child.kicad_sch';c.write_text(schematic())
        (self.root/'circuit.kicad_pro').write_text(json.dumps({'text_variables':{'CHILD':'child.kicad_sch'}}))
        self.source.write_text(schematic(extra=child('${CHILD}')))
        self.assertEqual(len(extract_symbols(self.source).meta['records']),2)
    def test_newer_unreviewed_schematic_format_refused(self):
        self.source.write_text(schematic().replace('20260306','20270101'))
        with self.assertRaisesRegex(ValueError,'newer than'):self.extract()
    def test_preview_input_fingerprints_include_supplied_libraries(self):
        supplied=self.root/'extra.kicad_sym';supplied.write_text(library_text([symbol('Extra')]))
        report=embed_symbols(self.source,self.out,supplied=[supplied])
        self.assertEqual(report['input_sha256'][str(supplied)],sha256(supplied.read_bytes()))
