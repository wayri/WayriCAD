"""Saved schematic grouping checks; no pcbnew dependency or design writes."""

import tempfile
import hashlib
import unittest
from pathlib import Path
from unittest import mock

from component_arranger_plugin.grouping import GroupingError, board_groups, infer_schematic_groups


LIB = '(lib_symbols (symbol "Device:R" (symbol "R_1_1" (pin passive line (at 0 0 0) (number "1")))))'


def symbol(ref, x, y=0, extra=''):
    return f'(symbol (lib_id "Device:R") (at {x} {y} 0) (unit 1) (uuid "{ref}") (property "Reference" "{ref}") {extra})'


def wire(x1, y1, x2, y2):
    return f'(wire (pts (xy {x1} {y1}) (xy {x2} {y2})))'


def schematic(body, library=LIB):
    return f'(kicad_sch (uuid "root") {library} {body})'


class GroupingTests(unittest.TestCase):
    def run_source(self, body, library=LIB, **options):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'example.kicad_sch'
            text = schematic(body, library)
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
        self.assertEqual(result['pin_links'][0]['length_mm'], 50)
        self.assertFalse(self.run_source(body, max_wire_mm=49)['pin_links'])

    def test_pin_links_keep_individual_shortest_paths_and_fields(self):
        library = '(lib_symbols (symbol "Device:R" (symbol "R_1_1" (pin passive line (at 0 0 0) (number "1")) (pin passive line (at 2 0 0) (number "2")))))'
        body = symbol('R2', 10) + symbol('R1', 0) + wire(0, 0, 12, 0)
        result = self.run_source(body, library=library, max_wire_mm=10)
        self.assertEqual(result['pin_links'], [
            {'from_symbol': '/root/R1', 'to_symbol': '/root/R2', 'from_reference': 'R1', 'to_reference': 'R2',
             'from_pin': a, 'to_pin': b, 'length_mm': length, 'kind': 'drawn_wire', 'sheet_path': '/root'}
            for a, b, length in [('1', '1', 10), ('2', '1', 8), ('2', '2', 10)]])
        self.assertEqual(result['symbols'][1]['pins'], [{'number': '1', 'position_mm': (0, 0)}, {'number': '2', 'position_mm': (2, 0)}])
        reordered = self.run_source(symbol('R1', 0) + symbol('R2', 10) + wire(0, 0, 12, 0), library=library, max_wire_mm=10)
        self.assertEqual(result['pin_links'], reordered['pin_links'])

    def test_pin_path_chooses_shorter_route_not_first_route(self):
        body = symbol('R1', 0) + symbol('R2', 10) + wire(0, 0, 0, 20) + wire(0, 20, 10, 20) + wire(10, 20, 10, 0) + wire(0, 0, 10, 0)
        self.assertEqual(self.run_source(body)['pin_links'][0]['length_mm'], 10)

    def test_pin_links_require_drawn_wire_and_ignore_label_proximity_and_power_jumps(self):
        body = symbol('R1', 0) + symbol('R2', 3) + '(global_label "GND" (at 0 0 0)) (global_label "GND" (at 3 0 0))'
        result = self.run_source(body, include_global_links=True, proximity_mm=4)
        self.assertFalse(result['pin_links'])
        self.assertFalse(self.run_source(symbol('R1', 0) + symbol('R2', 0))['pin_links'])

    def test_label_at_crossing_cannot_create_pin_path(self):
        body = symbol('R1', -5) + symbol('R2', 5) + symbol('R3', 0, -5) + symbol('R4', 0, 5) + wire(-5, 0, 5, 0) + wire(0, -5, 0, 5)
        for extra in ('', '(label "X" (at 0 0 0))'):
            links = self.run_source(body + extra, include_label_links=True)['pin_links']
            self.assertEqual([(link['from_reference'], link['to_reference']) for link in links], [('R1', 'R2'), ('R3', 'R4')])

    def test_ambiguous_alternate_pins_and_duplicate_numbers_are_not_mapped(self):
        library = '(lib_symbols (symbol "Device:R" (symbol "R_1_1" (pin passive line (at 0 0 0) (number "1")) (pin passive line (at 2 0 0) (number "2"))) (symbol "R_1_2" (pin passive line (at 0 0 0) (number "1")) (pin passive line (at 4 0 0) (number "2")))))'
        result = self.run_source(symbol('R1', 0), library=library)
        self.assertEqual(result['symbols'][0]['pins'], [{'number': '1', 'position_mm': (0, 0)}])
        self.assertTrue(any('alternate' in warning for warning in result['warnings']))
        explicit = self.run_source(symbol('R1', 0, extra='(convert 2)'), library=library)
        self.assertEqual(explicit['symbols'][0]['pins'][1]['position_mm'], (4, 0))
        duplicate = library.replace('(number "2")', '(number "1")')
        self.assertFalse(self.run_source(symbol('R1', 0, extra='(convert 1)'), library=duplicate)['symbols'][0]['pins'])

    def test_duplicate_pin_geometry_deduplicates_and_missing_numbers_stay_unknown(self):
        doubled = LIB.replace('(number "1"))', '(number "1")) (pin passive line (at 0 0 0) (number "1"))')
        result = self.run_source(symbol('R1', 0) + symbol('R2', 10) + wire(0, 0, 10, 0), library=doubled)
        self.assertEqual(len(result['pin_links']), 1)
        unnumbered = self.run_source(symbol('R1', 0), library=LIB.replace(' (number "1")', ''))
        self.assertEqual(unnumbered['symbols'][0]['pins_mm'], [(0, 0)])
        self.assertFalse(unnumbered['symbols'][0]['pins'])

    def test_numbered_pin_instance_unit_and_conflicting_occurrences(self):
        library = '(lib_symbols (symbol "Device:R" (symbol "R_1_1" (pin passive line (at 0 0 0) (number "1"))) (symbol "R_2_1" (pin passive line (at 2 0 0) (number "2")))))'
        instance = '(instances (project "demo" (path "/root" (reference "R1") (unit 2))))'
        result = self.run_source(symbol('R?', 0, extra=instance), library=library)
        self.assertEqual(result['symbols'][0]['pins'], [{'number': '2', 'position_mm': (2, 0)}])
        self.assertEqual(result['symbols'][0]['unit'], 2)
        self.assertIsInstance(result['symbols'][0]['unit'], int)
        ambiguous = '(instances (project "demo" (path "/root" (reference "R1") (unit 2))) (project "other" (path "/root" (reference "R2") (unit 1))))'
        result = self.run_source(symbol('R?', 0, extra=ambiguous))
        self.assertFalse(result['symbols'][0]['pins'])
        self.assertTrue(any('ambiguous schematic occurrence' in w for w in result['warnings']))

    def test_pin_metadata_work_limit_is_explicit(self):
        from component_arranger_plugin import grouping
        warnings, links = [], []
        symbols = [{'id': '/root/R1', 'reference': 'R1', 'sheet_path': '/root',
                    'pins': [{'number': '1', 'position_mm': (0, 0)}]}]
        grouping._drawn_pin_links({(0, 0): {(1, 0): 1}}, symbols, 25, links, warnings, {'remaining': 0})
        self.assertTrue(any('truncated' in warning for warning in warnings))

    def test_pin_metadata_link_limit_is_explicit(self):
        result = self.run_source(''.join(symbol(f'R{i:02}', i) for i in range(96)) + wire(0, 0, 95, 0), max_wire_mm=100)
        self.assertEqual(len(result['pin_links']), 4096)
        self.assertTrue(any('truncated' in warning for warning in result['warnings']))

    def test_source_fingerprints_bind_exact_root_and_repeated_child_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, child = (Path(directory) / name for name in ('root.kicad_sch', 'child.kicad_sch'))
            root.write_text(schematic('(sheet (uuid "one") (property "Sheetfile" "child.kicad_sch")) (sheet (uuid "two") (property "Sheetfile" "child.kicad_sch"))'), encoding='utf-8')
            child.write_bytes(('\ufeff' + schematic(symbol('R1', 0) + symbol('R2', 10) + wire(0, 0, 10, 0))).encode('utf-8'))
            result = infer_schematic_groups(root)
            self.assertEqual(result['source_fingerprints'], {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in (root, child)})
            self.assertEqual([link['sheet_path'] for link in result['pin_links']], ['/root/one', '/root/two'])
            original_read = Path.read_bytes
            child_reads = 0
            def changed_read(path):
                nonlocal child_reads
                raw = original_read(path)
                if path == child.resolve():
                    child_reads += 1
                    if child_reads > 1:
                        return raw + b'\n'
                return raw
            with mock.patch.object(Path, 'read_bytes', changed_read):
                with self.assertRaisesRegex(GroupingError, 'changed while loading'):
                    infer_schematic_groups(root)

    def test_metadata_only_matches_pin_links_and_skips_cluster_and_label_work(self):
        from component_arranger_plugin import grouping
        body = symbol('R1', 0) + symbol('R2', 10) + wire(0, 0, 10, 0) + '(label "SUPPLY" (at 0 0 0)) (label "SUPPLY" (at 10 0 0))'
        full = self.run_source(body)
        distances = grouping._distances
        def bounded_distances(graph, starts, limit, budget):
            self.assertEqual(len(starts), 1)
            self.assertIsNotNone(budget)
            return distances(graph, starts, limit, budget)
        with mock.patch.object(grouping, '_clusters', side_effect=AssertionError('metadata must not cluster')):
            with mock.patch.object(grouping, '_distances', side_effect=bounded_distances):
                metadata = self.run_source(body, metadata_only=True)
        self.assertEqual(metadata['pin_links'], full['pin_links'])
        self.assertEqual(metadata['clusters'], [])
        self.assertEqual(metadata['wire_clusters'], [])
        self.assertEqual(metadata['label_links'], [])

    def test_metadata_references_filter_pairs_and_keep_wire_junctions(self):
        body = symbol('R1', 0) + symbol('R2', 10) + symbol('R3', 5, 5) + wire(0, 0, 10, 0) + wire(5, 0, 5, 5)
        result = self.run_source(body, metadata_only=True, references={'R2', 'R3'})
        self.assertEqual([s['reference'] for s in result['symbols']], ['R2', 'R3'])
        self.assertEqual([(p['from_reference'], p['to_reference'], p['length_mm']) for p in result['pin_links']], [('R2', 'R3', 10)])
        self.assertFalse(self.run_source(body, metadata_only=True, references=set())['pin_links'])

    def test_metadata_oversized_graph_preflight_skips_graph_construction(self):
        from component_arranger_plugin import grouping
        body = symbol('R1', 0) + symbol('R2', 10) + ''.join(wire(i, 0, i + 1, 0) for i in range(1001))
        with mock.patch.object(grouping, '_wire_graph', side_effect=AssertionError('oversized graph must not be constructed')):
            result = self.run_source(body, metadata_only=True)
        self.assertFalse(result['pin_links'])
        self.assertTrue(any('graph-construction' in warning for warning in result['warnings']))

    def test_metadata_byte_and_pin_limits_warn_without_guessed_links(self):
        from component_arranger_plugin import grouping
        body = symbol('R1', 0) + symbol('R2', 10) + wire(0, 0, 10, 0)
        with mock.patch.object(grouping, '_METADATA_MAX_BYTES', 32):
            with mock.patch.object(grouping, '_parse', side_effect=AssertionError('oversized input must not parse')):
                result = self.run_source(body, metadata_only=True)
        self.assertFalse(result['pin_links'])
        self.assertTrue(any('byte' in warning for warning in result['warnings']))
        with mock.patch.object(grouping, '_METADATA_MAX_PINS', 1):
            result = self.run_source(body, metadata_only=True)
        self.assertFalse(result['pin_links'])
        self.assertTrue(any('pin endpoint' in warning for warning in result['warnings']))

    def test_metadata_custody_and_sheet_budget_are_deterministic(self):
        from component_arranger_plugin import grouping
        with tempfile.TemporaryDirectory() as directory:
            root, child = (Path(directory) / name for name in ('root.kicad_sch', 'child.kicad_sch'))
            root.write_text(schematic(''.join(f'(sheet (uuid "{name}") (property "Sheetfile" "child.kicad_sch"))' for name in ('one', 'two'))), encoding='utf-8')
            child.write_text(schematic(symbol('R1', 0) + symbol('R2', 10) + wire(0, 0, 10, 0)), encoding='utf-8')
            first = infer_schematic_groups(root, metadata_only=True, references={'R1', 'R2'})
            self.assertEqual(first, infer_schematic_groups(root, metadata_only=True, references={'R2', 'R1'}))
            self.assertEqual(first['source_fingerprints'], {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in (root, child)})
            with mock.patch.object(grouping, '_METADATA_MAX_SHEETS', 2):
                limited = infer_schematic_groups(root, metadata_only=True)
            self.assertFalse(limited['pin_links'])
            self.assertTrue(any('sheet limit' in warning for warning in limited['warnings']))

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
            lib = '(lib_symbols (symbol "Device:R" (symbol "R_1_1" (pin passive line (at 2 0 0) (number "1"))) (symbol "R_2_1" (pin passive line (at 20 0 0) (number "2")))))'
            body = symbol('R1', 10).replace('(at 10 0 0)', '(at 10 0 90)') + symbol('R2', 10, -2)
            path.write_text(f'(kicad_sch (uuid "root") {lib} {body})', encoding='utf-8')
            result = infer_schematic_groups(path)
            self.assertEqual(result['symbols'][0]['pins_mm'], [(10.0, -2.0)])
            self.assertEqual(result['symbols'][0]['pins'], [{'number': '1', 'position_mm': (10, -2)}])
            self.assertNotIn((10.0, -20.0), result['symbols'][0]['pins_mm'])
            body = symbol('R1', 10, extra='(mirror y)')
            path.write_text(f'(kicad_sch (uuid "root") {lib} {body})', encoding='utf-8')
            self.assertEqual(infer_schematic_groups(path)['symbols'][0]['pins_mm'], [(8.0, 0.0)])
            self.assertEqual(infer_schematic_groups(path)['symbols'][0]['pins'], [{'number': '1', 'position_mm': (8, 0)}])

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
