import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch as mock_patch
from embed_3d_plugin.codec import Codec, sha256
from embed_3d_plugin.core import Planner, PREFIX, embedded_entries
from embed_3d_plugin.paths import Resolver
from embed_3d_plugin.sexpr import parse, patch, quote, semantic
from embed_3d_plugin import board_package as bp

MODEL_SETTINGS = ' (offset (xyz -1.200 2.50 0.001)) (scale (xyz 0.5 1 3)) (rotate (xyz 90 13 -37)) (opacity 0.65) (hide yes)'


def placed(uid, ref, name, path=None, pad_x='2.1'):
    models = '(model '+quote(str(path))+MODEL_SETTINGS+')' if path else ''
    return '(footprint '+quote(name)+' (layer "B.Cu") (uuid '+quote(uid)+') (at 11.25 39.3 127.8)\n'+\
           '(property "Reference" '+quote(ref)+' (at 2 3) (layer "B.SilkS"))\n'+\
           '(pad "1" smd rect (at '+pad_x+' 5.4) (size 1 2) (layers "B.Cu" "B.Mask") (net 1 "SIG"))\n'+\
           '(attr smd) (custom_field "preserve me")\n'+models+'\n)'


def board(footprints, extra=''):
    return '(kicad_pcb (version 20260101) (generator "pcbnew")\n(general (thickness 1.6))\n'+\
           '(layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (setup (pad_to_mask_clearance 0)) (net 1 "SIG")\n'+\
           '\n'.join(footprints)+'\n(segment (start 1 2)(end 3 4)(width 0.25)(layer "F.Cu")(net 1))\n'+extra+'\n)'


def rename_snapshot(text, name):
    # Synthetic text fixture, NOT a claim of native coordinate normalization.
    arg = parse(text).arg()
    return patch(text, [(arg.start, arg.end, quote(name))])


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.model = self.root/'part.step'; self.model.write_bytes(b'opaque STEP payload for pure parser tests')
        self.planner = Planner(Resolver(self.root))
        self.uid1 = '11111111-1111-4111-8111-111111111111'
        self.uid2 = '22222222-2222-4222-8222-222222222222'
    def tearDown(self): self.tmp.cleanup()

    def fixture(self, second=False, zero=False, supplied=False, extra=''):
        texts = [placed(self.uid1, 'R1', 'Resistor_SMD:R_0402', None if zero else self.model)]
        if second: texts.append(placed(self.uid2, 'R2', 'Resistor_SMD:R_0402', self.model, pad_x='9.8'))
        plans = [self.planner.scan(t, 'R'+str(i+1), self.root) for i, t in enumerate(texts)]
        defs = [bp.Definition('d'+str(i), 'Board_'+str(i), rename_snapshot(p.build(), 'Board_'+str(i)), 'Resistor_SMD:R_0402') for i, p in enumerate(plans)]
        instances = [bp.Instance(bp.uuid_of(t), p, d.key, d.key) for t,p,d in zip(texts,plans,defs)]
        if supplied:
            imported = self.planner.scan(placed('supplied', 'REF**', 'Resistor_SMD:R_0402', self.model, pad_x='8.8'), 'supplied')
            defs.append(bp.Definition('user', 'User_0402', rename_snapshot(imported.build(), 'User_0402'), 'Resistor_SMD:R_0402', 'supplied definition'))
            instances[0].definition_key = 'user'
        text = board(texts, extra)
        return text, instances, defs

    def package(self, **kwargs):
        text, instances, defs = self.fixture(**kwargs)
        return bp.compose(text, instances, defs, 'WayriCAD_Embed3D_Board')

    def test_actual_model_and_footprint_bytes_inside_pcb(self):
        p = self.package(); entries = embedded_entries(p.board_text)
        self.assertIn(bp.MANIFEST, entries)
        snapshot = p.manifest['definitions'][0]['embedded_file']
        self.assertIn('(type other)', entries[snapshot].raw)
        models = [e for e in entries.values() if '(type model)' in e.raw]
        self.assertEqual(len(models), 1)
        self.assertEqual(Codec().decode(models[0].encoded), self.model.read_bytes())
        self.assertIn('footprint', Codec().decode(entries[snapshot].encoded).decode())

    def test_models_moved_to_board_pool_and_relinked(self):
        p = self.package()
        for fp in parse(p.board_text).nodes(p.board_text, 'footprint'):
            text = fp.raw(p.board_text)
            self.assertFalse(embedded_entries(text))
            self.assertTrue(all(ref.startswith(PREFIX) for ref in bp.model_refs(text)))
            self.assertTrue(parse(text).arg().value(text).startswith('WayriCAD_Embed3D_Board:'))

    def test_exact_model_suffix_and_board_geometry_preserved(self):
        old, items, defs = self.fixture(second=True)
        p = bp.compose(old, items, defs, 'WayriCAD_Embed3D_Board')
        self.assertEqual(bp._board_fingerprint(old), bp._board_fingerprint(p.board_text))
        self.assertEqual(p.board_text.count(MODEL_SETTINGS), 2)
        self.assertIn('(at 11.25 39.3 127.8)', p.board_text)
        self.assertIn('(net 1 "SIG")', p.board_text)
        self.assertIn('(at 9.8 5.4)', p.board_text)
        self.assertIn('(segment (start 1 2)(end 3 4)(width 0.25)(layer "F.Cu")(net 1))', p.board_text)

    def test_repeat_models_deduplicated(self):
        p = self.package(second=True)
        models = [e for e in embedded_entries(p.board_text).values() if '(type model)' in e.raw]
        self.assertEqual(len(models), 1)
        self.assertEqual(len(p.library_files), 2)  # distinct as-placed definitions retained

    def test_identical_bytes_different_source_basenames_deduplicated(self):
        old, items, defs = self.fixture(second=True)
        other = self.root/'another.step'; other.write_bytes(self.model.read_bytes())
        second = placed(self.uid2, 'R2', 'Lab:Other', other)
        items[1].plan = self.planner.scan(second)
        defs[1].text = rename_snapshot(items[1].plan.build(), defs[1].name)
        old = board([placed(self.uid1, 'R1', 'Resistor_SMD:R_0402', self.model), second])
        p = bp.compose(old, items, defs, 'WayriCAD_Embed3D_Board')
        self.assertEqual(len([e for e in embedded_entries(p.board_text).values() if '(type model)' in e.raw]), 1)

    def test_zero_model_footprint_included(self):
        p = self.package(zero=True)
        self.assertEqual(len(p.library_files), 1)
        self.assertEqual(p.manifest['definitions'][0]['models'], [])
        self.assertEqual(bp.recover(p.board_text).library_files, p.library_files)

    def test_user_supplied_relink_does_not_replace_board_geometry(self):
        p = self.package(supplied=True)
        self.assertIn('(footprint "WayriCAD_Embed3D_Board:User_0402"', p.board_text)
        self.assertIn('(at 2.1 5.4)', p.board_text)
        self.assertIn('(at 8.8 5.4)', p.library_files['User_0402.kicad_mod'].decode())
        self.assertTrue(p.manifest['instances'][0]['used_supplied_definition'])
        self.assertIn('Board_0.kicad_mod', p.library_files) # as-placed recovery snapshot still present

    def test_rebuild_from_pcb_alone_without_models(self):
        p = self.package(second=True)
        path = self.root/'board.kicad_pcb'; path.write_text(p.board_text)
        self.model.unlink()
        result = bp.rebuild_library(path, apply=True)
        self.assertTrue(result['applied'])
        for name, data in p.library_files.items():
            # Saving the fixture with write_text may convert newlines on Windows.
            self.assertEqual((Path(result['library'])/name).read_bytes().replace(b'\r\n',b'\n'), data.replace(b'\r\n',b'\n'))
        self.assertIn('${KIPRJMOD}/WayriCAD_Embed3D_Board.pretty', (self.root/'fp-lib-table').read_text())

    def test_library_footprints_hydrated_standalone(self):
        p = self.package()
        for raw in p.library_files.values():
            text = raw.decode(); entries = embedded_entries(text)
            for ref in bp.model_refs(text):
                self.assertEqual(Codec().decode(entries[ref[len(PREFIX):]].encoded), self.model.read_bytes())

    def test_missing_and_unchecked_models_block_composition(self):
        text, items, defs = self.fixture(); items[0].plan.rows[0].checked = False
        with self.assertRaises(ValueError): bp.compose(text, items, defs, 'Lib')
        text, items, defs = self.fixture(); items[0].plan.rows[0].status = 'Missing payload'
        with self.assertRaises(ValueError): bp.compose(text, items, defs, 'Lib')

    def test_changed_model_transforms_block_composition(self):
        text, items, defs = self.fixture()
        text = text.replace('(rotate (xyz 90 13 -37))', '(rotate (xyz 90 13 -38))')
        with self.assertRaisesRegex(ValueError, 'changed since preview'): bp.compose(text, items, defs, 'Lib')

    def test_missing_duplicate_or_extra_instance_blocked(self):
        text, items, defs = self.fixture(second=True)
        with self.assertRaises(ValueError): bp.compose(text, items[:1], defs, 'Lib')
        with self.assertRaises(ValueError): bp.compose(text, [items[0],items[0]], defs, 'Lib')

    def test_unknown_definition_blocked(self):
        text, items, defs = self.fixture(); items[0].definition_key = 'absent'
        with self.assertRaises(ValueError): bp.compose(text, items, defs, 'Lib')

    def test_duplicate_names_case_insensitive_blocked(self):
        text, items, defs = self.fixture(second=True); defs[1].name = defs[0].name.upper()
        with self.assertRaises(ValueError): bp.compose(text, items, defs, 'Lib')

    def test_existing_unrelated_attachment_preserved(self):
        entry = bp.entry_for_bytes('notes.txt', b'Important original attachment', Codec())
        p = self.package(extra='(embedded_files '+entry.raw+')')
        self.assertEqual(Codec().decode(embedded_entries(p.board_text)['notes.txt'].encoded), b'Important original attachment')

    def test_collision_with_existing_content_addressed_model_blocked(self):
        name = 'model__'+sha256(self.model.read_bytes())+'.step'
        bad = bp.entry_for_bytes(name, b'wrong', Codec(), 'model')
        with self.assertRaisesRegex(ValueError, 'collision'): self.package(extra='(embedded_files '+bad.raw+')')

    def test_manifest_name_not_hijacked(self):
        existing = bp.entry_for_bytes(bp.MANIFEST, b'{"format":"someone-elses-archive"}', Codec())
        with self.assertRaisesRegex(ValueError, 'different attachment'): self.package(extra='(embedded_files '+existing.raw+')')

    def test_publish_new_copy_and_native_validation_called(self):
        p = self.package(); before = self.model.read_bytes(); calls = []
        def validate(board_path, library):
            calls.append((board_path.name, len(list(library.glob('*.kicad_mod')))))
            self.assertEqual(bp.recover(board_path.read_text()).library_files, p.library_files)
        path = bp.write_package(p, self.root/'new', 'pcb.kicad_pcb', {'pcb.kicad_pro': b'{}'}, validate)
        self.assertTrue(path.is_file()); self.assertEqual(calls, [('pcb.kicad_pcb', 1)])
        self.assertEqual(self.model.read_bytes(), before)
        self.assertEqual((path.parent/'pcb.kicad_pro').read_bytes(), b'{}')

    def test_existing_output_never_overwritten(self):
        dest = self.root/'existing'; dest.mkdir(); (dest/'user.txt').write_text('keep')
        with self.assertRaises(ValueError): bp.write_package(self.package(), dest, 'pcb.kicad_pcb')
        self.assertEqual((dest/'user.txt').read_text(), 'keep')

    def test_failed_native_validation_does_not_publish(self):
        def fail(*_): raise RuntimeError('native rejected')
        with self.assertRaises(RuntimeError): bp.write_package(self.package(), self.root/'new', 'pcb.kicad_pcb', validate=fail)
        self.assertFalse((self.root/'new').exists())
        self.assertFalse(list(self.root.glob('.embed_3d_plugin-package-*')))

    def test_unexpected_sidecar_rejected(self):
        with self.assertRaises(ValueError): bp.write_package(self.package(), self.root/'new', 'pcb.kicad_pcb', {'../evil': b'x'})

    def test_rebuild_dry_run_makes_no_changes(self):
        p = self.package(); path = self.root/'board.kicad_pcb'; path.write_text(p.board_text)
        before = set(self.root.iterdir()); result = bp.rebuild_library(path)
        self.assertFalse(result['applied']); self.assertEqual(before, set(self.root.iterdir()))

    def test_rebuild_idempotent_and_recreates_missing_file(self):
        p = self.package(second=True); path = self.root/'board.kicad_pcb'; path.write_text(p.board_text)
        first = bp.rebuild_library(path, apply=True)
        second = bp.rebuild_library(path, apply=True); self.assertTrue(second['unchanged'])
        target = Path(first['library'])/next(iter(p.library_files)); target.unlink()
        third = bp.rebuild_library(path, apply=True); self.assertEqual(third['new_files'], 1)
        self.assertTrue(target.is_file())

    def test_edited_local_library_blocks_without_partial_writes(self):
        p = self.package(second=True); path = self.root/'board.kicad_pcb'; path.write_text(p.board_text)
        lib = self.root/(p.library_name+'.pretty'); lib.mkdir()
        edited = lib/next(iter(p.library_files)); edited.write_text('user edits')
        with self.assertRaisesRegex(ValueError, 'later/different edits'): bp.rebuild_library(path, apply=True)
        self.assertEqual(edited.read_text(), 'user edits'); self.assertEqual(len(list(lib.iterdir())), 1)
        self.assertFalse((self.root/'fp-lib-table').exists())

    def test_preserve_library_table_and_collision(self):
        old = '(fp_lib_table\n; keep this comment\n(lib (name "GlobalLocal") (type "KiCad") (uri "${KIPRJMOD}/mine.pretty")))'
        result = bp.library_table('WayriCAD_Embed3D_Board', old)
        self.assertIn('; keep this comment', result); self.assertIn('GlobalLocal', result)
        self.assertEqual(bp.library_table('WayriCAD_Embed3D_Board', result), result)
        bad = result.replace('${KIPRJMOD}/WayriCAD_Embed3D_Board.pretty', 'C:/Other.pretty')
        with self.assertRaises(ValueError): bp.library_table('WayriCAD_Embed3D_Board', bad)

    def test_rebuild_rollback_when_table_write_fails(self):
        p = self.package(); path = self.root/'board.kicad_pcb'; path.write_text(p.board_text)
        original = bp.atomic_write
        def fail_table(target, data, *args, **kwargs):
            if Path(target).name == 'fp-lib-table': raise OSError('simulated write failure')
            return original(target, data, *args, **kwargs)
        with mock_patch.object(bp, 'atomic_write', side_effect=fail_table):
            with self.assertRaises(OSError): bp.rebuild_library(path, apply=True)
        self.assertFalse((self.root/(p.library_name+'.pretty')).exists())
        self.assertFalse((self.root/'fp-lib-table').exists())

    def test_path_traversal_and_reserved_names_blocked(self):
        for name in ('../evil', 'C:\\evil', '/tmp/x', '.hidden', 'CON', 'nul.txt', 'X.', '', 'LPT1'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError): bp.safe_name(name)

    def test_symlink_output_and_rebuild_blocked(self):
        outside = self.root/'outside'; outside.mkdir()
        link = self.root/'link'
        try: link.symlink_to(outside, target_is_directory=True)
        except OSError: self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError): bp.write_package(self.package(), link/'new', 'p.kicad_pcb')
        p = self.package(); path = self.root/'board.kicad_pcb'; path.write_text(p.board_text)
        (self.root/(p.library_name+'.pretty')).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): bp.rebuild_library(path, apply=True)
        self.assertEqual(list(outside.iterdir()), [])

    def alter_manifest(self, package, change):
        pool = embedded_entries(package.board_text); meta = json.loads(Codec().decode(pool[bp.MANIFEST].encoded))
        change(meta)
        pool[bp.MANIFEST] = bp.entry_for_bytes(bp.MANIFEST, json.dumps(meta).encode(), Codec())
        return bp.replace_entries(package.board_text, pool)

    def test_malicious_manifest_cannot_write_outside_library(self):
        text = self.alter_manifest(self.package(), lambda m: m['definitions'][0].update(name='../escape'))
        with self.assertRaises(ValueError): bp.recover(text)

    def test_missing_snapshot_detected(self):
        p = self.package(); pool = embedded_entries(p.board_text)
        del pool[p.manifest['definitions'][0]['embedded_file']]
        with self.assertRaisesRegex(ValueError, 'Missing footprint snapshot'): bp.recover(bp.replace_entries(p.board_text, pool))

    def test_corrupted_model_or_snapshot_hash_detected(self):
        p = self.package()
        text = self.alter_manifest(p, lambda m: m['definitions'][0].update(sha256='0'*64))
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): bp.recover(text)
        pool = embedded_entries(p.board_text)
        modelname = next(name for name in pool if name.startswith('model__'))
        pool[modelname] = bp.entry_for_bytes(modelname, b'corrupted bytes', Codec(), 'model')
        with self.assertRaisesRegex(ValueError, 'corrupt model'): bp.recover(bp.replace_entries(p.board_text, pool))

    def test_unknown_board_without_archive(self):
        with self.assertRaisesRegex(ValueError, 'no WayriCAD Embed3D'): bp.recover(board([]))

    def test_sha256_checksum_checked_for_existing_payload(self):
        entry = bp.entry_for_bytes('bad.step', b'data', Codec(), 'model'); entry.checksum = '0'*64
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'): bp.PayloadReader().read(entry)

    def test_budget_enforced(self):
        entry = bp.entry_for_bytes('model.step', b'123456789', Codec(), 'model')
        with mock_patch.object(bp, 'MAX_JOB_BYTES', 4):
            with self.assertRaisesRegex(ValueError, 'budget'): bp.PayloadReader().read(entry)

    def test_exclusive_publication_never_overwrites_or_leaves_partial_target(self):
        path = self.root/'output.txt'; path.write_bytes(b'user data')
        with self.assertRaises(FileExistsError): bp._publish_new_file(path, b'new data')
        self.assertEqual(path.read_bytes(), b'user data')
        self.assertFalse(list(self.root.glob('.embed_3d_plugin-new-*')))
        missing = self.root/'new.txt'
        with mock_patch.object(bp.os, 'fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): bp._publish_new_file(missing, b'new data')
        self.assertFalse(missing.exists())
        self.assertFalse(list(self.root.glob('.embed_3d_plugin-new-*')))

    def test_supplied_definitions_can_be_archived_in_empty_board(self):
        _, _, definitions = self.fixture()
        p = bp.compose(board([]), [], definitions, 'Supplied')
        self.assertEqual(len(p.library_files), 1)
        self.assertEqual(p.manifest['instances'], [])

    def test_repackage_existing_archive_replaces_only_owned_manifest(self):
        first = self.package()
        pool = embedded_entries(first.board_text)
        fp = parse(first.board_text).nodes(first.board_text, 'footprint')[0].raw(first.board_text)
        plan = self.planner.scan(fp, 'R1', pool=pool)
        definition = bp.Definition('second', 'Second', rename_snapshot(plan.build(), 'Second'), 'WayriCAD_Embed3D_Board:Board_0')
        second = bp.compose(first.board_text, [bp.Instance(self.uid1, plan, 'second', 'second')], [definition], 'Second_Lib')
        self.assertEqual(bp.recover(second.board_text).library_name, 'Second_Lib')
        self.assertIn(first.manifest['definitions'][0]['embedded_file'], embedded_entries(second.board_text))

    def test_cli_inspect_dryrun_and_apply_rebuild(self):
        from embed_3d_plugin.__main__ import main
        import io
        from contextlib import redirect_stdout
        p = self.package(); path = self.root/'board.kicad_pcb'; path.write_text(p.board_text)
        stream = io.StringIO()
        with redirect_stdout(stream): self.assertEqual(main(['inspect-board', str(path), '--json']), 0)
        self.assertEqual(json.loads(stream.getvalue())['format'], bp.FORMAT)
        with redirect_stdout(io.StringIO()): self.assertEqual(main(['rebuild-library', str(path)]), 0)
        self.assertFalse((self.root/'fp-lib-table').exists())
        with redirect_stdout(io.StringIO()): self.assertEqual(main(['rebuild-library', str(path), '--apply']), 0)
        self.assertTrue((self.root/'fp-lib-table').exists())

    def test_cli_rejects_missing_archive(self):
        from embed_3d_plugin.__main__ import main
        import io
        from contextlib import redirect_stderr
        path = self.root/'board.kicad_pcb'; path.write_text(board([]))
        with redirect_stderr(io.StringIO()): self.assertEqual(main(['inspect-board', str(path)]), 2)
