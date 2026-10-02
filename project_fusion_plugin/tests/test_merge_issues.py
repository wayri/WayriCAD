import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('fusion_issue_test')
package.__path__ = [str(ROOT)]
sys.modules.setdefault('fusion_issue_test', package)
issues = importlib.import_module('fusion_issue_test.merge_issues')
sx = importlib.import_module('fusion_issue_test.sexpr')
SourceSpec = importlib.import_module('fusion_issue_test.model').SourceSpec
MergeError = importlib.import_module('fusion_issue_test.model').MergeError


def footprint(ref, uid, *, board_only=True, path='', net=''):
    fp = ['footprint', sx.q('Test:Part'), ['uuid', uid],
          ['property', sx.q('Reference'), sx.q(ref)]]
    if board_only:
        fp.append(['attr', 'board_only'])
    if path:
        fp.append(['path', sx.q(path)])
    if net:
        fp.append(['pad', sx.q('1'), 'smd', 'rect', ['net', sx.q(net)]])
    return fp


class MergeIssueTests(unittest.TestCase):
    def source(self, root, footprints, records=()):
        project = root / 'Example.kicad_pro'
        project.write_text('{}', encoding='utf-8')
        sx.save(root / 'Example.kicad_pcb', ['kicad_pcb', *footprints])
        spec = SourceSpec(str(project), 'Example', variant='<Default>')
        fake = types.SimpleNamespace(project_file=project,
                                     pcb_file=root / 'Example.kicad_pcb',
                                     symbols=list(records))
        return spec, fake

    def test_duplicate_placeholders_have_distinct_reviewed_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            spec, fake = self.source(root, [footprint('G***', 'a'), footprint('G***', 'b')])
            with patch.object(issues, 'discover', return_value=fake):
                report = issues.scan_source(spec)
            self.assertEqual([r['suggested_reference'] for r in report['issues']],
                             ['MECH1', 'MECH2'])
            with self.assertRaises(MergeError):
                issues.validate_resolutions(report, {})
            selected = {r['id']: r['action'] for r in report['issues']}
            copy = root / 'detached.kicad_pcb'
            copy.write_bytes((root / 'Example.kicad_pcb').read_bytes())
            changed = issues.apply_to_detached_board(copy, report, selected)
            self.assertEqual(len(changed), 2)
            self.assertEqual([issues.fp_reference(fp) for fp in sx.children(sx.load(copy), 'footprint')],
                             ['MECH1', 'MECH2'])
            self.assertEqual([issues.fp_reference(fp) for fp in sx.children(sx.load(root / 'Example.kicad_pcb'), 'footprint')],
                             ['G***', 'G***'])

    def test_schematic_correlated_duplicate_is_blocking(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record = types.SimpleNamespace(old_ref='J1', node=['symbol', ['property', sx.q('Footprint'), sx.q('Test:Part')]])
            spec, fake = self.source(root, [footprint('J1', 'a', board_only=False, path='/one'),
                                            footprint('J1', 'b', board_only=False, path='/two')], [record])
            with patch.object(issues, 'discover', return_value=fake):
                report = issues.scan_source(spec)
            self.assertTrue(all(row['action'] is None for row in report['issues']))
            with self.assertRaises(MergeError):
                issues.validate_resolutions(report, {})

    def test_blank_selected_footprint_requires_explicit_retention(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record = types.SimpleNamespace(old_ref='J1', node=['symbol', ['property', sx.q('Footprint'), sx.q('')]])
            spec, fake = self.source(root, [footprint('J1', 'a', board_only=False, path='/one')], [record])
            with patch.object(issues, 'discover', return_value=fake):
                report = issues.scan_source(spec)
            row = report['issues'][0]
            self.assertEqual(row['code'], 'blank_variant_footprint')
            self.assertEqual(row['suggested_footprint'], 'Test:Part')
            with self.assertRaises(MergeError):
                issues.validate_resolutions(report, {})
            issues.validate_resolutions(report, {row['id']: 'retain_placed_footprint'})


if __name__ == '__main__':
    unittest.main()
