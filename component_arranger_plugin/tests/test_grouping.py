"""Saved schematic grouping checks; no pcbnew dependency or design writes."""

import tempfile
import unittest
from pathlib import Path

from component_arranger_plugin.grouping import GroupingError, board_groups, infer_schematic_groups


LIB = '(lib_symbols (symbol "Device:R" (symbol "R_1_1" (pin passive line (at 0 0 0)))))'


def symbol(ref, x, y=0, extra=''):
    return f'(symbol (lib_id "Device:R") (at {x} {y} 0) (unit 1) (uuid "{ref}") (property "Reference" "{ref}") {extra})'


def wire(x1, y1, x2, y2):
    return f'(wire (pts (xy {x1} {y1}) (xy {x2} {y2})))'


def schematic(body):
    return f'(kicad_sch (uuid "root") {LIB} {body})'


class GroupingTests(unittest.TestCase):
    def run_source(self, body, **options):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'example.kicad_sch'
            text = schematic(body)
            source.write_text(text, encoding='utf-8')
            result = infer_schematic_groups(source, **options)
            self.assertEqual(source.read_text(encoding='utf-8'), text)
            return result

    def test_wire_length_uses_drawn_path_and_threshold(self):
        body = symbol('R1', 0) + symbol('R2', 10) + wire(0, 0, 0, 20) + wire(0, 20, 10, 20) + wire(10, 20, 10, 0)
        self.assertEqual(len(self.run_source(body, max_wire_mm=49)['clusters']), 2)
        result = self.run_source(body, max_wire_mm=50)
        self.assertEqual(result['clusters'][0]['references'], ['R1', 'R2'])
        self.assertEqual(result['clusters'][0]['evidence'][0]['length_mm'], 50)

    def test_t_branch_splits_wire_and_joins_all(self):
        body = symbol('R1', 0) + symbol('R2', 10) + symbol('R3', 5, 5) + wire(0, 0, 10, 0) + wire(5, 0, 5, 5)
        self.assertEqual(len(self.run_source(body)['clusters']), 1)

    def test_crossings_require_junction(self):
        body = symbol('R1', -5) + symbol('R2', 5) + symbol('R3', 0, -5) + symbol('R4', 0, 5) + wire(-5, 0, 5, 0) + wire(0, -5, 0, 5)
        self.assertEqual(len(self.run_source(body)['clusters']), 2)
        self.assertEqual(len(self.run_source(body + '(junction (at 0 0))')['clusters']), 1)

    def test_labels_require_explicit_acceptance(self):
        body = symbol('R1', 0) + symbol('R2', 50) + '(label "SUPPLY" (at 0 0 0)) (label "SUPPLY" (at 50 0 0))'
        result = self.run_source(body)
        self.assertEqual(len(result['clusters']), 2)
        self.assertTrue(result['label_links'][0]['requires_confirmation'])
        self.assertFalse(result['label_links'][0]['accepted'])
        self.assertEqual(len(self.run_source(body, include_label_links=True)['clusters']), 1)

    def test_global_acceptance_separate_from_local(self):
        body = symbol('R1', 0) + symbol('R2', 50) + '(global_label "GND" (at 0 0 0)) (global_label "GND" (at 50 0 0))'
        self.assertEqual(len(self.run_source(body, include_label_links=True)['clusters']), 2)
        self.assertEqual(len(self.run_source(body, include_global_links=True)['clusters']), 1)

    def test_graphical_proximity_is_explicit_non_electrical_heuristic(self):
        body = symbol('R1', 0) + symbol('R2', 3)
        self.assertEqual(len(self.run_source(body)['clusters']), 2)
        result = self.run_source(body, proximity_mm=4)
        self.assertEqual(len(result['clusters']), 1)
        self.assertFalse(result['clusters'][0]['evidence'][0]['electrical_connection'])

    def test_repeated_child_instances_use_instance_reference_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            child = symbol('R?', 0, extra='(instances (project "demo" (path "/root/one" (reference "R10")) (path "/root/two" (reference "R20"))))')
            (folder / 'child.kicad_sch').write_text(schematic(child), encoding='utf-8')
            sheets = ''.join(f'(sheet (uuid "{uid}") (property "Sheetfile" "child.kicad_sch"))' for uid in ('one', 'two'))
            (folder / 'root.kicad_sch').write_text(schematic(sheets), encoding='utf-8')
            result = infer_schematic_groups(folder / 'root.kicad_sch')
            self.assertEqual([s['reference'] for s in result['symbols']], ['R10', 'R20'])
            self.assertEqual(len({s['id'] for s in result['symbols']}), 2)
            self.assertEqual([c['id'] for c in result['clusters']], ['A', 'B'])

    def test_global_links_across_child_sheets_are_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for number in (1, 2):
                (folder / f'{number}.kicad_sch').write_text(schematic(symbol(f'R{number}', 0) + '(global_label "GND" (at 0 0 0))'), encoding='utf-8')
            sheets = ''.join(f'(sheet (uuid "s{i}") (property "Sheetfile" "{i}.kicad_sch"))' for i in (1, 2))
            (folder / 'root.kicad_sch').write_text(schematic(sheets), encoding='utf-8')
            self.assertEqual(len(infer_schematic_groups(folder / 'root.kicad_sch')['clusters']), 2)
            self.assertEqual(len(infer_schematic_groups(folder / 'root.kicad_sch', include_global_links=True)['clusters']), 1)

    def test_invalid_missing_and_recursive_sources_are_actionable(self):
        with self.assertRaisesRegex(GroupingError, 'positive finite'):
            self.run_source('', max_wire_mm=-1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.kicad_sch'
            with self.assertRaisesRegex(GroupingError, 'Cannot read schematic'):
                infer_schematic_groups(path)
            path.write_text('(kicad_sch', encoding='utf-8')
            with self.assertRaisesRegex(GroupingError, 'Malformed'):
                infer_schematic_groups(path)
            path.write_text(schematic('(sheet (uuid "loop") (property "Sheetfile" "missing.kicad_sch"))'), encoding='utf-8')
            with self.assertRaisesRegex(GroupingError, 'Recursive'):
                infer_schematic_groups(path)
        with self.assertRaisesRegex(GroupingError, 'positive finite'):
            self.run_source('', max_wire_mm='bad')
        with self.assertRaisesRegex(GroupingError, 'Malformed'):
            self.run_source('(symbol (at bad 0) (property "Reference" "R1"))')

    def test_rotated_mirrored_library_pins_and_multiunit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'transform.kicad_sch'
            lib = '(lib_symbols (symbol "Device:R" (symbol "R_1_1" (pin passive line (at 2 0 0))) (symbol "R_2_1" (pin passive line (at 20 0 0)))))'
            body = symbol('R1', 10).replace('(at 10 0 0)', '(at 10 0 90)') + symbol('R2', 10, -2)
            path.write_text(f'(kicad_sch (uuid "root") {lib} {body})', encoding='utf-8')
            result = infer_schematic_groups(path)
            self.assertEqual(result['symbols'][0]['pins_mm'], [(10.0, -2.0)])
            self.assertNotIn((10.0, -20.0), result['symbols'][0]['pins_mm'])
            body = symbol('R1', 10, extra='(mirror y)')
            path.write_text(f'(kicad_sch (uuid "root") {lib} {body})', encoding='utf-8')
            self.assertEqual(infer_schematic_groups(path)['symbols'][0]['pins_mm'], [(8.0, 0.0)])

    def test_missing_embedded_pins_remain_unknown(self):
        result = self.run_source(symbol('R1', 0).replace('Device:R', 'Missing:R'))
        self.assertTrue(result['warnings'])
        self.assertFalse(result['symbols'][0]['pins_mm'])

    def test_stable_alphabetical_cluster_names_beyond_z(self):
        result = self.run_source(''.join(symbol(f'R{i:02}', i * 100) for i in range(28)))
        self.assertEqual(result['clusters'][-2]['id'], 'AA')
        self.assertEqual(result['clusters'][-1]['id'], 'AB')

    def test_board_selection_is_read_only_and_sheet_scope_separate(self):
        class Uuid:
            def __init__(self, text): self.text = text
            def AsString(self): return self.text
        class Footprint:
            def __init__(self, ref, selected): self.ref, self.selected, self.m_Uuid = ref, selected, Uuid(ref)
            def IsSelected(self): return self.selected
            def GetReference(self): return self.ref
            def GetPath(self): return Uuid('/root/sheet/' + self.ref)
        class Board:
            def __init__(self): self.parts = [Footprint('U1', True), Footprint('C1', False)]
            def GetFootprints(self): return self.parts
        board = Board()
        self.assertEqual(board_groups(board)['clusters'][0]['references'], ['U1'])
        self.assertEqual(board_groups(board, 'sheet')['clusters'][0]['references'], ['C1', 'U1'])
        self.assertEqual([p.selected for p in board.parts], [True, False])


if __name__ == '__main__':
    unittest.main()
