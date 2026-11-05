"""Read-only saved BOM extraction and field-anchor identity checks."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from review_comments_plugin.bom_review import bom_anchor, load_bom


def symbol(uid, ref, unit=1, *, variant='', fields=''):
    return (f'(symbol (lib_id "Demo:Part") (uuid "{uid}") (unit {unit}) '
            f'(in_bom yes) (dnp no) (property "Reference" "{ref}") '
            f'(property "Value" "10k") {fields} '
            f'(instances (project "Demo" (path "/root" (reference "{ref}") '
            f'(unit {unit}) {variant}))))')


class SavedBomTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_pcb_fields_flags_hashes_and_field_anchor(self):
        board = self.write('repo/Board.kicad_pcb',
            '(kicad_pcb (footprint "Demo:R" (uuid "fp-1") '
            '(property "Reference" "R1") (property "Value" "47k") '
            '(property "MPN" "DEMO-47K") (attr smd exclude_from_bom dnp)))')
        result = load_bom(board, self.root)
        self.assertEqual(result['kind'], 'pcb')
        self.assertEqual(result['columns'], ['Reference', 'Value', 'Footprint', 'MPN'])
        row = result['rows'][0]
        self.assertEqual((row['reference'], row['fields']['MPN']), ('R1', 'DEMO-47K'))
        self.assertEqual((row['flags']['dnp'], row['flags']['in_bom']), (True, False))
        self.assertEqual(len(row['id']), 68)
        self.assertEqual(result['source_hashes']['repo/Board.kicad_pcb'], hashlib.sha256(board.read_bytes()).hexdigest())
        scope = dict(provider='github', repository='wayri/WayriCAD', ref='a' * 40,
                     file='repo/Board.kicad_pcb')
        anchor = bom_anchor(scope, row, result['source_hashes'], field='MPN')
        self.assertEqual(anchor['kind'], 'bom-field')
        self.assertEqual(anchor['context']['field'], 'MPN')
        self.assertEqual(anchor['context']['rowId'], row['id'])
        self.assertEqual(anchor['context']['sourceFiles'], result['source_hashes'])
        self.assertNotIn('field', anchor)
        self.assertEqual(bom_anchor(scope, row, result['source_hashes'], variant='*')['variant'], '*')
        with self.assertRaisesRegex(ValueError, 'another saved design'):
            bom_anchor(dict(scope, file='other.kicad_pcb'), row, result['source_hashes'])
        with self.assertRaisesRegex(ValueError, 'absent'):
            bom_anchor(scope, row, result['source_hashes'], field='NoSuchField')

    def test_schematic_multiunit_custom_fields_and_explicit_variant(self):
        variant = '(variant (name "Economy") (field (name "MPN") (value "LOW-COST")) (dnp yes))'
        first = symbol('unit-a', 'U1', 1, variant=variant, fields='(property "MPN" "FULL")')
        second = symbol('unit-b', 'U1', 2, variant=variant, fields='(property "MPN" "FULL")')
        sheet = self.write('repo/Demo.kicad_sch',
                           f'(kicad_sch (version 20260306) (uuid "root") {first} {second})')
        project = self.write('repo/Demo.kicad_pro', json.dumps({'schematic': {'variants': [
            {'name': 'Economy', 'description': 'Lower-cost assembly'}]}}))
        result = load_bom(sheet, self.root)
        self.assertEqual(len(result['rows']), 1)
        row = result['rows'][0]
        self.assertEqual(row['member_uuids'], ['unit-a', 'unit-b'])
        self.assertEqual(row['fields']['MPN'], 'FULL')
        self.assertEqual(row['variant_overrides']['Economy']['fields']['MPN'], 'LOW-COST')
        self.assertTrue(row['variant_overrides']['Economy']['flags']['dnp'])
        self.assertEqual(result['variants'], ['<Default>', 'Economy'])
        self.assertEqual(result['variant_descriptions']['Economy'], 'Lower-cost assembly')
        self.assertEqual(result['inventory'][row['id']]['fields'], ['MPN', 'Reference', 'Value'])
        self.assertIn('repo/Demo.kicad_pro', result['source_hashes'])
        self.assertEqual(result['source_hashes']['repo/Demo.kicad_pro'], hashlib.sha256(project.read_bytes()).hexdigest())
        scope = dict(file='repo/Demo.kicad_sch', provider='github', repository='wayri/WayriCAD', ref='a' * 40)
        self.assertEqual(bom_anchor(scope, row, result['source_hashes'], variant='Economy')['variant'], 'Economy')
        with self.assertRaisesRegex(ValueError, 'explicitly available'):
            bom_anchor(scope, row, result['source_hashes'], variant='Invented')

    def test_repeated_sheet_instances_keep_distinct_rows_and_source_hashes(self):
        root = self.write('repo/Demo.kicad_sch',
            '(kicad_sch (version 20260306) (uuid "root") '
            '(sheet (uuid "sheet-a") (property "Sheetname" "A") '
            '(property "Sheetfile" "Channel.kicad_sch") '
            '(instances (project "Demo" (path "/root")))) '
            '(sheet (uuid "sheet-b") (property "Sheetname" "B") '
            '(property "Sheetfile" "Channel.kicad_sch") '
            '(instances (project "Demo" (path "/root")))))')
        self.write('repo/Channel.kicad_sch',
            '(kicad_sch (version 20260306) (uuid "child") '
            '(symbol (lib_id "Demo:Part") (uuid "same-uuid") (unit 1) '
            '(property "Reference" "R1") (property "Value" "10k") '
            '(instances (project "Demo" '
            '(path "/root/sheet-a" (reference "R1") (unit 1)) '
            '(path "/root/sheet-b" (reference "R1") (unit 1))))))')
        result = load_bom(root, self.root)
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(len({row['id'] for row in result['rows']}), 2)
        self.assertEqual({row['sheet_path'] for row in result['rows']}, {'/A/', '/B/'})
        self.assertTrue(all(row['duplicate_reference'] for row in result['rows']))
        self.assertEqual(set(result['source_hashes']), {'repo/Demo.kicad_sch', 'repo/Channel.kicad_sch'})
        self.assertTrue(all(row['origin_file'] == 'repo/Demo.kicad_sch' for row in result['rows']))

    def test_rejects_conflicting_units_missing_child_and_path_traversal(self):
        first = symbol('unit-a', 'U1', 1, fields='(property "MPN" "A")')
        second = symbol('unit-b', 'U1', 2, fields='(property "MPN" "B")')
        path = self.write('Demo.kicad_sch', f'(kicad_sch (uuid "root") {first} {second})')
        with self.assertRaisesRegex(ValueError, 'conflicting multi-unit'):
            load_bom(path)
        for filename, error in [('Missing.kicad_sch', 'missing'),
                                ('../Outside.kicad_sch', 'traverse')]:
            path.write_text('(kicad_sch (uuid "root") (sheet (uuid "s") '
                            f'(property "Sheetfile" "{filename}") '
                            '(instances (project "Demo" (path "/root")))))', encoding='utf-8')
            with self.assertRaisesRegex((ValueError, FileNotFoundError), error):
                load_bom(path)

    def test_repository_public_schematic_fixture_is_read_only(self):
        repository = Path(__file__).resolve().parents[2]
        path = repository / 'bom_studio_plugin/examples/vendor_splitting/BOM_Demo.kicad_sch'
        result = load_bom(path, repository)
        self.assertGreater(len(result['rows']), 4)
        self.assertIn('Economy', result['variants'])
        self.assertIn('Qualification', result['variants'])
        self.assertIn('bom_studio_plugin/examples/vendor_splitting/Channel.kicad_sch', result['source_hashes'])

    def test_rejects_linked_child_and_bounded_source(self):
        root = self.write('Demo.kicad_sch',
            '(kicad_sch (uuid "root") (sheet (uuid "sheet") '
            '(property "Sheetfile" "Child.kicad_sch") '
            '(instances (project "Demo" (path "/root")))))')
        actual = self.write('Real.kicad_sch', '(kicad_sch (uuid "child"))')
        linked = self.root / 'Child.kicad_sch'
        try:
            linked.symlink_to(actual)
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaisesRegex(ValueError, 'linked'):
                load_bom(root)
            linked.unlink()
        linked.write_text('(kicad_sch (uuid "child"))', encoding='utf-8')
        from unittest.mock import patch
        with patch('review_comments_plugin.bom_review.MAX_FILE_BYTES', 10):
            with self.assertRaisesRegex(ValueError, 'limit'):
                load_bom(root)


if __name__ == '__main__':
    unittest.main()
