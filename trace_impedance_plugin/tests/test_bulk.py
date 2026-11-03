"""Whole-board extraction never invents one impedance for branched nets."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from trace_impedance_plugin import bulk, cli


class Track:
    def __init__(self, uid, net='DATA'):
        self.m_Uuid = SimpleNamespace(AsString=lambda: uid)
        self.net = net

    def GetNetname(self): return self.net
    def GetLayer(self): return 0
    def GetStart(self): return SimpleNamespace(x=0, y=0)
    def GetEnd(self): return SimpleNamespace(x=1000000, y=0)
    def GetWidth(self): return 200000


class Geometry:
    def __init__(self, engine):
        self.layers = [0, 2]; self.islands = []
        self.pcb = SimpleNamespace(PCB_TRACK=Track, PCB_VIA=type('Via', (), {}), PCB_ARC=type('Arc', (), {}))

    def reference(self, *args, **kwargs): return []


class Engine:
    def __init__(self, tracks=None):
        self.board = SimpleNamespace(GetTracks=lambda: tracks or [Track('a'), Track('b'), Track('c', 'CLK')], Zones=lambda: [])
        self.measured = []

    def net_names(self): return ['DATA', 'CLK', 'GND']
    def pads_for_net(self, net): return ['J1.1', 'U1.1', 'U2.1'] if net == 'DATA' else []
    def _layer_name(self, layer): return 'F.Cu' if layer == 0 else 'B.Cu'
    def _new_result(self, *args): return SimpleNamespace(blockers=[], as_report=lambda: {'segments': []})
    def _measure_edges(self, result, edges, *args):
        self.measured.extend(edges)
        result.as_report = lambda: {'segments': [dict(item_uuid=edge['item'].m_Uuid.AsString(),
            kind=edge['kind'], layer='F.Cu', status='ok', impedance_ohm=50., reference_layer='', reference_net='') for edge in edges]}


class BulkTests(unittest.TestCase):
    def extract(self, engine=None, **kwargs):
        with patch.object(bulk, 'CopperGeometry', Geometry):
            return bulk.extract_board(engine or Engine(), infer_references=False, **kwargs)

    def test_all_sections_in_branched_net_have_no_net_equivalent(self):
        engine = Engine(); report = self.extract(engine)
        rows = {row['net']: row for row in report['nets']}
        self.assertEqual(len(rows['DATA']['sections']), 2)
        self.assertEqual(len(engine.measured), 3)
        self.assertIsNone(rows['DATA']['net_equivalent_impedance_ohm'])
        self.assertEqual(rows['DATA']['pads'], ['J1.1', 'U1.1', 'U2.1'])
        self.assertEqual(report['status'], 'partial')  # GND has no routed sections

    def test_bundles_deduplicate_work_not_member_results(self):
        definitions = {'schema': 'wayricad.rlc-bundles/v1', 'bundles': [
            {'name': 'Bus', 'nets': ['DATA', 'CLK']}, {'name': 'Data only', 'nets': ['DATA']}]}
        report = self.extract(bundles=definitions)
        self.assertEqual(report['coverage']['physical_items'], 3)
        self.assertEqual(len(report['nets']), 2)
        self.assertEqual(len(report['bundles']), 2)
        self.assertIsNone(report['bundles'][0]['coupled_impedance_ohm'])
        self.assertIsNone(report['bundles'][0]['mutual_inductance_nh'])

    def test_budget_retains_omitted_identities_and_never_passes(self):
        report = self.extract(max_sections=1)
        self.assertEqual(report['status'], 'section_budget_exceeded')
        self.assertFalse(report['coverage']['complete'])
        self.assertEqual(report['coverage']['extracted_sections'], 1)
        self.assertEqual(report['coverage']['omitted_item_uuids'], ['a', 'b'])

    def test_cancel_before_first_section_is_explicit(self):
        report = self.extract(cancelled=lambda: True)
        self.assertEqual(report['status'], 'cancelled')
        self.assertEqual(report['coverage']['completed_items'], 0)
        self.assertEqual(report['coverage']['omitted_item_uuids'], ['a', 'b', 'c'])

    def test_bad_bundle_and_budget_rejected(self):
        for document in ([{'name': 'B', 'nets': ['missing']}], [{'name': 'B', 'nets': ['DATA', 'DATA']}],
                         {'schema': 'old', 'bundles': []}):
            with self.assertRaises(ValueError): self.extract(bundles=document)
        for value in (0, True, 1.5):
            with self.assertRaises(ValueError): self.extract(max_sections=value)

    def test_cli_options_preserve_exact_names(self):
        args = cli.parser().parse_args(['bulk', 'Example.kicad_pcb', '--net', '/Sheet/D0', '--net', 'D1',
                                       '--bundles', 'bus.json', '--max-sections', '10'])
        self.assertEqual(args.net, ['/Sheet/D0', 'D1'])
        self.assertEqual(args.max_sections, 10)

    def test_orphan_and_unassigned_tracks_are_not_omitted(self):
        report = self.extract(Engine([Track('orphan', 'NO_PAD_NET'), Track('unassigned', '')]))
        rows = {row['net']: row for row in report['nets']}
        self.assertEqual(len(rows['NO_PAD_NET']['sections']), 1)
        self.assertEqual(len(rows['']['sections']), 1)
        self.assertEqual(rows['']['status'], 'partial')
        self.assertEqual(rows['']['display_name'], '(unassigned copper)')

    def test_inference_uses_copper_coverage_and_preserves_arbitrary_name(self):
        geometry = object.__new__(bulk._ReferenceGeometry)
        geometry.layers = [0, 2]; geometry.engine = Engine()
        plane = {'id': 'plane', 'net': 'RETURN_A'}
        def coverage(signal, a, b, width, layer, net, all_matches):
            self.assertEqual(layer, 'B.Cu')
            return [(.2, 'B.Cu', 4.2, plane)]
        with patch.object(bulk.CopperGeometry, 'reference', side_effect=coverage):
            rows = geometry.reference_candidates(0, (0, 0), (1, 0), .2, 'DATA')
        self.assertEqual(rows[0][3]['net'], 'RETURN_A')

    def test_overlapping_references_on_same_layer_remain_ambiguous(self):
        geometry = object.__new__(bulk._ReferenceGeometry)
        geometry.reference_candidates = lambda *args: [
            (.2, 'B.Cu', 4.2, {'id': 'a', 'net': 'GND'}),
            (.2, 'B.Cu', 4.2, {'id': 'b', 'net': 'RETURN'})]
        self.assertIsNone(geometry.reference(0, (0, 0), (1, 0), .2))
        self.assertEqual(geometry.reference(0, (0, 0), (1, 0), .2, all_matches=True), [])


def test_report_cannot_overwrite_bundle_definition(tmp_path):
    bundle = tmp_path / 'bundles.json'
    bundle.write_text('{"schema":"wayricad.rlc-bundles/v1","bundles":[]}')
    original = bundle.read_bytes()
    with patch.object(cli, 'analyze') as analyze:
        assert cli.main(['bulk', 'Example.kicad_pcb', '--bundles', str(bundle), '--output', str(bundle)]) == 1
        analyze.assert_not_called()
    assert bundle.read_bytes() == original


if __name__ == '__main__': unittest.main()
