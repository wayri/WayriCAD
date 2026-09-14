import base64
import gzip
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch as mock_patch

from embed_3d_plugin.codec import Codec, CodecError, raw_frame, read_raw_frame, sha256
from embed_3d_plugin.core import Planner, PREFIX, Embedded, embedded_entries, make_entry, verify_sources
from embed_3d_plugin.paths import Resolver, ResolutionError
from embed_3d_plugin.sexpr import parse, quote, semantic, patch, FormatError
from embed_3d_plugin import storage

WRL = b'''#VRML V2.0 utf8
Shape { appearance Appearance { material Material { diffuseColor 0.2 0.6 0.9 } }
geometry Box { size 1 2 3 } }
'''
SETTINGS = '\n  (offset (xyz -1.23000 0.000000 4.567890))\n  (scale (xyz 0.125 2.50 0.333333))\n  (rotate (xyz -90.0 15.25 360))\n  (opacity 0.55) (hide yes)'


def footprint(refs, settings=SETTINGS, extra='', newline='\n'):
    models = '\n'.join('(model '+quote(ref)+settings+')' for ref in refs)
    text = '''(footprint "Lab:Complex_µ" (version 20241229) (generator pcbnew)
 (layer "F.Cu") (at 10 20 37.5)
 (uuid "12345678-1234-1234-1234-123456789abc")
 (property "Reference" "U1" (at 0 -2 13) (layer "F.SilkS"))
 (pad "1" smd roundrect (at 1 2) (size 1.2 0.7) (layers "F.Cu" "F.Mask") (net "USB D+"))
 (custom_future_property "must remain exactly here")
 ; comment: preserve formatting and unknown fields
 %s
 %s
)
''' % (models, extra)
    return text.replace('\n', newline)


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.model = self.root/'model.wrl'
        self.model.write_bytes(WRL)
        self.resolver = Resolver(self.root, {'ROOT': str(self.root)})
        self.planner = Planner(self.resolver)

    def tearDown(self):
        self.temp.cleanup()

    def scan(self, refs=None, **kwargs):
        return self.planner.scan(footprint(refs or [str(self.model)], **kwargs), 'Demo', self.root)

    def file_plan(self, name='fp.kicad_mod'):
        plan = self.scan()
        plan.source_path = self.root/name
        plan.source_path.write_bytes(plan.original.encode('utf-8'))
        return plan


class CodecTests(unittest.TestCase):
    def test_native_roundtrips(self):
        codec = Codec()
        for size in (0, 1, 255, 256, 65535, 131072, 131073, 500000):
            with self.subTest(size=size):
                data = random.Random(size).randbytes(size)
                self.assertEqual(codec.decode(codec.encode(data)), data)

    def test_raw_fallback_roundtrips(self):
        codec = Codec(native=False)
        for size in (0, 1, 131071, 131072, 131073, 262144):
            with self.subTest(size=size):
                data = b'X'*size
                self.assertEqual(codec.decode(codec.encode(data)), data)

    def test_fallback_frames_decode_with_system_libzstd(self):
        native = Codec()
        if not native.lib:
            self.skipTest('System libzstd unavailable')
        for size in (0, 1, 255, 256, 131072, 131073, 524288):
            data = random.Random(size).randbytes(size)
            self.assertEqual(native.decompress(raw_frame(data)), data)

    def test_reject_invalid_base64(self):
        with self.assertRaises(CodecError):
            Codec().decode('%%%not-base64')

    def test_reject_truncated_raw_frame(self):
        with self.assertRaises(CodecError):
            read_raw_frame(raw_frame(b'abc')[:-1])

    def test_reject_trailing_raw_data(self):
        with self.assertRaises(CodecError):
            read_raw_frame(raw_frame(b'abc')+b'junk')

    def test_compression_is_effective(self):
        native = Codec()
        if not native.lib:
            self.skipTest('System libzstd unavailable')
        self.assertLess(len(native.compress(WRL*1000)), len(WRL)*10)

    def test_unrecognized_frame_rejected(self):
        with self.assertRaises(CodecError):
            Codec().decompress(b'not a zstd frame')


class ParserTests(unittest.TestCase):
    def test_quoted_unicode_and_escapes(self):
        value = 'C:\\models\\µ spaced "part"\nname.step'
        self.assertEqual(parse('(model '+quote(value)+')').arg().value('(model '+quote(value)+')'), value)

    def test_whitespace_semantics(self):
        self.assertEqual(semantic('(a (b 2))'), semantic('( a\n(b  2) )'))

    def test_model_settings_not_ignored(self):
        self.assertNotEqual(semantic('(model "x" (scale (xyz 1 1 1)))', True),
                            semantic('(model "y" (scale (xyz 2 1 1)))', True))

    def test_model_references_are_ignored_only_when_requested(self):
        self.assertEqual(semantic('(model "x")', True), semantic('(model "y")', True))
        self.assertNotEqual(semantic('(model "x")'), semantic('(model "y")'))

    def test_reject_unbalanced(self):
        for text in ('(', '(a))', '(a "unterminated)', '(a |missing)', '(a) (b)', 'abc'):
            with self.subTest(text=text), self.assertRaises(FormatError):
                parse(text)

    def test_reject_overlapping_patches(self):
        with self.assertRaises(FormatError):
            patch('abcdef', [(0, 3, 'x'), (2, 4, 'y')])

    def test_duplicate_block_is_rejected(self):
        text = '(footprint "x" (embedded_files) (embedded_files))'
        with self.assertRaises(FormatError):
            embedded_entries(text)


class EmbeddingTests(TemporaryCase):
    def test_exact_original_model_bytes(self):
        plan = self.scan()
        output = plan.build()
        entries = embedded_entries(output)
        self.assertEqual(len(entries), 1)
        entry = next(iter(entries.values()))
        self.assertEqual(Codec().decode(entry.encoded), WRL)
        self.assertEqual(entry.checksum, sha256(WRL))
        self.assertIn(PREFIX+entry.name, output)

    def test_transform_suffix_is_byte_exact(self):
        plan = self.scan()
        out = plan.build()
        before = parse(plan.original).nodes(plan.original, 'model')[0]
        after = parse(out).nodes(out, 'model')[0]
        self.assertEqual(plan.original[before.arg().end:before.end], out[after.arg().end:after.end])

    def test_unrelated_footprint_content_is_unchanged(self):
        plan = self.scan()
        self.assertEqual(semantic(plan.original, True), semantic(plan.build(), True))
        self.assertIn('; comment: preserve formatting and unknown fields', plan.build())

    def test_crlf_transform_preservation(self):
        plan = self.scan(newline='\r\n')
        output = plan.build()
        before = parse(plan.original).nodes(plan.original, 'model')[0]
        after = parse(output).nodes(output, 'model')[0]
        self.assertEqual(plan.original[before.arg().end:before.end], output[after.arg().end:after.end])

    def test_multiple_models_all_preserved(self):
        second = self.root/'part.step'; second.write_bytes(bytes(range(256))*10)
        plan = self.scan([str(self.model), str(second)])
        self.assertEqual(len(plan.actionable), 2)
        out = plan.build()
        decoded = {Codec().decode(e.encoded) for e in embedded_entries(out).values()}
        self.assertEqual(decoded, {WRL, second.read_bytes()})
        self.assertEqual(len(parse(out).nodes(out, 'model')), 2)

    def test_same_source_payload_deduplicated(self):
        plan = self.scan([str(self.model)]*3)
        self.assertEqual(len(embedded_entries(plan.build())), 1)
        self.assertEqual(len(self.planner.cache), 1)

    def test_same_basename_different_files_do_not_collide(self):
        other = self.root/'other'; other.mkdir()
        model2 = other/self.model.name; model2.write_bytes(WRL+b'\n#different\n')
        plan = self.scan([str(self.model), str(model2)])
        self.assertEqual(len(embedded_entries(plan.build())), 2)

    def test_skip_already_embedded_is_idempotent(self):
        output = self.scan().build()
        second = self.planner.scan(output, source_dir=self.root)
        self.assertEqual(second.rows[0].status, 'Embedded')
        self.assertEqual(second.build(), output)

    def test_unchecked_model_unchanged(self):
        plan = self.scan()
        plan.rows[0].checked = False
        self.assertEqual(plan.build(), plan.original)

    def test_missing_path_is_non_destructive(self):
        plan = self.scan(['${MISSING_VAR}/x.step'])
        self.assertEqual(plan.rows[0].status, 'Needs attention')
        self.assertEqual(plan.build(), plan.original)

    def test_locate_override(self):
        text = footprint(['/gone/a.step'])
        plan = self.planner.scan(text, overrides={0: str(self.model)})
        self.assertTrue(plan.rows[0].ready)
        self.assertEqual(Codec().decode(next(iter(embedded_entries(plan.build()).values())).encoded), WRL)

    def test_board_embedded_payload_can_be_localized(self):
        existing = next(iter(embedded_entries(self.scan().build()).values()))
        text = footprint([PREFIX+existing.name])
        plan = self.planner.scan(text, pool={existing.name: existing})
        self.assertEqual(plan.rows[0].status, 'Localize embedded')
        self.assertIn(existing.name, embedded_entries(plan.build()))

    def test_metadata_only_payload_is_replaced_once(self):
        entry = next(iter(embedded_entries(self.scan().build()).values()))
        extra = '(embedded_files (file (name %s) (type model) (checksum %s)))' % (quote(entry.name), quote(entry.checksum))
        text = footprint([PREFIX+entry.name]*2, extra=extra)
        plan = self.planner.scan(text, pool={entry.name: entry})
        self.assertEqual(len(embedded_entries(plan.build())), 1)
        self.assertTrue(embedded_entries(plan.build())[entry.name].encoded)

    def test_missing_embedded_payload_is_reported(self):
        plan = self.scan([PREFIX+'missing.step'])
        self.assertEqual(plan.rows[0].status, 'Missing payload')
        self.assertEqual(plan.build(), plan.original)

    def test_other_embedded_files_preserved(self):
        encoded = Codec().encode(b'font-data')
        extra = '(embedded_files '+make_entry('font.bin', encoded, sha256(b'font-data'))+')'
        plan = self.scan(extra=extra)
        self.assertEqual(embedded_entries(plan.build())['font.bin'].encoded, encoded)

    def test_existing_same_bytes_different_compressor_is_reused(self):
        first = self.scan()
        row = first.rows[0]
        other_encoding = Codec(native=False).encode(WRL)
        # A native hash may be MMH3 instead of SHA256. The source digest must
        # remain an independent SHA256 for external-file freshness checks.
        extra = '(embedded_files '+make_entry(row.target, other_encoding, 'a'*32)+')'
        plan = self.scan(extra=extra)
        self.assertEqual(plan.rows[0].digest, sha256(WRL))
        verify_sources([plan])
        self.assertEqual(embedded_entries(plan.build())[row.target].encoded, other_encoding)

    def test_external_textures_are_not_claimed_portable(self):
        self.model.write_bytes(b'#VRML V2.0 utf8\nImageTexture { url "texture.png" }')
        plan = self.scan()
        self.assertFalse(plan.rows[0].ready)
        self.assertIn('dependencies', plan.rows[0].detail)

    def test_compressed_vrml_dependencies_detected(self):
        wrz = self.root/'part.wrz'
        wrz.write_bytes(gzip.compress(b'#VRML V2.0 utf8\nInline { url [ "child.wrl" ] }'))
        plan = self.scan([str(wrz)])
        self.assertFalse(plan.rows[0].ready)

    def test_compound_model_extension_is_preserved(self):
        model = self.root/'part.step.gz'
        data = gzip.compress(b'ISO-10303-21; synthetic payload for byte-preservation test')
        model.write_bytes(data)
        plan = self.scan([str(model)])
        self.assertTrue(plan.rows[0].target.endswith('.step.gz'))
        self.assertEqual(Codec().decode(plan.rows[0].payload.encoded), data)

    def test_binary_model_data_roundtrip(self):
        model = self.root/'opaque.step'; data = random.Random(9).randbytes(400000); model.write_bytes(data)
        out = self.scan([str(model)]).build()
        self.assertEqual(Codec().decode(next(iter(embedded_entries(out).values())).encoded), data)

    def test_unicode_and_spaces_in_model_path(self):
        model = self.root/'µ spaced part.wrl'; model.write_bytes(WRL)
        self.assertTrue(self.scan([str(model)]).rows[0].ready)

    def test_scan_cancellation(self):
        with self.assertRaises(InterruptedError):
            self.planner.scan(footprint([str(self.model)]), cancelled=lambda: True)

    def test_randomized_transform_preservation(self):
        rng = random.Random(713)
        for i in range(100):
            settings = ''.join('\n (%s (xyz %s))' % (key, ' '.join('%.9f' % rng.uniform(-100, 100) for _ in range(3)))
                               for key in ('scale', 'rotate', 'offset'))
            plan = self.scan(settings=settings)
            before, after = plan.original, plan.build()
            self.assertEqual(semantic(before, True), semantic(after, True), i)
            self.assertIn(settings, after)

    def test_empty_model_is_rejected(self):
        self.model.write_bytes(b'')
        self.assertFalse(self.scan().rows[0].ready)

    def test_model_change_since_preview_is_detected(self):
        plan = self.scan()
        self.model.write_bytes(WRL+b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            verify_sources([plan])


class ResolutionTests(TemporaryCase):
    def test_project_variable(self):
        self.assertEqual(self.resolver.resolve('${KIPRJMOD}/model.wrl'), self.model)

    def test_nested_variables(self):
        resolver = Resolver(self.root, {'A': '${B}', 'B': str(self.root)})
        self.assertEqual(resolver.resolve('${A}/model.wrl'), self.model)

    def test_legacy_alias(self):
        self.assertEqual(self.resolver.resolve(':ROOT:model.wrl'), self.model)

    def test_old_version_model_variable(self):
        resolver = Resolver(self.root, {'KICAD10_3DMODEL_DIR': str(self.root)})
        self.assertEqual(resolver.resolve('${KICAD6_3DMODEL_DIR}/model.wrl'), self.model)

    def test_recursive_variable_blocked(self):
        resolver = Resolver(self.root, {'A': '${B}', 'B': '${A}'})
        with self.assertRaises(ResolutionError):
            resolver.resolve('${A}/model.wrl')

    def test_remote_paths_not_fetched(self):
        with self.assertRaises(ResolutionError):
            self.resolver.resolve('https://example.test/model.step')

    def test_ambiguous_relative_paths_are_blocked(self):
        source = self.root/'library'; source.mkdir(); (source/'model.wrl').write_bytes(WRL)
        with self.assertRaisesRegex(ResolutionError, 'Ambiguous'):
            self.resolver.resolve('model.wrl', source)

    def test_source_relative_path(self):
        source = self.root/'library'; source.mkdir(); (source/'unique.wrl').write_bytes(WRL)
        self.assertEqual(self.resolver.resolve('unique.wrl', source), source/'unique.wrl')

    def test_backslash_paths_are_normalized(self):
        self.assertEqual(self.resolver.resolve('${ROOT}\\model.wrl'), self.model)


class StorageTests(TemporaryCase):
    def test_backup_write_and_restore(self):
        plan = self.file_plan()
        job = storage.embed_files([plan], self.root)
        self.assertEqual(plan.source_path.read_bytes(), plan.build().encode('utf-8'))
        manifest = json.loads((job/'manifest.json').read_text())
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual((job/manifest['files'][0]['backup']).read_bytes(), plan.original.encode('utf-8'))
        self.assertEqual(storage.restore_files(job/'manifest.json'), 1)
        self.assertEqual(plan.source_path.read_bytes(), plan.original.encode('utf-8'))

    def test_footprint_change_since_preview_is_detected(self):
        plan = self.file_plan()
        plan.source_path.write_text(plan.original+'\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            storage.embed_files([plan], self.root)
        self.assertFalse((self.root/'.embed_3d_plugin-backups').exists())

    def test_restore_refuses_later_edits(self):
        plan = self.file_plan(); job = storage.embed_files([plan], self.root)
        plan.source_path.write_bytes(plan.source_path.read_bytes()+b'\n; later work\n')
        with self.assertRaisesRegex(ValueError, 'Later edits'):
            storage.restore_files(job/'manifest.json')
        self.assertIn(b'later work', plan.source_path.read_bytes())

    def test_native_validation_failure_changes_nothing(self):
        plan = self.file_plan()
        def reject(*_):
            raise ValueError('native rejected')
        with self.assertRaisesRegex(ValueError, 'native rejected'):
            storage.embed_files([plan], self.root, reject)
        self.assertEqual(plan.source_path.read_bytes(), plan.original.encode('utf-8'))

    def test_multi_file_rollback(self):
        one, two = self.file_plan('one.kicad_mod'), self.file_plan('two.kicad_mod')
        original_write = storage.atomic_write
        failed = False
        def faulty(path, data, mode=None):
            nonlocal failed
            if path == two.source_path and not failed:
                failed = True
                raise OSError('injected write failure')
            return original_write(path, data, mode)
        with mock_patch.object(storage, 'atomic_write', side_effect=faulty):
            with self.assertRaisesRegex(RuntimeError, 'injected write failure'):
                storage.embed_files([one, two], self.root)
        self.assertEqual(one.source_path.read_bytes(), one.original.encode('utf-8'))
        self.assertEqual(two.source_path.read_bytes(), two.original.encode('utf-8'))

    def test_failure_after_replace_is_rolled_back(self):
        plan = self.file_plan()
        original_write, failed = storage.atomic_write, False
        def faulty(path, data, mode=None):
            nonlocal failed
            result = original_write(path, data, mode)
            if path == plan.source_path and not failed:
                failed = True
                raise OSError('injected post-replace failure')
            return result
        with mock_patch.object(storage, 'atomic_write', side_effect=faulty):
            with self.assertRaisesRegex(RuntimeError, 'post-replace failure'):
                storage.embed_files([plan], self.root)
        self.assertEqual(plan.source_path.read_bytes(), plan.original.encode('utf-8'))

    def test_duplicate_target_is_rejected(self):
        plan = self.file_plan()
        with self.assertRaisesRegex(ValueError, 'unique'):
            storage.embed_files([plan, plan], self.root)

    def test_manifest_retains_original_path_and_transform(self):
        plan = self.file_plan(); job = storage.embed_files([plan], self.root)
        data = json.loads((job/'manifest.json').read_text())
        model = data['plans'][0]['models'][0]
        self.assertEqual(model['original_reference'], str(self.model))
        self.assertIn('(scale (xyz 0.125 2.50 0.333333))', model['settings_original'])

    def test_corrupted_backup_refuses_restore(self):
        plan = self.file_plan(); job = storage.embed_files([plan], self.root)
        data = json.loads((job/'manifest.json').read_text())
        (job/data['files'][0]['backup']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            storage.restore_files(job/'manifest.json')


if __name__ == '__main__':
    unittest.main()
