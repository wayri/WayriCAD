"""Connector review export contracts, including native rule-area round trips."""
import json
from pathlib import Path
import tempfile
import unittest
import subprocess

from wayricad_runtime.connector_review import _rules, export_connector_review, validate_connector_clearance
from wayricad_runtime.geometry import board_fingerprint
from wayricad_runtime.routing import FanoutPlan

try:
    import pcbnew
except ImportError:
    pcbnew = None


class RuleTextTests(unittest.TestCase):
    def test_existing_rules_keep_higher_priority_and_exact_text(self):
        existing = '(version 1)\n# Source rule\n(rule "existing" (constraint clearance (min 0.3mm)))\n'
        output = _rules(existing, '(rule "connector")\n')
        self.assertLess(output.index('(rule "connector"'), output.index('(rule "existing"'))
        self.assertIn('(rule "existing" (constraint clearance (min 0.3mm)))\n', output)
        self.assertEqual(output.count('(version 1)'), 1)

    def test_unsupported_header_is_not_rewritten(self):
        with self.assertRaises(ValueError):
            _rules('(version 2)', '(rule "connector")')


@unittest.skipIf(pcbnew is None, 'KiCad native Python required')
class NativeReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.kicad_pcb'
        self.board = pcbnew.BOARD()
        self.board.SetFileName(str(self.source))
        self.board.GetDesignSettings().m_MinClearance = pcbnew.FromMM(.1)
        for start, end in [((0, 0), (30, 0)), ((30, 0), (30, 30)),
                           ((30, 30), (0, 30)), ((0, 30), (0, 0))]:
            edge = pcbnew.PCB_SHAPE(self.board)
            edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
            edge.SetLayer(pcbnew.Edge_Cuts)
            edge.SetStart(self.pos(*start))
            edge.SetEnd(self.pos(*end))
            self.board.Add(edge)
        self.fp = pcbnew.FOOTPRINT(self.board)
        self.fp.SetReference('J1')
        self.fp.SetPosition(self.pos(10, 10))
        self.board.Add(self.fp)
        self.net = pcbnew.NETINFO_ITEM(self.board, '/Connector/Signal')
        self.board.Add(self.net)
        self.pad = pcbnew.PAD(self.fp)
        self.pad.SetNumber('1')
        self.pad.SetPosition(self.pos(10, 10))
        self.pad.SetSize(self.pos(.6, .6))
        self.pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        layers = pcbnew.LSET()
        layers.AddLayer(pcbnew.F_Cu)
        self.pad.SetLayerSet(layers)
        self.pad.SetNet(self.net)
        self.fp.Add(self.pad)
        pcbnew.SaveBoard(str(self.source), self.board)
        self.source.with_suffix('.kicad_pro').write_text(json.dumps({
            'board': {'design_settings': {'rules': {'min_clearance': .1}}},
            'net_settings': {'classes': [{'name': 'Default', 'clearance': .3}]}}))
        self.source.with_suffix('.kicad_dru').write_text('(version 1)\n(rule "retained" (condition "A.NetName == \'HIGH_VOLTAGE\'") (constraint clearance (min 1mm)))\n')
        self.plan = FanoutPlan(self.fp, self.pad, self.pos(10, 12), pcbnew.FromMM(.2),
                               pcbnew.FromMM(.6), pcbnew.FromMM(.3), start=self.pos(10, 10),
                               layer=pcbnew.F_Cu, net_code=self.net.GetNetCode(), clearance=pcbnew.FromMM(.15))
        self.plan.connector_region = [self.pos(9, 9), self.pos(11, 9), self.pos(11, 12), self.pos(9, 12)]
        self.plan.local_clearance = True

    @staticmethod
    def pos(x, y):
        return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))

    def test_export_preserves_live_board_source_files_and_rule_priority(self):
        before = board_fingerprint(self.board)
        originals = {p: p.read_bytes() for p in self.root.iterdir()}
        result = export_connector_review(self.board, pcbnew, [self.plan], self.root / 'review')
        self.assertEqual(self.board.GetFileName(), str(self.source))
        self.assertEqual(board_fingerprint(self.board), before)
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
        clone = pcbnew.LoadBoard(str(self.root / 'review' / result['board']))
        self.assertEqual(len(list(clone.GetTracks())), 1)
        zones = list(clone.Zones())
        self.assertEqual(len(zones), 1)
        self.assertTrue(zones[0].GetIsRuleArea())
        self.assertFalse(zones[0].GetDoNotAllowTracks())
        self.assertEqual(zones[0].GetLayer(), pcbnew.F_Cu)
        text = (self.root / 'review' / result['rules']).read_text()
        self.assertLess(text.index('(rule "WayriCAD connector'), text.index('(rule "retained'))
        self.assertIn('A.enclosedByArea', text)
        self.assertIn('B.enclosedByArea', text)
        self.assertIn('/Connector/Signal', text)
        self.assertEqual((self.root / 'review' / result['project']).read_bytes(), originals[self.source.with_suffix('.kicad_pro')])

    def test_existing_destination_and_floor_are_rejected_before_export(self):
        dest = self.root / 'review'
        dest.mkdir()
        with self.assertRaisesRegex(ValueError, 'new review directory'):
            export_connector_review(self.board, pcbnew, [self.plan], dest)
        with self.assertRaises(ValueError):
            validate_connector_clearance(self.board, pcbnew, pcbnew.FromMM(.09))
        self.source.with_suffix('.kicad_pro').write_text(json.dumps({'board': {'design_settings': {'rules': {'min_clearance': .2}}}}))
        with self.assertRaises(ValueError):
            export_connector_review(self.board, pcbnew, [self.plan], self.root / 'low-floor')
        self.assertFalse((self.root / 'low-floor').exists())

    def test_enlarged_area_encloses_endpoint_copper_and_hierarchical_names(self):
        result = export_connector_review(self.board, pcbnew, [self.plan], self.root / 'review')
        clone = pcbnew.LoadBoard(str(self.root / 'review' / result['board']))
        polygon = list(clone.Zones())[0].Outline()
        self.assertTrue(polygon.Contains(self.pos(10, 12.099)))
        self.assertFalse(polygon.Contains(self.pos(10, 12.2)))

    def test_unsaved_native_floor_is_retained_in_review_project(self):
        self.board.GetDesignSettings().m_MinClearance = pcbnew.FromMM(.2)
        self.plan.clearance = pcbnew.FromMM(.25)
        result = export_connector_review(self.board, pcbnew, [self.plan], self.root / 'review')
        project = json.loads((self.root / 'review' / result['project']).read_text())
        self.assertEqual(project['board']['design_settings']['rules']['min_clearance'], .2)
        self.assertEqual(project['net_settings']['classes'][0]['clearance'], .3)
        self.assertEqual(json.loads(self.source.with_suffix('.kicad_pro').read_text())['board']['design_settings']['rules']['min_clearance'], .1)

    def test_native_drc_applies_exception_only_inside_region(self):
        cli = Path(pcbnew.__file__).parents[2] / 'kicad-cli.exe'
        if not cli.exists():
            self.skipTest('KiCad CLI executable required')
        # The inside pair has 0.2 mm gap, below the default 0.3 mm but above
        # the requested 0.15 mm. The same pair outside must remain a violation.
        for index, (x, y) in enumerate(((10.8, 10), (20, 20), (20.8, 20)), 2):
            net = pcbnew.NETINFO_ITEM(self.board, 'NET' + str(index))
            self.board.Add(net)
            pad = pcbnew.PAD(self.fp)
            pad.SetNumber(str(index))
            pad.SetPosition(self.pos(x, y))
            pad.SetSize(self.pos(.6, .6))
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            layers = pcbnew.LSET()
            layers.AddLayer(pcbnew.F_Cu)
            pad.SetLayerSet(layers)
            pad.SetNet(net)
            self.fp.Add(pad)
        result = export_connector_review(self.board, pcbnew, [self.plan], self.root / 'review')
        report = self.root / 'drc.json'
        process = subprocess.run([str(cli), 'pcb', 'drc', '--format', 'json', '--output', str(report),
                                  str(self.root / 'review' / result['board'])], capture_output=True, text=True, timeout=60)
        self.assertEqual(process.returncode, 0, process.stderr)
        document = json.loads(report.read_text())
        self.assertFalse(any(row['type'] == 'lib_footprint_issues' and 'rule' in row.get('description', '').lower()
                             for row in document['violations']))
        violations = [row for row in document['violations'] if row['type'] == 'clearance']
        self.assertTrue(violations, 'The outside pair should retain its original clearance violation.')
        for row in violations:
            self.assertTrue(all(item['pos']['x'] > 15 for item in row['items']), row)


if __name__ == '__main__':
    unittest.main()
