"""Project-library publication, portability and rollback contracts."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from embed_3d_plugin import project_local as local
from embed_3d_plugin import board_package as bp
from embed_3d_plugin import symbols as sy
from embed_3d_plugin.sexpr import parse
from embed_3d_plugin.codec import sha256
from test_board_package import board, placed, rename_snapshot, MODEL_SETTINGS
from test_symbols import schematic, instance


class ProjectLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.pcb = self.root/'circuit.kicad_pcb'; self.sch = self.root/'circuit.kicad_sch'
        self.uid = '11111111-1111-4111-8111-111111111111'
        self.model = self.root/'resistor.step'; self.model.write_bytes(b'opaque test model')
        self.pcb.write_text(board([placed(self.uid,'R1','Lib:Part',self.model)]))
        self.sch.write_text(schematic(instances=[instance(self.uid,ref='R1')]).replace('Resistor_SMD:R_0402_1005Metric','Lib:Part'))
    def tearDown(self): self.tmp.cleanup()
    def prepare(self, **kwargs):
        text = self.pcb.read_text(); fp = parse(text).nodes(text,'footprint')[0]
        norm = {self.uid: ('Part', rename_snapshot(fp.raw(text),'Part'))}
        return local.prepare(self.pcb,self.sch,normalized=norm,normalized_hash=sha256(self.pcb.read_bytes()),**kwargs)
    def test_preview_then_portable_project_links_and_backup(self):
        before = self.pcb.read_bytes(); plan = self.prepare()
        self.assertFalse((self.root/'local').exists())
        report = plan.apply()
        self.assertEqual((Path(report['backup'])/self.pcb.name).read_bytes(),before)
        self.assertEqual(plan.counts['schematic_assignments'],1)
        self.assertIn('${KIPRJMOD}/local/models/',self.pcb.read_text())
        self.assertIn('WayriCAD_Project:Part',self.sch.read_text())
        self.assertEqual(self.pcb.read_text().count(MODEL_SETTINGS),1)
        self.assertTrue((self.root/'local/symbols/WayriCAD_Project.kicad_sym').is_file())
        self.assertTrue(report['models_complete'])
        self.assertEqual(bp._board_fingerprint(before.decode()),bp._board_fingerprint(self.pcb.read_text()))
    def test_custom_folder_is_persisted(self):
        self.prepare(folder='libraries/assets').apply()
        self.assertEqual(local.settings(self.root)['folder'],'libraries/assets')
        self.assertIn('${KIPRJMOD}/libraries/assets',self.pcb.read_text())
    def test_local_default_footprints_in_exported_library_and_native_cache(self):
        plan = self.prepare()
        library = plan.files['local/symbols/WayriCAD_Project.kicad_sym'].decode('utf-8')
        definition = parse(library).nodes(library, 'symbol')[0]
        self.assertEqual(sy.property_value(definition, library, 'Footprint').value(library), 'WayriCAD_Project:Part')
        output = plan.files[self.sch.name].decode('utf-8')
        for raw in sy.cache_symbols(output).values():
            self.assertEqual(sy.property_value(parse(raw), raw, 'Footprint').value(raw), 'WayriCAD_Project:Part')
        plan.apply()
        repeated = self.prepare()
        self.assertEqual(repeated.files['local/symbols/WayriCAD_Project.kicad_sym'],
                         plan.files['local/symbols/WayriCAD_Project.kicad_sym'])
    def test_unavailable_mismatched_default_is_never_guessed(self):
        text = self.sch.read_text()
        root = parse(text); block = root.one(text, 'lib_symbols')
        replacement = block.raw(text).replace('Lib:Part', 'Unavailable_WayriCAD:Generic')
        self.sch.write_text(text[:block.start]+replacement+text[block.end:])
        with self.assertRaisesRegex(ValueError, 'default library is unavailable'):
            self.prepare()
        plan = self.prepare(allow_missing=True)
        self.assertFalse(plan.summary()['assets_complete'])
        self.assertTrue(any(w.startswith('Unresolved symbol footprint default retained:') for w in plan.warnings))
        self.assertIn('Unavailable_WayriCAD:Generic', plan.files['local/symbols/WayriCAD_Project.kicad_sym'].decode('utf-8'))
    def test_unused_native_cache_default_is_localized_too(self):
        from test_symbols import symbol
        extra = symbol('Device:Unused').replace('Resistor_SMD:R_0402_1005Metric', 'Lib:Part')
        text = self.sch.read_text()
        block = parse(text).one(text, 'lib_symbols')
        self.sch.write_text(text[:block.end-1] + extra + text[block.end-1:])
        plan = self.prepare()
        output = plan.files[self.sch.name].decode('utf-8')
        unused = sy.cache_symbols(output)['Device:Unused']
        self.assertEqual(sy.property_value(parse(unused), unused, 'Footprint').value(unused), 'WayriCAD_Project:Part')
    def test_geometry_fingerprint_retains_tracks_zones_and_footprint_coordinates(self):
        source = '(kicad_pcb (footprint "L:A" (at 1 2) (model "old" (offset (xyz 0 0 0)))) (zone (polygon (pts (xy 1 2) (xy 3 4)))))'
        linked = source.replace('"L:A"','"Local:A"').replace('"old"','"new"')
        self.assertEqual(local._relink_fingerprint(source), local._relink_fingerprint(linked))
        for changed in [linked.replace('(at 1 2)', '(at 1 3)'), linked.replace('(xy 3 4)', '(xy 4 4)'),
                        linked.replace('(xyz 0 0 0)', '(xyz 1 0 0)')]:
            self.assertNotEqual(local._relink_fingerprint(source), local._relink_fingerprint(changed))
    def test_resolution_failures_are_cached_only_within_one_plan(self):
        resolver = local.ProjectResolver(self.root)
        real = local.Resolver.resolve
        calls = []
        def counted(instance, reference, context=None):
            calls.append(reference)
            return real(instance, reference, context)
        with patch.object(local.Resolver, 'resolve', counted):
            for _ in range(3):
                with self.assertRaises(ValueError): resolver.resolve('missing.step')
            self.assertEqual(len(calls),1)
            (self.root/'missing.step').write_bytes(b'new exact model')
            resolver.begin_plan()
            self.assertEqual(resolver.resolve('missing.step'), (self.root/'missing.step').resolve())
            self.assertEqual(len(calls),2)
    def test_table_edit_during_prepare_is_not_authorized_for_overwrite(self):
        real=local.extract_pcb
        def extract(*args,**kwargs):
            result=real(*args,**kwargs)
            (self.root/'fp-lib-table').write_text('(fp_lib_table)\n; concurrent edit')
            return result
        with patch.object(local,'extract_pcb',side_effect=extract):
            with self.assertRaisesRegex(ValueError,'sidecar changed during preview'):self.prepare()
        self.assertIn('concurrent edit',(self.root/'fp-lib-table').read_text())
    def test_different_project_roots_are_rejected(self):
        foreign=self.root/'other';foreign.mkdir();target=foreign/self.sch.name
        shutil.copy2(self.sch,target)
        with self.assertRaisesRegex(ValueError,'same project folder'):
            local.prepare(self.pcb,target)
    def test_missing_model_blocks_unless_explicit_partial(self):
        self.model.unlink()
        with self.assertRaises(ValueError): self.prepare()
        plan = self.prepare(allow_missing=True)
        self.assertFalse(plan.summary()['models_complete'])
        plan.apply()
        self.assertIn(str(self.model).replace('\\','\\\\'),self.pcb.read_text())
    def test_stale_model_or_design_cannot_overwrite(self):
        plan = self.prepare(); self.model.write_bytes(b'new model')
        with self.assertRaisesRegex(ValueError,'Input changed'): plan.apply()
        self.assertFalse((self.root/'local').exists())
    def test_validation_failure_has_no_source_side_effect(self):
        before = self.pcb.read_bytes(); plan = self.prepare()
        def fail(_): raise ValueError('Native parser rejected')
        with self.assertRaisesRegex(ValueError,'Native parser'): plan.apply(validate=fail)
        self.assertEqual(before,self.pcb.read_bytes()); self.assertFalse((self.root/'local').exists())
    def test_publication_failure_rolls_back(self):
        before = {p.name:p.read_bytes() for p in (self.pcb,self.sch)}
        plan = self.prepare(); real_replace = local.os.replace; calls = []
        def fail(source,target):
            calls.append(str(target))
            if Path(target).name == 'sym-lib-table': raise OSError('injected publication failure')
            return real_replace(source,target)
        with patch.object(local.os,'replace',side_effect=fail):
            with self.assertRaisesRegex(OSError,'injected'): plan.apply()
        for name,data in before.items(): self.assertEqual((self.root/name).read_bytes(),data)
        self.assertFalse((self.root/'fp-lib-table').exists())
    def test_repeated_localization_stable_paths(self):
        self.prepare().apply(); plan = self.prepare()
        self.assertEqual(plan.counts['models'],1)
        self.assertEqual(len(list((self.root/'local/models').glob('*'))),1)
        plan.apply()
        self.assertEqual(len(list((self.root/'local/models').glob('*'))),1)
        self.assertEqual(len(sy.cache_symbols(self.sch.read_text())),1)
    def test_reject_outside_project_folder(self):
        for value in ('../outside','/outside','C:/outside','.hidden','local/../../outside'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): self.prepare(folder=value)
    def test_edited_managed_asset_is_preserved(self):
        self.prepare().apply()
        library = next((self.root/'local').rglob('*.kicad_mod'))
        library.write_text(library.read_text()+'\n; user edit\n')
        with self.assertRaisesRegex(ValueError,'unchanged managed'): self.prepare()
    def test_restore_preserves_subsequent_user_edits(self):
        before = self.pcb.read_bytes(); report = self.prepare().apply()
        localized = self.pcb.read_bytes(); self.pcb.write_bytes(localized+b'\n')
        with self.assertRaisesRegex(ValueError,'changed since'): local.restore(report['backup'])
        self.pcb.write_bytes(localized)
        local.restore(report['backup'])
        self.assertEqual(self.pcb.read_bytes(),before)
    def test_schematic_only_copies_assigned_footprint_and_model(self):
        library = self.root/'source.pretty'; library.mkdir()
        raw = placed(self.uid,'R1','Lib:Part',self.model)
        (library/'Part.kicad_mod').write_text(rename_snapshot(raw,'Part'))
        self.sch.write_text(self.sch.read_text().replace('Resistor_SMD:R_0402_1005Metric','Lib:Part'))
        (self.root/'fp-lib-table').write_text('(fp_lib_table (lib (name "Lib") (type "KiCad") (uri "${KIPRJMOD}/source.pretty") (options "") (descr "")))')
        plan = local.prepare(schematic=self.sch); plan.apply()
        self.assertEqual(plan.counts['footprints'],1); self.assertEqual(plan.counts['models'],1)
        self.assertIn('WayriCAD_Project:L_Lib_Part',self.sch.read_text())
        repeat = local.prepare(schematic=self.sch); repeat.apply()
        self.assertEqual(len(list((self.root/'local').rglob('*.kicad_mod'))),1)
