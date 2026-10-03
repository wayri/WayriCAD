"""Generic copper-loss regressions; native workflow: FUSION_NATIVE_COPPER=1."""
import copy
from dataclasses import asdict
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_fusion_copper_test'
pkg = ModuleType(PACKAGE); pkg.__path__ = [str(ROOT)]; sys.modules[PACKAGE] = pkg
sx = importlib.import_module(PACKAGE + '.sexpr')
repair = importlib.import_module(PACKAGE + '.repair')
copper = importlib.import_module(PACKAGE + '.copper_preservation')
netlist = importlib.import_module(PACKAGE + '.netlist')
model = importlib.import_module(PACKAGE + '.model')
board_module = importlib.import_module(PACKAGE + '.board')


def uid(index):
    return f'11111111-1111-4111-8111-{index:012d}'


def fixture():
    board = sx.loads(f'''(kicad_pcb
      (footprint "Lib:Part" (property "Reference" "J1")
        (pad "1" smd rect (net "OLD")) (pad "2" smd rect (net "OLD")))
      (segment (start 1 1) (end 2 1) (width .2) (layer "F.Cu") (net "OLD") (uuid "{uid(1)}"))
      (arc (start 2 1) (mid 3 2) (end 2 3) (width .2) (layer "F.Cu") (net "OLD") (uuid "{uid(2)}"))
      (via (at 2 1) (size .6) (drill .3) (layers "F.Cu" "B.Cu") (net "OLD") (uuid "{uid(3)}"))
      (zone (net "OLD") (layer "F.Cu") (uuid "{uid(4)}")
        (polygon (pts (xy 0 0) (xy 4 0) (xy 4 4)))
        (filled_polygon (layer "F.Cu") (pts (xy .1 .1) (xy 3.9 .1) (xy 3.9 3.9))))
      (group "module" (uuid "{uid(5)}") (members "{uid(1)}" "{uid(2)}" "{uid(3)}" "{uid(4)}")))''')
    return board


def net(nets):
    return netlist.Netlist(nets=nets, pins={pin: name for name, pins in nets.items() for pin in pins})


class CopperPolicyTests(unittest.TestCase):
    def test_rename_preserves_every_route_plane_fill_and_group(self):
        board = fixture(); before = copy.deepcopy(board)
        schematic = net({'NEW': {('J1', '1'), ('J1', '2'), ('J2', '1')}})
        mapping, changed = repair.net_partition_map(board, schematic)
        self.assertFalse(changed)
        report = copper.remap_preserved_copper(board, schematic, mapping)
        self.assertEqual(report['removed_copper_count'], 0)
        self.assertEqual(copper.copper_geometry(before), copper.copper_geometry(board))
        self.assertEqual(sx.children(before, 'group'), sx.children(board, 'group'))
        self.assertEqual(sx.children(sx.child(before, 'zone'), 'filled_polygon'),
                         sx.children(sx.child(board, 'zone'), 'filled_polygon'))
        self.assertEqual({board_module.net_name(item, {}) for item in copper.copper_items(board)}, {'NEW'})

    def test_split_even_with_same_name_blocks_atomically_with_all_identities(self):
        board = fixture(); before = copy.deepcopy(board)
        schematic = net({'OLD': {('J1', '1')}, 'OTHER': {('J1', '2')}})
        mapping, _ = repair.net_partition_map(board, schematic)
        with self.assertRaises(copper.CopperReviewRequired) as caught:
            copper.remap_preserved_copper(board, schematic, mapping, invalidate_fill=True)
        self.assertEqual(board, before)
        issue = caught.exception.report['blocked_nets'][0]
        self.assertEqual(issue['counts'], {'arc': 1, 'segment': 1, 'via': 1, 'zone': 1})
        self.assertEqual({x['uuid'] for x in issue['items']}, {uid(i) for i in range(1, 5)})
        self.assertIn('J1.2 -> OTHER', str(caught.exception))
        self.assertIn(uid(4), str(caught.exception))

    def test_merge_and_orphan_copper_require_review(self):
        for orphan in (False, True):
            board = fixture()
            if orphan:
                sx.put(sx.child(board, 'zone'), 'net', sx.q('UNANCHORED'))
                schematic = net({'NEW': {('J1', '1'), ('J1', '2')}})
            else:
                sx.put(sx.children(sx.child(board, 'footprint'), 'pad')[1], 'net', sx.q('OTHER'))
                schematic = net({'NEW': {('J1', '1'), ('J1', '2')}})
            mapping, _ = repair.net_partition_map(board, schematic)
            before = copy.deepcopy(board)
            with self.assertRaises(copper.CopperReviewRequired):
                copper.remap_preserved_copper(board, schematic, mapping)
            self.assertEqual(board, before)

    def test_new_geometry_invalidates_caches_only_after_successful_proof(self):
        board = fixture(); before = copy.deepcopy(board)
        schematic = net({'OLD': {('J1', '1'), ('J1', '2')}})
        report = copper.remap_preserved_copper(board, schematic, {'OLD': 'OLD'}, invalidate_fill=True)
        self.assertEqual(report['invalidated_zone_fill_uuids'], [uid(4)])
        self.assertTrue(report['zone_refill_required'])
        self.assertFalse(sx.children(sx.child(board, 'zone'), 'filled_polygon'))
        self.assertEqual(copper.copper_geometry(board), copper.copper_geometry(before))
        self.assertEqual(sx.child(board, 'group'), sx.child(before, 'group'))

    def test_footprint_zone_is_checked_but_polygon_arcs_and_keepouts_are_not_tracks(self):
        board = fixture(); zone = sx.child(board, 'zone'); board.remove(zone)
        sx.child(board, 'footprint').append(zone)
        sx.child(sx.child(zone, 'polygon'), 'pts').append(
            ['arc', ['start', '4', '4'], ['mid', '2', '5'], ['end', '0', '4']])
        keepout = ['zone', ['net', sx.q('unmapped')], ['keepout', ['tracks', 'not_allowed']]]
        board.append(keepout)
        schematic = net({'NEW': {('J1', '1'), ('J1', '2')}})
        mapping, _ = repair.net_partition_map(board, schematic)
        report = copper.remap_preserved_copper(board, schematic, mapping)
        self.assertEqual(report['preserved_copper_counts'], {'arc': 1, 'segment': 1, 'via': 1, 'zone': 1})
        self.assertEqual(board_module.net_name(zone, {}), 'NEW')
        self.assertEqual(board_module.net_name(keepout, {}), 'unmapped')


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_COPPER') == '1', 'Opt-in native KiCad repair workflow')
class NativeCopperRepairTests(unittest.TestCase):
    def make_fixture(self, folder):
        # Existing public, synthetic fixture: one resistor, two tracks, via, plane.
        sys.path.insert(0, str(ROOT / 'tests'))
        try:
            from test_sections_native import make_fixture
            spec, _ = make_fixture(folder)
        finally:
            sys.path.remove(str(ROOT / 'tests'))
        return model.SourceSpec(**asdict(spec))

    def test_native_rename_retains_plane_via_identity_and_source_archive(self):
        import pcbnew
        with tempfile.TemporaryDirectory(prefix='fusion-copper-rename-') as temporary:
            root = Path(temporary); spec = self.make_fixture(root / 'source')
            path = Path(spec.project).with_suffix('.kicad_pcb')
            native_board = pcbnew.LoadBoard(str(path))
            self.assertTrue(pcbnew.ZONE_FILLER(native_board).Fill(native_board.Zones()))
            pcbnew.SaveBoard(str(path), native_board)
            tree = sx.load(path); table = board_module.net_table(tree)
            first = sx.children(sx.children(tree, 'footprint')[0], 'pad')[0]
            renamed = board_module.net_name(first, table)
            for item in sx.walk(tree):
                if sx.tag(item) in {'pad', 'segment', 'via', 'zone'} and board_module.net_name(item, table) == renamed:
                    sx.put(item, 'net', sx.q('LegacyNet'))
                    if sx.child(item, 'net_name') is not None:
                        sx.put(item, 'net_name', sx.q('LegacyNet'))
            sx.save(path, tree)
            before = repair.fingerprint(path.parent)
            plan = repair.preview_repair(spec)
            self.assertEqual(before, repair.fingerprint(path.parent))
            result, report = repair.apply_repair(plan, root / 'candidate')
            self.assertEqual(before, repair.fingerprint(path.parent))
            candidate = Path(result.project).with_suffix('.kicad_pcb'); parsed = sx.load(candidate)
            self.assertEqual(copper.copper_geometry(tree), copper.copper_geometry(parsed))
            self.assertEqual(report['native_uuid_associations'], 'passed')
            self.assertEqual(report['copper_preservation']['removed_copper_count'], 0)
            self.assertTrue(sx.children(sx.child(parsed, 'zone'), 'filled_polygon'))
            board = pcbnew.LoadBoard(str(candidate))
            self.assertEqual(len(list(board.Zones())), 1)
            self.assertEqual(sum(isinstance(t, pcbnew.PCB_VIA) for t in board.GetTracks()), 1)
            with zipfile.ZipFile(candidate.parent / 'original-source.zip') as archive:
                self.assertEqual(archive.read(path.name), path.read_bytes())
            drc = netlist.KiCadCLI().drc(candidate, candidate.parent / 'native-drc.json')
            self.assertFalse(drc['schematic_parity'])
            self.assertFalse([v for v in drc['violations'] if 'short' in v['type']])

    def test_native_changed_partition_refuses_preview_and_publishes_nothing(self):
        with tempfile.TemporaryDirectory(prefix='fusion-copper-block-') as temporary:
            root = Path(temporary); spec = self.make_fixture(root / 'source')
            path = Path(spec.project).with_suffix('.kicad_pcb'); tree = sx.load(path)
            pads = sx.children(sx.children(tree, 'footprint')[0], 'pad')
            sx.put(pads[1], 'net', sx.q(board_module.net_name(pads[0], board_module.net_table(tree))))
            sx.save(path, tree); before = repair.fingerprint(path.parent)
            with self.assertRaisesRegex(model.MergeError, 'No copper was removed'):
                repair.preview_repair(spec)
            plan = repair.RepairPlan(spec, before, False, {})
            with self.assertRaisesRegex(model.MergeError, 'No copper was removed'):
                repair.apply_repair(plan, root / 'blocked')
            self.assertFalse((root / 'blocked').exists())
            self.assertFalse(list(root.glob('.fusion-repair-*')))
            self.assertEqual(before, repair.fingerprint(path.parent))


if __name__ == '__main__':
    unittest.main()
