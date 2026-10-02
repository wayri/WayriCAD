"""Native multi-subsheet extraction without any source PCB."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
import importlib
from test_sections_native import make_fixture, s, sx, sch, model


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_SECTIONS') == '1', 'native KiCad opt-in')
class SchematicSectionsNative(unittest.TestCase):
    def test_whole_project_schematic_only_omits_board(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            spec, _ = make_fixture(base/'source')
            before = s.fingerprint(base/'source')
            selection = importlib.import_module(s.__package__ + '.source_selection')
            request = {'whole_project': True, 'sheet_paths': [], 'max_depth': None,
                       'include_layout': False, 'region_mm': None}
            result = selection.materialize_selection(spec, request, base/'schematic-only')
            self.assertEqual(len(result), 1)
            self.assertFalse(Path(result[0].project).with_suffix('.kicad_pcb').exists())
            self.assertEqual(len(sch.discover(result[0], sch.new_uuid(), require_board=False).symbols), 1)
            self.assertEqual(before, s.fingerprint(base/'source'))

    def test_multiple_schematic_only_sections_and_stale_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            spec, first = make_fixture(base/'source')
            root = sx.load(base/'source/board.kicad_sch')
            child = sx.load(base/'source/child.kicad_sch')
            second_id = sch.new_uuid()
            second = '/'+sx.value(root,'uuid')+'/'+second_id
            node = copy.deepcopy(sx.children(root, 'sheet')[0])
            sx.put(node, 'uuid', sx.q(second_id))
            sx.prop(node, 'Sheetname')[2] = sx.q('Other')
            sx.prop(node, 'Sheetfile')[2] = sx.q('other.kicad_sch')
            root.append(node)
            symbol = sx.children(child, 'symbol')[0]
            sx.put(child, 'uuid', sx.q(sch.new_uuid()))
            sx.put(symbol, 'uuid', sx.q(sch.new_uuid()))
            sx.prop(symbol, 'Reference')[2] = sx.q('R2')
            sx.put(symbol, 'instances', ['project',sx.q('board'),
                ['path',sx.q(second),['reference',sx.q('R2')],['unit','1']]])
            sx.save(base/'source/other.kicad_sch', child)
            sx.save(base/'source/board.kicad_sch', root)
            (base/'source/board.kicad_pcb').unlink()
            before = s.fingerprint(base/'source')
            plan = s.preview_schematic_sections(spec, [first, second])
            self.assertEqual([r['components'] for r in plan['report']], [1,1])
            extracted = s.apply_schematic_sections(plan, base/'extracted')
            self.assertEqual(len(extracted), 2)
            self.assertEqual(len({x.alias for x in extracted}), 2)
            for item in extracted:
                model.validate_section_origin(item)
                self.assertIsNone(item.section_origin['region_mm'])
                source = sch.discover(item, sch.new_uuid(), require_board=False)
                self.assertEqual(len(source.symbols), 1)
                self.assertFalse(source.pcb_file.exists())
            self.assertEqual(before, s.fingerprint(base/'source'))
            (base/'source/board.kicad_pro').write_text('{"changed":true}')
            with self.assertRaisesRegex(model.MergeError, 'changed since preview'):
                s.apply_schematic_sections(plan, base/'stale')
            self.assertFalse((base/'stale').exists())

    def test_duplicate_and_overlapping_selection_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            spec, path = make_fixture(Path(temp).resolve()/'source')
            with self.assertRaisesRegex(model.MergeError, 'distinct'):
                s.preview_schematic_sections(spec, [path,path])


if __name__ == '__main__':
    unittest.main()
